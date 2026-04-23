from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from loguru import logger

from app.schemas import ClauseReview, ReviewResponse
from app.utils.openai_client import OpenAICompatClient


REVIEW_SYSTEM_PROMPT = "你是一名专业的中国租房合同法律审查助手。"

REVIEW_USER_PROMPT_TEMPLATE = """请审查以下合同条款，输出严格的JSON格式：
{{
  "clause_type": "条款类型（押金/违约/维修/解约/其他）",
  "risk_level": "high/medium/low",
  "risk_reason": "风险原因（50字内，面向普通用户）",
  "legal_basis": "相关法律依据（如《民法典》第710条）",
  "suggestion": "具体修改建议（用第一人称，告诉用户怎么做）",
  "negotiation_tip": "和房东谈判时可以说的话（一句话）"
}}

合同条款：
{clause_text}

审查重点：
1. 是否存在单方面不平等约定
2. 押金条款是否符合当地规定
3. 维修责任是否明确
4. 解约条件是否对等
5. 是否缺少必要保护条款
"""


def _simple_clause_split(text: str) -> list[str]:
    t = re.sub(r"\r\n?", "\n", text).strip()
    if not t:
        return []
    # Split by blank lines; fallback to sentence-ish chunks.
    parts = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    if len(parts) >= 2:
        return parts[:20]
    # fallback: split by "。" or ";" or line breaks
    parts2 = [p.strip() for p in re.split(r"[。；;\n]+", t) if p.strip()]
    return parts2[:20]


def _stable_clause_id(clause_text: str) -> str:
    return hashlib.sha1(clause_text.encode("utf-8")).hexdigest()[:12]


def _safe_json_loads(s: Any) -> Optional[dict[str, Any]]:
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    s = s.strip()
    if not s:
        return None
    # Try to locate JSON object in text.
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        s = m.group(0)
    try:
        return json.loads(s)
    except Exception:
        return None


def _risk_to_score(level: str) -> float:
    return {"high": 90.0, "medium": 50.0, "low": 15.0}.get(level, 30.0)


@dataclass
class ReviewDeps:
    client: OpenAICompatClient


def _default_clause_review(clause_text: str, clause_id: str) -> ClauseReview:
    return ClauseReview(
        clause_id=clause_id,
        clause_type="其他",
        risk_level="medium",
        clause_text=clause_text,
        risk_reason="（降级模式）模型不可用，返回默认风险判断。",
        legal_basis="（降级模式）",
        suggestion="建议你把该条款发给房东确认，并补充对等的权利义务条款。",
        negotiation_tip="这条我们按示范合同改一下，双方责任对等更合理。",
    )


async def _review_single_clause(
    client: OpenAICompatClient,
    clause_text: str,
    clause_id: str,
    city: Optional[str],
    use_llm: bool,
) -> tuple[ClauseReview, bool]:
    """Review a single clause; return (review, ok)."""
    if not use_llm:
        return _default_clause_review(clause_text=clause_text, clause_id=clause_id), True
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                (f"城市：{city}\n\n" if city else "")
                + REVIEW_USER_PROMPT_TEMPLATE.format(clause_text=clause_text)
            ),
        },
    ]
    try:
        content = await client.chat_completions(messages=messages, max_tokens=4096, retries=2)
        obj = _safe_json_loads(content)
        if not obj:
            raise ValueError("Model did not return valid JSON.")
        review = ClauseReview(
            clause_id=clause_id,
            clause_type=str(obj.get("clause_type", "其他")),
            risk_level=str(obj.get("risk_level", "medium")),
            clause_text=clause_text,
            risk_reason=str(obj.get("risk_reason", ""))[:300],
            legal_basis=str(obj.get("legal_basis", ""))[:300],
            suggestion=str(obj.get("suggestion", ""))[:500],
            negotiation_tip=str(obj.get("negotiation_tip", ""))[:200],
        )
        return review, True
    except Exception:
        logger.exception("review llm failed for clause_id={}", clause_id)
        return _default_clause_review(clause_text=clause_text, clause_id=clause_id), False


async def stream_review_contract_text(
    *,
    deps: ReviewDeps,
    text: str,
    city: Optional[str] = None,
) -> AsyncIterator[ClauseReview]:
    """Yield each ClauseReview as soon as it is ready."""
    try:
        clauses = _simple_clause_split(text)
        logger.debug("stream review start: clauses={}, city={}", len(clauses), city or "")

        use_llm = True
        consecutive_failures = 0
        max_consecutive_failures = 3
        reviews: list[ClauseReview] = []

        for clause_text in clauses:
            clause_id = _stable_clause_id(clause_text)
            review, ok = await _review_single_clause(
                client=deps.client,
                clause_text=clause_text,
                clause_id=clause_id,
                city=city,
                use_llm=use_llm,
            )
            if not ok:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    logger.warning(
                        "review consecutive failures reached {}, switch to degrade mode",
                        max_consecutive_failures,
                    )
                    use_llm = False
            else:
                consecutive_failures = 0
            reviews.append(review)
            yield review

        if not reviews:
            review = ClauseReview(
                clause_id="empty",
                clause_type="其他",
                risk_level="low",
                clause_text="",
                risk_reason="未识别到可审查的条款文本。",
                legal_basis="",
                suggestion="请上传/粘贴合同正文后再试。",
                negotiation_tip="",
            )
            reviews.append(review)
            yield review

        overall = sum(_risk_to_score(r.risk_level) for r in reviews) / max(1, len(reviews))
        logger.debug("stream review done: clauses={}, overall={}", len(reviews), round(overall, 2))
    except Exception:
        logger.exception("stream review fatal fallback")
        fallback_text = (text or "").strip()
        clause_text = fallback_text if fallback_text else "合同审查服务暂不可用。"
        clause_id = _stable_clause_id(clause_text) if fallback_text else "fallback"
        review = _default_clause_review(clause_text=clause_text, clause_id=clause_id)
        yield review


async def review_contract_text(
    *,
    deps: ReviewDeps,
    text: str,
    city: Optional[str] = None,
) -> ReviewResponse:
    """Non-streaming wrapper: collect all then return ReviewResponse."""
    reviews: list[ClauseReview] = []
    async for review in stream_review_contract_text(deps=deps, text=text, city=city):
        reviews.append(review)
    overall = sum(_risk_to_score(r.risk_level) for r in reviews) / max(1, len(reviews))
    return ReviewResponse(overall_risk_score=round(overall, 2), clauses=reviews)

