"""LLM Router — routes calls across providers with role-based tiered fallback.

The "Pro" model (deepseek-v4-pro) is intentionally skipped on all providers:
- HF Inference: 1T param model, cold-start timeouts (9+ min, no output)
- NVIDIA API: model exists in catalog but times out on inference

All roles use the Flash model which is fast, reliable, and 236B params.

Routing:
  1. NVIDIA v4-flash (key1) — primary for all roles
  2. NVIDIA v4-flash (key2) — spillover
  3. HF Inference v4-flash — uses HF credits, no NVIDIA rate limit hit
  4. OpenRouter → Groq → Ollama
"""
import os
import time
import json
from typing import Optional, Literal
from loguru import logger
import requests
from openai import OpenAI, DefaultHttpxClient
import httpx

ModelTier = Literal["cheap", "balanced", "powerful"]

MODEL_TIERS = {
    "cheap": {
        "openrouter": "nvidia/nemotron-nano-9b-v2:free",
        "groq": "mixtral-8x7b-32768",
    },
    "balanced": {
        "openrouter": "google/gemma-4-26b-a4b-it:free",
        "groq": "llama-3.1-8b-instant",
    },
    "powerful": {
        "openrouter": "openai/gpt-oss-20b:free",
        "groq": "llama-3.3-70b-versatile",
    },
}


_HERMES_HF_CLIENT = None

def _get_hermes_hf() -> Optional[object]:
    """Lazy-init the HF Hermes client."""
    global _HERMES_HF_CLIENT
    if _HERMES_HF_CLIENT is None:
        try:
            from hermes_integration.hermes_hf_client import HermesHFClient
            _HERMES_HF_CLIENT = HermesHFClient()
        except Exception:
            _HERMES_HF_CLIENT = False
    return _HERMES_HF_CLIENT if _HERMES_HF_CLIENT else None


def _try_hermes(prompt: str, system: str,
                max_tokens: int, temperature: float) -> Optional[str]:
    """Route through Hermes Agent hosted on Hugging Face Spaces.
    
    Hermes handles LLM routing, web search, and research tools remotely.
    Falls back to local providers if unreachable.
    """
    client = _get_hermes_hf()
    if not client or not client.available:
        return None
    return client.complete(
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
    )


