from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger

from app.config import get_settings
from app.logging_config import setup_logging
from app.schemas import ExtractResponse, ReviewRequest, ReviewResponse
from app.services.ocr import extract_text_from_file
from app.services.qa import stream_answer
from app.services.review import ReviewDeps, review_contract_text, stream_review_contract_text
from app.utils.openai_client import OpenAICompatClient


app = FastAPI(title="Rent Contract Review API", version="0.1.0")
setup_logging()

# In-memory doc store (MVP). Key: doc_id -> (text, ts)
_DOC_STORE: dict[str, tuple[str, float]] = {}
_DOC_TTL_S = 60 * 60  # 1 hour


def _doc_store_put(doc_id: str, text: str) -> None:
    _DOC_STORE[doc_id] = (text, time.time())


def _doc_store_get(doc_id: str) -> Optional[str]:
    item = _DOC_STORE.get(doc_id)
    if not item:
        return None
    text, ts = item
    if time.time() - ts > _DOC_TTL_S:
        _DOC_STORE.pop(doc_id, None)
        return None
    return text


def _doc_store_gc() -> None:
    now = time.time()
    expired = [k for k, (_, ts) in _DOC_STORE.items() if now - ts > _DOC_TTL_S]
    for k in expired:
        _DOC_STORE.pop(k, None)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    logger.debug("health check")
    return {"ok": True}


@app.post("/api/extract", response_model=ExtractResponse)
async def extract(file: UploadFile = File(...)) -> ExtractResponse:
    logger.debug(
        "extract request: filename={}, content_type={}",
        file.filename or "upload",
        file.content_type or "",
    )
    raw = await file.read()
    settings = get_settings()
    client = OpenAICompatClient(settings)
    try:
        text = await extract_text_from_file(
            file.filename or "upload", file.content_type or "", raw, client=client
        )
        _doc_store_gc()
        doc_id = str(uuid.uuid4())
        _doc_store_put(doc_id, text)
        logger.debug("extract success: doc_id={}, text_len={}", doc_id, len(text))
        return ExtractResponse(doc_id=doc_id, text=text)
    except Exception:
        logger.exception("extract failed")
        raise
    finally:
        await client.aclose()


@app.post("/api/review_file", response_model=ReviewResponse)
async def review_file(file: UploadFile = File(...), city: Optional[str] = Form(default=None)) -> ReviewResponse:
    """
    One-shot: upload file -> multimodal extract -> review.
    """
    logger.debug(
        "review_file request: filename={}, content_type={}, city={}",
        file.filename or "upload",
        file.content_type or "",
        city or "",
    )
    raw = await file.read()
    settings = get_settings()
    client = OpenAICompatClient(settings)
    try:
        text = await extract_text_from_file(
            file.filename or "upload", file.content_type or "", raw, client=client
        )
        _doc_store_gc()
        doc_id = str(uuid.uuid4())
        _doc_store_put(doc_id, text)
        logger.debug("review_file extracted: doc_id={}, text_len={}", doc_id, len(text))
        # Keep API shape consistent: review response does not include doc_id yet (front already has it from extract)
        return await review_contract_text(deps=ReviewDeps(client=client), text=text, city=city)
    except Exception:
        logger.exception("review_file failed")
        raise
    finally:
        await client.aclose()


@app.post("/api/review")
async def review(req: ReviewRequest):
    logger.debug("review request: doc_id={}, city={}, text_len={}", req.doc_id, req.city or "", len(req.text or ""))
    settings = get_settings()
    client = OpenAICompatClient(settings)

    async def gen():
        try:
            reviews = []
            async for clause in stream_review_contract_text(
                deps=ReviewDeps(client=client), text=req.text, city=req.city
            ):
                reviews.append(clause)
                payload = {
                    "type": "clause",
                    "clause": clause.model_dump(),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            overall = sum(r.risk_level == "high" and 90 or r.risk_level == "medium" and 50 or 15 for r in reviews) / max(1, len(reviews))
            yield f"data: {json.dumps({'type': 'done', 'overall_risk_score': round(overall, 2)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            logger.debug("review stream finished: clauses={}", len(reviews))
        except Exception:
            logger.exception("review stream failed")
            raise
        finally:
            await client.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/qa/stream")
async def qa_stream(doc_id: str, question: str, city: Optional[str] = None):
    logger.debug("qa stream request: doc_id={}, city={}, q_len={}", doc_id, city or "", len(question or ""))
    settings = get_settings()
    client = OpenAICompatClient(settings)

    async def gen():
        try:
            contract_text = _doc_store_get(doc_id) or ""
            if not contract_text.strip():
                logger.debug("qa stream doc missing: doc_id={}", doc_id)
                yield f"data: {json.dumps({'delta': '未找到该 doc_id 的合同文本，请先上传/抽取。'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            async for chunk in stream_answer(client=client, contract_text=contract_text, question=question, city=city):
                # SSE format
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            logger.debug("qa stream finished: doc_id={}", doc_id)
        except Exception:
            logger.exception("qa stream failed: doc_id={}", doc_id)
            raise
        finally:
            await client.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream")

