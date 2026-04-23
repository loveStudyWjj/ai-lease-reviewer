from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from loguru import logger

from app.utils.openai_client import OpenAICompatClient


QA_SYSTEM_PROMPT = "你是租房合同问答助手，回答要简洁、可执行，尽量引用合同原文与审查建议。"


async def stream_answer(
    *,
    client: OpenAICompatClient,
    contract_text: str,
    question: str,
    city: Optional[str] = None,
) -> AsyncIterator[str]:
    logger.debug("qa start: city={}, question_len={}, contract_len={}", city or "", len(question), len(contract_text))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": QA_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                (f"城市：{city}\n\n" if city else "")
                + f"合同全文：\n{contract_text}\n\n问题：{question}\n"
            ),
        },
    ]
    try:
        async for chunk in client.chat_completions_stream(messages=messages, max_tokens=4096):
            yield chunk
        logger.debug("qa finished")
    except Exception:
        logger.exception("qa failed, return degraded message")
        yield "（降级模式）模型服务不可用，请稍后重试。"

