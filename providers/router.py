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
import threading
from typing import Optional, Literal
from loguru import logger
import requests
from openai import OpenAI, DefaultHttpxClient
import httpx

ModelTier = Literal["cheap", "balanced", "powerful"]

# All models must be >200B parameters. No small models.
MODEL_TIERS = {
    "cheap": {
        "nvidia_pro": "deepseek-ai/deepseek-v4-pro",        # 1T params (NVIDIA)
        "openrouter": "deepseek/deepseek-r1:free",          # 671B (OpenRouter)
    },
    "balanced": {
        "nvidia_pro": "deepseek-ai/deepseek-v4-pro",        # 1T
        "openrouter": "deepseek/deepseek-r1:free",          # 671B
    },
    "powerful": {
        "nvidia_pro": "deepseek-ai/deepseek-v4-pro",        # 1T
        "openrouter": "deepseek/deepseek-r1:free",          # 671B
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


# Global shared rate limiter — all LLMRouter instances share this
_nvidia_window_global = []
_nvidia_lock = threading.Lock()


class LLMRouter:
    """Routes LLM calls across providers with tiered fallback.

    All roles use the same reliable pipeline with shared rate limiting.
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

    def _rate_limit_nvidia(self):
        """Enforce 70 requests per minute SHARED across all instances.
        2 API keys x 40 req/min each = 80 available. Using 70 to leave headroom.
        """
        global _nvidia_window_global
        now = time.time()
        with _nvidia_lock:
            _nvidia_window_global = [t for t in _nvidia_window_global if now - t < 60]
            if len(_nvidia_window_global) >= 70:
                sleep_time = 60 - (now - _nvidia_window_global[0])
                if sleep_time > 0:
                    logger.info(f"NVIDIA shared rate limit: waiting {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                _nvidia_window_global = _nvidia_window_global[1:]
            _nvidia_window_global.append(now)

    def complete(self, prompt: str, agent_type: str = "general",
                  system: str = "You are a helpful AI assistant.",
                  max_tokens: int = 4096, temperature: float = 0.7,
                  tier: ModelTier = "balanced",
                  role: str = "worker") -> Optional[str]:
        """Unified routing — only models >200B parameters."""

        # 0. Hermes Agent (deprecated, kept for backwards compat)
        result = _try_hermes(prompt, system, max_tokens, temperature)
        if result:
            return result

        # 1. HF Inference — try multiple >200B models
        for hf_model in ["deepseek-ai/DeepSeek-V4-Flash", "deepseek-ai/DeepSeek-R1",
                         "deepseek-ai/DeepSeek-V3"]:
            result = self._try_hf_inference(prompt, system, max_tokens, temperature,
                                              model=hf_model)
            if result:
                return result

        # 2. OpenRouter — try multiple >200B free models
        models = MODEL_TIERS.get(tier, MODEL_TIERS["balanced"])
        openrouter_models = [
            models["openrouter"],           # deepseek/deepseek-r1:free (671B)
            "deepseek/deepseek-chat:free",  # DeepSeek V3 (671B)
        ]
        for or_model in openrouter_models:
            result = self._try_openrouter(prompt, system, max_tokens, temperature, or_model)
            if result:
                return result
            result = self._try_openrouter(prompt, system, max_tokens, temperature,
                                            or_model, key_index=2)
            if result:
                return result

        # 3. NVIDIA (last resort — constantly rate limited from SFO)
        # Try Flash (236B) then Pro (1T) with each key, fail fast on rate limits
        for key_attr, label in [("nvidia_key", "key1"), ("nvidia_key_2", "key2")]:
            key = getattr(self, key_attr, None)
            if not key:
                continue
            for model_attr, mdl_label, timeout in [
                (self.NVIDIA_MODEL_FLASH, "Flash", 30),
                (self.NVIDIA_MODEL_PRO, "Pro", 60),
            ]:
                self._rate_limit_nvidia()
                result = self._try_nvidia(prompt, system, max_tokens, temperature,
                                            model=model_attr, api_key=key,
                                            timeout_secs=timeout)
                if result:
                    return result

        return None

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
                logger.info(f"NVIDIA {mdl} exhausted/rate limited, skip to next provider")
        return None

    def _try_hf_inference(self, prompt: str, system: str,
                          max_tokens: int, temperature: float,
                          model: str = None) -> Optional[str]:
        """Call DeepSeek via Hugging Face Inference API (direct REST, not OpenAI wrapper).

        Uses the serverless Inference API at huggingface.co/models/{model}/v1/chat.
        """
        if not self.hf_token:
            return None
        mdl = model or "deepseek-ai/DeepSeek-V4-Flash"
        try:
            logger.info(f"HF Inference: calling {mdl} via direct POST")
            # Direct POST to HF Inference API (more reliable than OpenAI wrapper)
            resp = requests.post(
                f"https://api-inference.huggingface.co/models/{mdl}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.hf_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": mdl,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": min(max_tokens, 16384),
                    "temperature": temperature,
                    "top_p": 0.95,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if content:
                    logger.info(f"HF Inference SUCCESS: got {len(content)} chars")
                    return content
            logger.info(f"HF Inference ({mdl}) status={resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.info(f"HF Inference ({mdl}) failed: {str(e)[:200]}")
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
