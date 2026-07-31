"""LLM Router — Free-first provider path with 20 RPM cap.

Architecture:
- OpenRouter free models as primary (20 RPM cap)
- Google Gemini as fallback (avoid — heavily censored)
- MiMo v2.5 as paid last resort (only when very necessary)
- Circuit breaker per provider, exponential backoff
- complete() returns LLMResult with text + token_usage + cost
"""
import os
import re
import json
import time
import random
import threading
from typing import Optional, Literal, NamedTuple
from loguru import logger
import requests


ModelTier = Literal["cheap", "balanced", "powerful"]

# ── Free models on OpenRouter (verified July 2026) ───────────────────
# Intelligent models (use for decision-making, planning, evaluation)
FREE_MODELS_POWERFUL = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",   # powerful reasoning
    "google/gemma-4-31b-it:free",                # intelligent, large context
    "nvidia/nemotron-3-super-120b-a12b:free",    # strong general
    "google/gemma-4-26b-a4b-it:free",            # intelligent, efficient
    "openai/gpt-oss-20b:free",                   # open source GPT
]

# Fast models (use for extraction, summaries, cheap work)
FREE_MODELS_CHEAP = [
    "inclusionai/ling-3.0-flash:free",           # fast language
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # fast reasoning
    "poolside/laguna-xs-2.1:free",               # fast code
    "poolside/laguna-s-2.1:free",                # code
    "nvidia/nemotron-nano-12b-v2-vl:free",       # vision-language
    "nvidia/nemotron-nano-9b-v2:free",           # tiny fast
]

# Code-specific models
FREE_MODELS_CODE = [
    "poolside/laguna-s-2.1:free",
    "cohere/north-mini-code:free",
    "poolside/laguna-xs-2.1:free",
]

# MiMo v2.5 — PAID, only when very necessary
MIMO_MODEL = "xiaomi/mimo-v2.5"

# Tier → model mapping
MODEL_TIERS = {
    "cheap": {
        "openrouter": FREE_MODELS_CHEAP,
        "mimo": MIMO_MODEL,
    },
    "balanced": {
        "openrouter": FREE_MODELS_POWERFUL + FREE_MODELS_CHEAP,
        "mimo": MIMO_MODEL,
    },
    "powerful": {
        "openrouter": FREE_MODELS_POWERFUL,
        "mimo": MIMO_MODEL,
    },
}

# Provider attempt order: OpenRouter first → Google fallback → MiMo paid last
PROVIDER_ORDER = {
    "cheap":     ["openrouter", "gemini", "mimo"],
    "balanced":  ["openrouter", "gemini", "mimo"],
    "powerful":  ["openrouter", "gemini", "mimo"],
}

# Approximate costs (MiMo v2.5 only — free models cost $0)
COST_PER_INPUT_TOKEN = 0.00000014   # $0.14/M tokens (MiMo v2.5)
COST_PER_OUTPUT_TOKEN = 0.00000028  # $0.28/M tokens (MiMo v2.5)

# Rate limiting: 20 RPM cap for OpenRouter
_OPENROUTER_RPM_CAP = 20
_OPENROUTER_CALL_TIMES: list[float] = []
_OPENROUTER_RATE_LOCK = threading.Lock()


class LLMResult(NamedTuple):
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0

    @property
    def cost(self) -> float:
        if self.provider == "openrouter":
            return 0.0  # free models
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


# ── Global circuit breakers ──────────────────────────────────────────
_or_breaker = CircuitBreaker("openrouter", fail_threshold=5, cooldown_s=60)
_gemini_breaker = CircuitBreaker("gemini", fail_threshold=3, cooldown_s=120)
_mimo_breaker = CircuitBreaker("mimo", fail_threshold=3, cooldown_s=120)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _openrouter_rate_limit():
    """Enforce 20 RPM cap on OpenRouter."""
    with _OPENROUTER_RATE_LOCK:
        now = time.time()
        # Remove calls older than 60s
        while _OPENROUTER_CALL_TIMES and _OPENROUTER_CALL_TIMES[0] < now - 60:
            _OPENROUTER_CALL_TIMES.pop(0)
        if len(_OPENROUTER_CALL_TIMES) >= _OPENROUTER_RPM_CAP:
            wait = 60 - (now - _OPENROUTER_CALL_TIMES[0]) + 0.5
            if wait > 0:
                logger.info(f"OpenRouter 20 RPM cap hit, waiting {wait:.1f}s")
                time.sleep(wait)
        _OPENROUTER_CALL_TIMES.append(time.time())


