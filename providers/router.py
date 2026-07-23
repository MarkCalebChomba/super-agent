import os
import json
from typing import Optional, Literal
from loguru import logger
import requests

ModelTier = Literal["cheap", "balanced", "powerful"]

MODEL_TIERS = {
    "cheap": {
        "openrouter": "mistralai/mistral-7b-instruct:free",
        "groq": "mixtral-8x7b-32768",
        "hf": "microsoft/phi-3-mini-4k-instruct",
    },
    "balanced": {
        "openrouter": "meta-llama/llama-3.1-8b-instruct:free",
        "groq": "llama-3.1-8b-instant",
        "hf": "meta-llama/meta-llama-3.1-8b-instruct",
    },
    "powerful": {
        "openrouter": "qwen/qwen-2.5-72b-instruct:free",
        "groq": "llama-3.3-70b-versatile",
        "hf": "mistralai/mixtral-8x22b-instruct",
    },
}

class LLMRouter:
    """Routes LLM calls across providers with tiered fallback.

    Priority chain:
    1. OpenRouter (free models: Mistral 7B, Llama 3.1, Qwen 2.5)
    2. Groq (free: Mixtral 8x7B, Llama 3.1 8B, Llama 3.3 70B)
    3. Hugging Face Inference API (free tier)
    4. Ollama (local fallback)

    SuperAgent/agents with tool-calling needs use 'powerful' tier.
    Simple tasks use 'cheap' tier.
    """

    OPENROUTER_BASE = "https://openrouter.ai/api/v1"
    GROQ_BASE = "https://api.groq.com/openai/v1"
    HF_INFERENCE_BASE = "https://api-inference.huggingface.co/models"
    OLLAMA_BASE = "http://localhost:11434"

    def __init__(self):
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_key_2 = os.getenv("OPENROUTER_API_KEY_2", "")
        self.groq_key = os.getenv("GROQ_API_KEY", "")
        self.hf_token = os.getenv("HF_TOKEN", os.getenv("HUGGINGFACE_TOKEN", ""))
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    def complete(self, prompt: str, agent_type: str = "general",
                 system: str = "You are a helpful AI assistant.",
                 max_tokens: int = 512, temperature: float = 0.7,
                 tier: ModelTier = "balanced") -> Optional[str]:
        """Route to best available provider. Returns text or None.
        
        Tier selection by agent_type:
        - supervisor/super_agent: powerful (tool calling)
        - agent thinking: balanced
        - simple/repetitive: cheap
        """
        # Auto-select tier based on agent type
        if agent_type in ("supervisor", "super_agent", "master"):
            tier = "powerful"
        elif agent_type in ("search", "simple", "summarize"):
            tier = "cheap"

        models = MODEL_TIERS[tier]

        # Try providers in order
        result = self._try_openrouter(prompt, system, max_tokens, temperature, models["openrouter"])
        if result:
            return result

        # Second OpenRouter key
        if self.openrouter_key_2:
            result = self._try_openrouter(prompt, system, max_tokens, temperature,
                                         models["openrouter"], key_index=2)
            if result:
                return result

        result = self._try_groq(prompt, system, max_tokens, temperature, models["groq"])
        if result:
            return result

        result = self._try_hf_inference(prompt, system, max_tokens, temperature, models["hf"])
        if result:
            return result

        result = self._try_ollama(prompt, system, max_tokens, temperature)
        return result

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
        except Exception as e:
            logger.debug(f"Groq failed: {e}")
        return None

    def _try_hf_inference(self, prompt: str, system: str,
                          max_tokens: int, temperature: float,
                          model: str) -> Optional[str]:
        if not self.hf_token:
            return None
        try:
            resp = requests.post(
                f"{self.HF_INFERENCE_BASE}/{model}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.hf_token}",
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
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            logger.debug(f"HF Inference ({model}): {resp.status_code}")
        except Exception as e:
            logger.debug(f"HF Inference failed: {e}")
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
