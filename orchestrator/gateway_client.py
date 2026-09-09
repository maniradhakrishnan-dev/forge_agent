"""
Gateway Client for ForgeAgent.
Direct LLM API client for two providers:
1. Google Gemini API (gemini-2.5-flash)
2. Groq API (llama-3.3-70b-versatile)

NO silent fallbacks. If the API fails, the system fails LOUDLY.
"""

import os
import json
import asyncio
from typing import List, Dict, Any, Optional
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure .env is loaded whenever gateway_client module is imported
load_dotenv()


class LLMAPIError(Exception):
    """Raised when an LLM API call fails with a non-200 status or network error."""
    def __init__(self, provider: str, status_code: int, detail: str):
        self.provider = provider
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"⚠️  LLM API Error [{provider}] HTTP {status_code}: {detail}"
        )


class GatewayConfig(BaseModel):
    gemini_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY"))
    groq_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GROQ_API_KEY"))

    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.7-flash"))
    groq_model: str = Field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"))

    timeout: float = 60.0


class GatewayClient:
    def __init__(self, config: Optional[GatewayConfig] = None):
        # Reload .env dynamically so user changes in .env are reflected immediately
        load_dotenv(override=True)
        self.config = config or GatewayConfig()

    async def complete(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 8192
    ) -> str:
        """
        Routes chat completions: Gemini -> Groq -> HARD FAIL.
        No silent fallbacks. Errors are raised, not swallowed.
        """
        errors: List[str] = []

        # 1. Try Gemini API
        if self.config.gemini_api_key:
            try:
                res = await self._call_gemini(messages, temperature, max_tokens)
                return res
            except LLMAPIError as e:
                print(str(e))
                errors.append(str(e))
            except Exception as e:
                msg = f"⚠️  Gemini network error: {type(e).__name__}: {e}"
                print(msg)
                errors.append(msg)

        # 2. Try Groq API
        if self.config.groq_api_key:
            try:
                res = await self._call_groq(messages, temperature, max_tokens)
                return res
            except LLMAPIError as e:
                print(str(e))
                errors.append(str(e))
            except Exception as e:
                msg = f"⚠️  Groq network error: {type(e).__name__}: {e}"
                print(msg)
                errors.append(msg)

        # 3. HARD FAIL — no silent fallback
        if not self.config.gemini_api_key and not self.config.groq_api_key:
            raise LLMAPIError(
                provider="NONE",
                status_code=0,
                detail="No LLM API keys configured. Set GEMINI_API_KEY or GROQ_API_KEY in .env"
            )

        raise LLMAPIError(
            provider="ALL",
            status_code=0,
            detail=f"All LLM providers failed. Errors:\n" + "\n".join(errors)
        )

    async def _call_gemini(
        self, messages: List[Dict[str, str]], temperature: float, max_tokens: int
    ) -> str:
        """Calls Google Gemini API directly. Raises LLMAPIError on failure."""
        key = self.config.gemini_api_key
        model = self.config.gemini_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

        system_instruction = None
        contents = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            else:
                g_role = "user" if role == "user" else "model"
                contents.append({"role": g_role, "parts": [{"text": content}]})

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "thinkingConfig": {"thinkingBudget": 0}
            }
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            max_retries = 3
            resp = None
            for attempt in range(1, max_retries + 1):
                resp = await client.post(url, json=payload)
                # If model does not support thinkingConfig (returns HTTP 400), retry without it
                if resp.status_code == 400 and "thinkingConfig" in payload.get("generationConfig", {}):
                    del payload["generationConfig"]["thinkingConfig"]
                    resp = await client.post(url, json=payload)

                if resp.status_code in (429, 500, 503) and attempt < max_retries:
                    backoff = attempt * 3.0
                    if resp.status_code == 429:
                        try:
                            err_data = resp.json().get("error", {})
                            for item in err_data.get("details", []):
                                if "retryDelay" in item:
                                    backoff = float(str(item["retryDelay"]).rstrip("s")) + 1.0
                                    break
                        except Exception:
                            backoff = 10.0 * attempt
                    # If backoff is excessively long (>15s) and Groq fallback is configured, break to fallback immediately
                    if backoff > 15.0 and self.config.groq_api_key:
                        break
                    await asyncio.sleep(backoff)
                    continue
                break

            if resp.status_code != 200:
                # Parse error detail from response body
                try:
                    err_body = resp.json()
                    detail = json.dumps(err_body.get("error", err_body), indent=2)
                except Exception:
                    detail = resp.text[:500]
                raise LLMAPIError(
                    provider=f"Gemini ({model})",
                    status_code=resp.status_code,
                    detail=detail
                )

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise LLMAPIError(
                    provider=f"Gemini ({model})",
                    status_code=200,
                    detail="Empty candidates array in response. Possible content filter block."
                )

            parts = candidates[0].get("content", {}).get("parts", [])
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            if not text_parts or not any(text_parts):
                raise LLMAPIError(
                    provider=f"Gemini ({model})",
                    status_code=200,
                    detail="No text parts in response candidate."
                )

            return "".join(text_parts)

    async def _call_groq(
        self, messages: List[Dict[str, str]], temperature: float, max_tokens: int
    ) -> str:
        """Calls Groq API (High-speed Llama 3.3 70B) directly. Raises LLMAPIError on failure."""
        key = self.config.groq_api_key
        model = self.config.groq_model
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code != 200:
                try:
                    err_body = resp.json()
                    detail = json.dumps(err_body.get("error", err_body), indent=2)
                except Exception:
                    detail = resp.text[:500]
                raise LLMAPIError(
                    provider=f"Groq ({model})",
                    status_code=resp.status_code,
                    detail=detail
                )

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise LLMAPIError(
                    provider=f"Groq ({model})",
                    status_code=200,
                    detail="Empty choices array in response."
                )

            return choices[0].get("message", {}).get("content", "")