class ProviderUnavailable(Exception):
    """All providers exhausted or circuit-broken."""


class LLMRouter:
    """Free-first LLM router. OpenRouter free models primary, Gemini fallback, MiMo paid last."""

    OPENROUTER_BASE = "https://openrouter.ai/api/v1"
    GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_key_2 = os.getenv("OPENROUTER_API_KEY_2", "")
        self.openrouter_key_3 = os.getenv("OPENROUTER_API_KEY_3", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_key_2 = os.getenv("GEMINI_API_KEY_2", "")
        self.mimo_key = os.getenv("MIMO_API_KEY", "") or self.openrouter_key  # use OR key for MiMo

    def complete(self, prompt: str,
                 system: str = "You are a helpful AI assistant.",
                 max_tokens: int = 4096,
                 temperature: float = 0.7,
                 model: Optional[str] = None,
                 tools: Optional[list] = None,
                 tool_choice: Optional[str] = None,
                 tier: ModelTier = "balanced",
                 ) -> Optional[LLMResult]:
        """Provider-ordered completion. Free models first, paid last."""
        models_config = MODEL_TIERS.get(tier, MODEL_TIERS["balanced"])
        order = PROVIDER_ORDER.get(tier, PROVIDER_ORDER["balanced"])
        last_error = ""

        for provider in order:
            # ── OpenRouter (free models, 20 RPM cap) ──
            if provider == "openrouter":
                if _or_breaker.is_open:
                    last_error = "openrouter: circuit open"
                    continue
                or_keys = [k for k in [self.openrouter_key, self.openrouter_key_2, self.openrouter_key_3] if k]
                or_models = models_config.get("openrouter", FREE_MODELS_POWERFUL)
                for or_key in or_keys:
                    for or_model in or_models:
                        _openrouter_rate_limit()
                        try:
                            result = self._call_openrouter(prompt, system, max_tokens,
                                                            temperature, or_model, or_key,
                                                            tools=tools, tool_choice=tool_choice)
                            if result:
                                _or_breaker.record(True)
                                return result
                        except Exception as e:
                            _or_breaker.record(False)
                            last_error = str(e)[:100]
                            status = getattr(e, 'status_code', 0) or 0
                            if status == 429:
                                logger.info(f"OpenRouter 429 on {or_model}, trying next model")
                                break

            # ── Google Gemini (fallback, avoid — censored) ──
            elif provider == "gemini":
                if _gemini_breaker.is_open:
                    last_error = "gemini: circuit open"
                    continue
                if not (self.gemini_key or self.gemini_key_2):
                    last_error = "gemini: no keys"
                    continue
                gemini_keys = [k for k in [self.gemini_key, self.gemini_key_2] if k]
                gemini_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
                for gkey in gemini_keys:
                    for gmodel in gemini_models:
                        try:
                            result = self._call_gemini(prompt, system, max_tokens,
                                                        temperature, gmodel, gkey)
                            if result:
                                _gemini_breaker.record(True)
                                return result
                        except Exception as e:
                            _gemini_breaker.record(False)
                            last_error = str(e)[:100]

            # ── MiMo v2.5 (PAID — last resort only) ──
            elif provider == "mimo":
                if _mimo_breaker.is_open:
                    last_error = "mimo: circuit open"
                    continue
                if not self.mimo_key:
                    last_error = "mimo: no key"
                    continue
                logger.info(f"Using PAID model MiMo v2.5 (last resort)")
                try:
                    result = self._call_openrouter(prompt, system, max_tokens,
                                                    temperature, MIMO_MODEL, self.mimo_key,
                                                    tools=tools, tool_choice=tool_choice)
                    if result:
                        _mimo_breaker.record(True)
                        return result
                except Exception as e:
                    _mimo_breaker.record(False)
                    last_error = str(e)[:100]

        logger.error(f"All providers exhausted. Last error: {last_error}")
        return None

    def complete_structured(self, prompt: str,
                            schema: dict,
                            system: str = "You are a helpful AI assistant.",
                            max_tokens: int = 4096,
                            temperature: float = 0.7,
                            tier: ModelTier = "powerful",
                            ) -> Optional[dict]:
        """Call LLM with tool/function schema to force structured JSON output."""
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
            try:
                data = json.loads(result.text)
                return data
            except json.JSONDecodeError:
                pass
            try:
                data = json.loads(result.text)
                if "choices" in data:
                    msg = data["choices"][0]["message"]
                    if "tool_calls" in msg:
                        args = msg["tool_calls"][0]["function"]["arguments"]
                        return json.loads(args)
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass
            json_match = re.search(r'\{.*\}', result.text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        # Fallback: plain-text prompt asking for JSON
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

    # ── OpenRouter ──────────────────────────────────────────────────

    def _call_openrouter(self, prompt: str, system: str,
                          max_tokens: int, temperature: float,
                          model: str, api_key: str,
                          tools: Optional[list] = None,
                          tool_choice: Optional[str] = None,
                          ) -> Optional[LLMResult]:
        t0 = time.time()
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        resp = requests.post(
            f"{self.OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/MarkCalebChomba/super-agent",
            },
            json=body,
            timeout=60,
        )
        latency = (time.time() - t0) * 1000

        if resp.status_code == 200:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            logger.info(f"OpenRouter SUCCESS ({model}): {len(text)} chars, {latency:.0f}ms")
            return LLMResult(
                text=text,
                input_tokens=usage.get("prompt_tokens", _estimate_tokens(prompt + system)),
                output_tokens=usage.get("completion_tokens", _estimate_tokens(text)),
                model=model,
                provider="openrouter",
                latency_ms=latency,
            )
        logger.debug(f"OpenRouter ({model}): {resp.status_code}")
        err = Exception(f"OpenRouter {resp.status_code}: {resp.text[:200]}")
        err.status_code = resp.status_code
        raise err

    # ── Gemini (fallback — avoid, heavily censored) ────────────────

    def _call_gemini(self, prompt: str, system: str,
                      max_tokens: int, temperature: float,
                      model: str, api_key: str) -> Optional[LLMResult]:
        t0 = time.time()
        url = f"{self.GEMINI_BASE}/models/{model}:generateContent?key={api_key}"
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "maxOutputTokens": min(max_tokens, 8192),
                "temperature": temperature,
                "topP": 0.95,
            },
        }
        try:
            resp = requests.post(url, json=body, timeout=60)
            latency = (time.time() - t0) * 1000
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    content_parts = candidates[0].get("content", {}).get("parts", [])
                    text = " ".join(p.get("text", "") for p in content_parts)
                    usage = data.get("usageMetadata", {})
                    in_tokens = usage.get("promptTokenCount", _estimate_tokens(prompt + system))
                    out_tokens = usage.get("candidatesTokenCount", _estimate_tokens(text))
                    logger.info(f"Gemini SUCCESS ({model}): {len(text)} chars, {latency:.0f}ms")
                    return LLMResult(
                        text=text,
                        input_tokens=in_tokens,
                        output_tokens=out_tokens,
                        model=model,
                        provider="gemini",
                        latency_ms=latency,
                    )
            logger.info(f"Gemini ({model}) status={resp.status_code}: {resp.text[:150]}")
            if resp.status_code == 429:
                time.sleep(2)
            return None
        except Exception as e:
            logger.info(f"Gemini ({model}) failed: {str(e)[:100]}")
            return None
