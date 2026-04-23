from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from loguru import logger

from app.config import Settings


class OpenAICompatClient:
    """
    Minimal OpenAI-compatible client for vLLM.
    - Non-stream: POST /chat/completions
    - Stream: SSE-ish chunks from /chat/completions with stream=true
    """

    def __init__(self, settings: Settings, timeout_s: float = 120.0) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.openai_api_base.rstrip("/"),
            timeout=httpx.Timeout(timeout_s),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}" if settings.openai_api_key else "",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def build_vision_user_message(*, prompt: str, content_type: str, raw: bytes) -> dict[str, Any]:
        """
        Build an OpenAI-compatible vision message content:
        content = [{type:"text"...}, {type:"image_url", image_url:{url:"data:...;base64,..."}}]
        """
        b64 = base64.b64encode(raw).decode("ascii")
        mime = content_type or "image/png"
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }

    async def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        retries: int = 2,
        enable_thinking: bool = False,
    ) -> str:
        model_name = model or self._settings.openai_model
        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        logger.debug(
            "chat_completions request: model={}, messages={}, max_tokens={}, temperature={}, retries={}",
            model_name,
            len(messages),
            max_tokens,
            temperature,
            retries,
        )
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                r = await self._client.post("/chat/completions", json=payload)
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                logger.debug("chat_completions success: model={}, content_len={}", model_name, len(content or ""))
                return content
            except (httpx.ReadError, httpx.ConnectError, httpx.WriteError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                logger.warning(
                    "chat_completions transient error (attempt {}/{}): model={}, exc={}",
                    attempt + 1,
                    retries + 1,
                    model_name,
                    type(exc).__name__,
                )
                if attempt < retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    raise
            except Exception:
                logger.exception("chat_completions failed: model={}", model_name)
                raise
        # should never reach here, but satisfy type checker
        raise last_exc or RuntimeError("chat_completions unexpected path")

    async def chat_completions_stream(
        self,
        *,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        model_name = model or self._settings.openai_model
        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        logger.debug(
            "chat_completions_stream request: model={}, messages={}, max_tokens={}, temperature={}",
            model_name,
            len(messages),
            max_tokens,
            temperature,
        )
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    # vLLM uses "data: {...}" lines similar to OpenAI.
                    if line.startswith("data:"):
                        chunk = line[len("data:") :].strip()
                    else:
                        chunk = line.strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = obj["choices"][0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content
                    except Exception:
                        # If server returns plain text, just forward it.
                        yield chunk
            logger.debug("chat_completions_stream finished: model={}", model_name)
        except Exception:
            logger.exception("chat_completions_stream failed: model={}", model_name)
            raise

