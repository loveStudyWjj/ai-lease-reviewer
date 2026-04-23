from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.utils.openai_client import OpenAICompatClient


EXTRACT_TEXT_PROMPT = "识别并输出图片中的文本，填写框使用中括号"

async def extract_text_from_file(
    filename: str,
    content_type: str,
    raw: bytes,
    *,
    client: OpenAICompatClient | None = None,
) -> str:
    """
    Use a multimodal model when a binary file is uploaded (image/PDF-as-image).
    """
    suffix = Path(filename).suffix.lower()
    logger.debug(
        "ocr extract start: filename={}, content_type={}, size={}",
        filename,
        content_type or "",
        len(raw),
    )

    if content_type.startswith("text/") or suffix in {".txt", ".md"}:
        try:
            text = raw.decode("utf-8")
            logger.debug("ocr extract text/plain utf-8 success: text_len={}", len(text))
            return text
        except UnicodeDecodeError:
            text = raw.decode("gbk", errors="ignore")
            logger.debug("ocr extract text/plain gbk fallback: text_len={}", len(text))
            return text

    if client is None:
        logger.debug("ocr extract degraded: client missing")
        return (
            "【未配置多模态抽取】后端未传入模型客户端。\n"
            "请检查服务端 /api/extract 实现，或直接把合同文本粘贴到文本框。\n"
        )

    messages = [
        {"role": "system", "content": "你是文本抽取助手，只输出抽取到的原文文本，不要解释。"},
        client.build_vision_user_message(prompt=EXTRACT_TEXT_PROMPT, content_type=content_type, raw=raw),
    ]
    try:
        text = await client.chat_completions(messages=messages, max_tokens=8192, temperature=0.0, enable_thinking=True)
        result = text.strip()
        logger.debug("ocr extract multimodal success: text_len={}", len(result))
        return result
    except Exception:
        logger.exception("ocr extract multimodal failed")
        raise