class LLMRouter:
    """Routes LLM calls across providers with tiered fallback.

    Supervisor/Critic → HF Inference (deepseek-v4-pro) → NVIDIA flash → OpenRouter
    Worker             → NVIDIA flash → OpenRouter
    """

    NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL_FLASH = "deepseek-ai/deepseek-v4-flash"
    NVIDIA_MODEL_PRO = "deepseek-ai/deepseek-v4-pro"
    HF_INFERENCE_BASE = "https://api-inference.huggingface.co/v1"
    HF_PRO_MODEL = "deepseek-ai/DeepSeek-V4-Pro"
    OPENROUTER_BASE = "https://openrouter.ai/api/v1"
    GROQ_BASE = "https://api.groq.com/openai/v1"
    OLLAMA_BASE = "http://localhost:11434"

    def __init__(self):
        self.nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        self.nvidia_key_2 = os.getenv("NVIDIA_API_KEY_2", "")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_key_2 = os.getenv("OPENROUTER_API_KEY_2", "")
        self.groq_key = os.getenv("GROQ_API_KEY", "")
        self.hf_token = os.getenv("HF_TOKEN", "")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._nvidia_window = []

    def _rate_limit_nvidia(self):
        """Enforce 40 requests per minute global limit for NVIDIA."""
        now = time.time()
        self._nvidia_window = [t for t in self._nvidia_window if now - t < 60]
        if len(self._nvidia_window) >= 40:
            sleep_time = 60 - (now - self._nvidia_window[0])
            if sleep_time > 0:
                logger.info(f"NVIDIA rate limit: waiting {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self._nvidia_window = self._nvidia_window[1:]
        self._nvidia_window.append(now)

    def complete(self, prompt: str, agent_type: str = "general",
                  system: str = "You are a helpful AI assistant.",
                  max_tokens: int = 4096, temperature: float = 0.7,
                  tier: ModelTier = "balanced",
                  role: str = "worker") -> Optional[str]:
        """Unified routing — all roles use the same reliable pipeline.

        The "Pro" model is intentionally skipped (broken on all providers).
        Flash (236B) is fast, reliable, and capable enough for every role.
        """

        # 0. Hermes Agent (deprecated, kept for backwards compat)
        result = _try_hermes(prompt, system, max_tokens, temperature)
        if result:
            return result

        # 1. NVIDIA flash (key1) — 45s timeout (API can be slow from this region)
        self._rate_limit_nvidia()
        result = self._try_nvidia(prompt, system, max_tokens, temperature,
                                   model=self.NVIDIA_MODEL_FLASH, api_key=self.nvidia_key,
                                   timeout_secs=45)
        if result:
            return result

        # 2. NVIDIA flash (key2) — spillover, 30s timeout (key2 is faster)
        self._rate_limit_nvidia()
        result = self._try_nvidia(prompt, system, max_tokens, temperature,
                                   model=self.NVIDIA_MODEL_FLASH,
                                   api_key=self.nvidia_key_2 or self.nvidia_key,
                                   timeout_secs=30)
        if result:
            return result

        # 3. HF Inference flash — fast fail (connection blocked in this region)
        result = self._try_hf_inference(prompt, system, max_tokens, temperature,
                                         model="deepseek-ai/DeepSeek-V4-Flash")
        if result:
            return result

        # ── OpenRouter tier fallback (for both roles) ──
        if tier == "powerful":
            models = MODEL_TIERS["powerful"]
        elif tier == "cheap":
            models = MODEL_TIERS["cheap"]
        else:
            models = MODEL_TIERS["balanced"]

        result = self._try_openrouter(prompt, system, max_tokens, temperature, models["openrouter"])
        if result:
            return result
        if self.openrouter_key_2:
            result = self._try_openrouter(prompt, system, max_tokens, temperature,
                                           models["openrouter"], key_index=2)
            if result:
                return result

        result = self._try_groq(prompt, system, max_tokens, temperature, models["groq"])
        if result:
            return result

        result = self._try_ollama(prompt, system, max_tokens, temperature)
        return result

    def _try_nvidia(self, prompt: str, system: str,
                    max_tokens: int, temperature: float,
                    model: str = None, api_key: str = None,
                    timeout_secs: int = 90) -> Optional[str]:
        """Call NVIDIA DeepSeek via OpenAI-compatible API."""
        key = api_key or self.nvidia_key
        mdl = model or self.NVIDIA_MODEL_FLASH
        if not key:
            return None
        try:
            http_client = httpx.Client(timeout=httpx.Timeout(timeout_secs, connect=15))
            client = OpenAI(
                base_url=self.NVIDIA_BASE,
                api_key=key,
                http_client=http_client,
                max_retries=0,
            )
            completion = client.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                top_p=0.95,
                max_tokens=max_tokens if max_tokens <= 16384 else 16384,
                stream=False,
            )
            content = completion.choices[0].message.content
            if content:
                return content
        except Exception as e:
            err_str = str(e)
            logger.debug(f"NVIDIA {mdl} failed: {err_str[:120]}")
            if "503" in err_str or "ResourceExhausted" in err_str or "429" in err_str:
                logger.info(f"NVIDIA {mdl} rate limited, backing off 15s")
                time.sleep(15)
        return None

    def _try_hf_inference(self, prompt: str, system: str,
                          max_tokens: int, temperature: float,
                          model: str = None) -> Optional[str]:
        """Call DeepSeek via Hugging Face Inference API (OpenAI-compatible).

        Timeout set to 120s max total. If HF Inference is slow (cold start),
        it will fail fast and the caller falls through to the next provider.
        """
        if not self.hf_token:
            return None
        mdl = model or "deepseek-ai/DeepSeek-V4-Flash"
        try:
            http_client = httpx.Client(timeout=httpx.Timeout(15, connect=5))
            client = OpenAI(
                base_url=self.HF_INFERENCE_BASE,
                api_key=self.hf_token,
                http_client=http_client,
                max_retries=0,
            )
            completion = client.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                top_p=0.95,
                max_tokens=min(max_tokens, 16384),
                stream=False,
            )
            content = completion.choices[0].message.content
            if content:
                return content
        except Exception as e:
            logger.debug(f"HF Inference ({mdl}) failed: {str(e)[:120]}")
        return None

    def _try_openrouter(self, prompt: str, system: str,
                        max_tokens: int, temperature: float,
                        model: str, key_index: int = 1) -> Optional[str]:
        key = self.openrouter_key_2 if key_index == 2 else self.openrouter_key
        if not key:
            return None
        try:
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
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            logger.debug(f"OpenRouter ({model}): {resp.status_code}")
        except Exception as e:
            logger.debug(f"OpenRouter failed: {e}")
        return None

    def _try_groq(self, prompt: str, system: str,
                  max_tokens: int, temperature: float,
                  model: str) -> Optional[str]:
        if not self.groq_key:
            return None
        try:
            time.sleep(1)
            resp = requests.post(
                f"{self.GROQ_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json",
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
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            logger.debug(f"Groq ({model}): {resp.status_code}")
            if resp.status_code == 429:
                time.sleep(10)
        except Exception as e:
            logger.debug(f"Groq failed: {e}")
        return None

    def _try_ollama(self, prompt: str, system: str,
                    max_tokens: int, temperature: float) -> Optional[str]:
        try:
            resp = requests.post(
                f"{self.ollama_host}/api/chat",
                json={
                    "model": "llama3.2",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()["message"]["content"]
        except Exception as e:
            logger.debug(f"Ollama failed: {e}")
        return None
