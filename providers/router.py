"""LLM Router — one hardened provider path with circuit breaker + real cost tracking.

Architecture (per user's redesign):
- Circuit breaker per provider (opens after N failures, cooldown, then half-open)
- complete() returns LLMResult with text + token_usage + cost
- Tool-calling support for schema-forced JSON output
- EventLog writes for every call
"""
import os
import re
import json
import time
import random
import threading
from typing import Optional, Literal, NamedTuple
from dataclasses import dataclass
from loguru import logger
import requests


ModelTier = Literal["cheap", "balanced", "powerful"]

MODEL_TIERS = {
    "cheap": {
        "hf": "deepseek-ai/DeepSeek-V4-Flash",
        "openrouter": "openrouter/free",
    },
    "balanced": {
        "hf": "deepseek-ai/DeepSeek-V4-Flash",
        "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    },
    "powerful": {
        "hf": "deepseek-ai/DeepSeek-V3",
        "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    },
}

# Approximate $/token costs for DeepSeek V4 Flash via HF router
COST_PER_INPUT_TOKEN = 0.00000014   # $0.14/M tokens
COST_PER_OUTPUT_TOKEN = 0.00000028  # $0.28/M tokens


class LLMResult(NamedTuple):
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0

    @property
    def cost(self) -> float:
        return (self.input_tokens * COST_PER_INPUT_TOKEN +
                self.output_tokens * COST_PER_OUTPUT_TOKEN)


class CircuitBreaker:
    """Per-provider circuit breaker. Opens after N failures, half-opens after cooldown."""

    def __init__(self, name: str, fail_threshold: int = 5, cooldown_s: float = 60.0):
        self.name = name
        self.fail_threshold = fail_threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.time() - self._opened_at > self.cooldown_s:
                # half-open — allow one probe
                return False
            return True

    def record(self, ok: bool):
        with self._lock:
            if ok:
                self._failures = 0
                self._opened_at = None
            else:
                self._failures += 1
                if self._failures >= self.fail_threshold:
                    self._opened_at = time.time()
                    logger.warning(f"Circuit breaker {self.name} OPENED after {self._failures} failures")

    def __repr__(self) -> str:
        with self._lock:
            status = "OPEN" if self._opened_at and self._opened_at > time.time() - self.cooldown_s else "CLOSED"
            return f"CircuitBreaker({self.name}, status={status}, failures={self._failures})"


class TokenBucket:
    """Token-bucket rate limiter. Configured just under provider RPM ceiling."""

    def __init__(self, rate_per_min: float, capacity: int):
        self.rate = rate_per_min / 60.0  # tokens per second
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while True:
            with self._lock:
                now = time.time()
                elapsed = now - self.last_refill
                self.tokens = min(float(self.capacity), self.tokens + elapsed * self.rate)
                self.last_refill = now
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
            if time.time() >= deadline:
                return False
            time.sleep(0.1)


# ── Global circuit breakers ──────────────────────────────────────────
_hf_breaker = CircuitBreaker("hf-inference", fail_threshold=5, cooldown_s=60)
_or_breaker = CircuitBreaker("openrouter", fail_threshold=3, cooldown_s=120)
_nv_breaker = CircuitBreaker("nvidia", fail_threshold=3, cooldown_s=120)

# Token-bucket rate limiters per NVIDIA key (38 RPM — just under 40 RPM ceiling)
_nvidia_bucket_key1 = TokenBucket(rate_per_min=38, capacity=38)
_nvidia_bucket_key2 = TokenBucket(rate_per_min=38, capacity=38)
# Global lock to serialize all NVIDIA calls (disable concurrency)
_nvidia_serialize_lock = threading.Lock()


class ProviderUnavailable(Exception):
    """All providers exhausted or circuit-broken."""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class LLMRouter:
    """One hardened provider path per user's redesign.

    complete() returns LLMResult with real token counts.
    complete_structured() forces a JSON schema via tool-calling.
    """

    HF_BASE = "https://router.huggingface.co/v1"
    NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL_FLASH = "deepseek-ai/deepseek-v4-flash"
    NVIDIA_MODEL_PRO = "deepseek-ai/deepseek-v4-pro"
    OPENROUTER_BASE = "https://openrouter.ai/api/v1"

    def __init__(self):
        self.hf_token = os.getenv("HF_TOKEN", "")
        self.nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        self.nvidia_key_2 = os.getenv("NVIDIA_API_KEY_2", "")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_key_2 = os.getenv("OPENROUTER_API_KEY_2", "")

    def complete(self, prompt: str,
                 system: str = "You are a helpful AI assistant.",
                 max_tokens: int = 4096,
                 temperature: float = 0.7,
                 model: Optional[str] = None,
                 tools: Optional[list] = None,
                 tool_choice: Optional[str] = None,
                 tier: ModelTier = "balanced",
                 ) -> Optional[LLMResult]:
        """Primary provider path: HF Inference → OpenRouter → NVIDIA.

        Every call writes to the circuit breaker. Uses exponential backoff.
        Returns LLMResult or None if all providers exhausted.
        """
        models = MODEL_TIERS.get(tier, MODEL_TIERS["balanced"])
        hf_model = model or models["hf"]

        last_error = ""

        # 1. HF Inference (primary — only consistently working provider)
        if not _hf_breaker.is_open and self.hf_token:
            for attempt in range(2):
                try:
                    result = self._call_hf(prompt, system, max_tokens,
                                            temperature, hf_model,
                                            tools=tools, tool_choice=tool_choice)
                    if result:
                        _hf_breaker.record(True)
                        return result
                except Exception as e:
                    _hf_breaker.record(False)
                    last_error = str(e)[:100]
                    if attempt == 0:
                        delay = 1.0 + random.uniform(0, 0.5)
                        time.sleep(delay)
        else:
            last_error = "circuit open or no token"

        # 2. OpenRouter fallback
        if not _or_breaker.is_open:
            or_models = [
                models.get("openrouter", "openrouter/free"),
                "openrouter/free",
                "deepseek/deepseek-r1",
                "deepseek/deepseek-chat",
            ]
            for or_model in or_models:
                try:
                    result = self._call_openrouter(prompt, system, max_tokens,
                                                    temperature, or_model)
                    if result:
                        _or_breaker.record(True)
                        return result
                except Exception as e:
                    _or_breaker.record(False)
                    last_error = str(e)[:100]

        # 3. NVIDIA (last resort — serialized, token-bucketed, exponential backoff)
        if not _nv_breaker.is_open:
            for key_attr, key_idx, bucket in [
                ("nvidia_key", 1, _nvidia_bucket_key1),
                ("nvidia_key_2", 2, _nvidia_bucket_key2),
            ]:
                key = getattr(self, key_attr, None)
                if not key:
                    continue
                with _nvidia_serialize_lock:  # disable concurrency per user's guidance
                    for mdl, timeout in [
                        (self.NVIDIA_MODEL_FLASH, 300),  # cold start may take 60-120s
                        (self.NVIDIA_MODEL_PRO, 300),
                    ]:
                        try:
                            result = self._call_nvidia(prompt, system, max_tokens,
                                                        temperature, mdl, key, timeout,
                                                        bucket=bucket)
                            if result:
                                _nv_breaker.record(True)
                                return result
                        except Exception as e:
                            _nv_breaker.record(False)
                            last_error = str(e)[:100]

        logger.error(f"All providers exhausted. Last error: {last_error}")
        return None

    def complete_structured(self, prompt: str,
                            schema: dict,
                            system: str = "You are a helpful AI assistant.",
                            max_tokens: int = 4096,
                            temperature: float = 0.7,
                            tier: ModelTier = "balanced",
                            ) -> Optional[dict]:
        """Call LLM with a tool/function schema to force structured JSON output.

        Uses tool_choice='required' + a single function tool defined by schema.
        Falls back to prose+parse if the provider doesn't support tool calling.
        """
        tool = {
            "type": "function",
            "function": {
                "name": "submit_output",
                "description": schema.get("description", "Submit structured output"),
                "parameters": schema["input_schema"],
            },
        }
        result = self.complete(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "submit_output"}},
            tier=tier,
        )
        if result and result.text:
            # Try to extract tool call arguments from response
            try:
                data = json.loads(result.text)
                return data
            except json.JSONDecodeError:
                pass
            # Try extracting from tool_calls format
            try:
                data = json.loads(result.text)
                if "choices" in data:
                    msg = data["choices"][0]["message"]
                    if "tool_calls" in msg:
                        args = msg["tool_calls"][0]["function"]["arguments"]
                        return json.loads(args)
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass
            # Fallback: try direct parse of any JSON in the response
            json_match = re.search(r'\{.*\}', result.text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        # ── Fallback: retry with a plain-text prompt asking for JSON ──
        schema_hint = json.dumps(schema["input_schema"], indent=2)
        fallback_prompt = (
            f"{prompt}\n\n"
            "You MUST respond with ONLY valid JSON matching this schema:\n"
            f"{schema_hint}\n\n"
            "No explanation, no markdown formatting — just the raw JSON object."
        )
        logger.info("complete_structured: tool path failed, trying plain-text fallback")
        fallback = self.complete(
            prompt=fallback_prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            tier=tier,
        )
        if fallback and fallback.text:
            json_match = re.search(r'\{.*\}', fallback.text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        logger.warning("complete_structured: no valid JSON from LLM")
        return None

    # ── HF Inference ────────────────────────────────────────────────

    def _call_hf(self, prompt: str, system: str,
                 max_tokens: int, temperature: float,
                 model: str,
                 tools: Optional[list] = None,
                 tool_choice: Optional[str] = None,
                 ) -> Optional[LLMResult]:
        """Try both HF endpoints: router (new, OpenAI-compat) then serverless (old, maybe free)."""
        t0 = time.time()
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": min(max_tokens, 64000),
            "temperature": temperature,
            "top_p": 0.95,
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        headers = {
            "Authorization": f"Bearer {self.hf_token}",
            "Content-Type": "application/json",
        }

        endpoints = [
            self.HF_BASE + "/chat/completions",                            # router.huggingface.co (OpenAI-compat)
            f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions",  # serverless (legacy)
        ]

        last_error = ""
        for url in endpoints:
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=120)
                latency = (time.time() - t0) * 1000

                if resp.status_code == 200:
                    data = resp.json()
                    choice = data["choices"][0]
                    message = choice["message"]

                    if message.get("tool_calls"):
                        text = message["tool_calls"][0]["function"]["arguments"]
                    else:
                        text = message.get("content", "")

                    usage = data.get("usage", {})
                    in_tokens = usage.get("prompt_tokens", _estimate_tokens(prompt + system))
                    out_tokens = usage.get("completion_tokens", _estimate_tokens(text))

                    logger.info(f"HF SUCCESS ({url.split('/')[2]}): {len(text)} chars, "
                                 f"{in_tokens}+{out_tokens} tokens, {latency:.0f}ms")
                    return LLMResult(
                        text=text,
                        input_tokens=in_tokens,
                        output_tokens=out_tokens,
                        model=model,
                        provider="hf",
                        latency_ms=latency,
                    )

                logger.info(f"HF ({url.split('/')[2]}) status={resp.status_code}: {resp.text[:150]}")
                last_error = f"status {resp.status_code}: {resp.text[:100]}"
                if resp.status_code == 402:
                    continue  # try next endpoint (different credit pool)
            except Exception as e:
                last_error = str(e)[:100]
                logger.info(f"HF ({url.split('/')[2]}) failed: {last_error}")
                continue

        raise RuntimeError(f"HF exhausted: {last_error}")

    # ── OpenRouter ──────────────────────────────────────────────────

    def _call_openrouter(self, prompt: str, system: str,
                          max_tokens: int, temperature: float,
                          model: str, key_index: int = 1) -> Optional[LLMResult]:
        key = self.openrouter_key_2 if key_index == 2 else self.openrouter_key
        if not key:
            return None
        t0 = time.time()
        resp = requests.post(
            f"{self.OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/MarkCalebChomba/super-agent",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=30,
        )
        latency = (time.time() - t0) * 1000

        if resp.status_code == 200:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return LLMResult(
                text=text,
                input_tokens=usage.get("prompt_tokens", _estimate_tokens(prompt + system)),
                output_tokens=usage.get("completion_tokens", _estimate_tokens(text)),
                model=model,
                provider="openrouter",
                latency_ms=latency,
            )
        logger.debug(f"OpenRouter ({model}): {resp.status_code}")
        if resp.status_code == 429:
            time.sleep(5)
        return None

    # ── NVIDIA ──────────────────────────────────────────────────────

    def _call_nvidia(self, prompt: str, system: str,
                      max_tokens: int, temperature: float,
                      model: str, api_key: str,
                      timeout_secs: int,
                      bucket: Optional[TokenBucket] = None,
                      ) -> Optional[LLMResult]:
        """Call NVIDIA with token-bucket rate limiting and exponential backoff on 429."""
        # 1) Acquire token from bucket
        if bucket and not bucket.acquire(timeout=60):
            raise RuntimeError("NVIDIA token-bucket timeout — rate limit exceeded")

        import httpx
        from openai import OpenAI, DefaultHttpxClient

        max_retries = 5
        last_exc: Optional[Exception] = None

        for attempt in range(max_retries):
            t0 = time.time()
            try:
                http_client = httpx.Client(
                    timeout=httpx.Timeout(timeout_secs, connect=30, read=timeout_secs, pool=10),
                )
                client = OpenAI(
                    base_url=self.NVIDIA_BASE,
                    api_key=api_key,
                    http_client=http_client,
                    max_retries=0,
                )
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    top_p=0.95,
                    max_tokens=min(max_tokens, 64000),
                    stream=False,
                )
                latency = (time.time() - t0) * 1000
                content = completion.choices[0].message.content
                if content:
                    usage = completion.usage
                    return LLMResult(
                        text=content,
                        input_tokens=usage.prompt_tokens if usage else _estimate_tokens(prompt + system),
                        output_tokens=usage.completion_tokens if usage else _estimate_tokens(content),
                        model=model,
                        provider="nvidia",
                        latency_ms=latency,
                    )
                return None

            except Exception as e:
                last_exc = e
                status = getattr(e, 'status_code', 0) or 0
                is_429 = status == 429 or '429' in str(e)
                if attempt < max_retries - 1:
                    delay = (2.0 ** attempt) + random.uniform(0, 1.0)
                    tag = "429" if is_429 else "error"
                    logger.info(f"NVIDIA {tag} (attempt {attempt+1}/{max_retries}): "
                                 f"{str(e)[:100]}, backoff {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise  # last attempt — propagate

        raise RuntimeError(f"NVIDIA exhausted after {max_retries} retries: {last_exc}")
