import os
import time
import json
from typing import Optional, Literal
from loguru import logger
import requests

ModelTier = Literal["cheap", "balanced", "powerful"]

MODEL_TIERS = {
    "cheap": {
        "openrouter": "mistralai/mistral-7b-instruct:free",
        "groq": "mixtral-8x7b-32768",
    },
    "balanced": {
        "openrouter": "qwen/qwen-2-7b-instruct:free",
        "groq": "llama-3.1-8b-instant",
    },
    "powerful": {
        "openrouter": "qwen/qwen-2.5-72b-instruct:free",
        "groq": "llama-3.3-70b-versatile",
    },
}

class LLMRouter:
    """Routes LLM calls across providers with tiered fallback.

    Primary: NVIDIA DeepSeek V4 Flash (fast, powerful, tool-capable)
    Fallback: OpenRouter -> Groq -> Ollama
    """

    NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL = "deepseek-ai/deepseek-v4-flash"
    OPENROUTER_BASE = "https://openrouter.ai/api/v1"
    GROQ_BASE = "https://api.groq.com/openai/v1"
    OLLAMA_BASE = "http://localhost:11434"

    def __init__(self):
        self.nvidia_key = os.getenv("NVIDIA_API_KEY", "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")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_key_2 = os.getenv("OPENROUTER_API_KEY_2", "")
        self.groq_key = os.getenv("GROQ_API_KEY", "")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._last_call = {}

    def _rate_limit(self, agent: str = "default"):
        now = time.time()
        last = self._last_call.get(agent, 0)
        elapsed = now - last
        if elapsed < 2.0:
            time.sleep(2.0 - elapsed)
        self._last_call[agent] = time.time()

    def complete(self, prompt: str, agent_type: str = "general",
                 system: str = "You are a helpful AI assistant.",
                 max_tokens: int = 4096, temperature: float = 0.7,
                 tier: ModelTier = "balanced") -> Optional[str]:
        """Route to NVIDIA DeepSeek V4 Flash first, fallback to free providers."""
        self._rate_limit(agent_type)

        # 1. Try NVIDIA DeepSeek V4 Flash (primary)
        result = self._try_nvidia(prompt, system, max_tokens, temperature)
        if result:
            return result

        # 2. Try OpenRouter (fallback)
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
                    max_tokens: int, temperature: float) -> Optional[str]:
        """Call NVIDIA DeepSeek V4 Flash via OpenAI-compatible API."""
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url=self.NVIDIA_BASE,
                api_key=self.nvidia_key,
                timeout=60,
            )
            completion = client.chat.completions.create(
                model=self.NVIDIA_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                top_p=0.95,
                max_tokens=max_tokens if max_tokens <= 16384 else 16384,
                extra_body={"chat_template_kwargs": {"thinking": True, "reasoning_effort": "high"}},
                stream=False,
            )
            content = completion.choices[0].message.content
            if content:
                return content
        except Exception as e:
            logger.debug(f"NVIDIA DeepSeek V4 Flash failed: {e}")
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
            if resp.status_code == 429:
                time.sleep(5)
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
