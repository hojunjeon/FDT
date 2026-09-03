"""거래 분류 (FDT-INP-01, FR-TXN-02).

우선순위: 매핑 테이블 -> 고정비 테이블 -> 요약 키워드 -> 폴백 분류기(선택, LLM) -> 미분류(기타, 낮은 확신도).
숫자는 건드리지 않고 라벨만 붙인다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from fdt.taxonomy.categories import (
    FIXED_KIND_OF_KEYWORD,
    FIXED_MERCHANTS,
    MERCHANT_TO_SUBCATEGORY,
    SUMMARY_KEYWORDS,
    Envelope,
    Flow,
    envelope_of,
)


@dataclass(frozen=True)
class Label:
    flow: Flow
    subcategory: str | None = None
    envelope: Envelope | None = None
    fixed_kind: str | None = None
    confidence: float = 1.0
    merchant: str = ""


class FallbackClassifier(Protocol):
    """미등록 가맹점 폴백. (merchant, hint) -> (subcategory, confidence). 없으면 None."""

    def __call__(self, merchant: str, hint: str) -> tuple[str, float] | None: ...


_SUFFIXES = re.compile(r"\s*(체크카드|카드|결제|승인)$")


def normalize_merchant(text: str) -> str:
    """'GS25 체크카드' -> 'GS25'. 계좌 요약 문자열에서 가맹점명 추출."""
    t = _SUFFIXES.sub("", text.strip())
    return t.split(" ")[0] if t else t


def classify_merchant(merchant: str, hint: str = "", fallback: FallbackClassifier | None = None) -> Label:
    m = merchant.strip()
    if m in FIXED_MERCHANTS:
        return Label(flow=Flow.FIXED, fixed_kind=FIXED_MERCHANTS[m], merchant=m)
    sub = MERCHANT_TO_SUBCATEGORY.get(m)
    if sub is not None:
        return Label(flow=Flow.SPEND, subcategory=sub, envelope=envelope_of(sub), merchant=m)
    if fallback is not None:
        res = fallback(m, hint)
        if res is not None:
            sub, conf = res
            env = envelope_of(sub)
            if env is not None:
                return Label(flow=Flow.SPEND, subcategory=sub, envelope=env, confidence=conf, merchant=m)
    return Label(flow=Flow.SPEND, subcategory="경조사·기타", envelope=Envelope.ETC, confidence=0.3, merchant=m)


def classify_account_summary(summary: str, is_deposit: bool, fallback: FallbackClassifier | None = None) -> Label:
    """계좌 거래 요약 -> 라벨. 입금은 수입/환불/내계좌이체만 가능."""
    s = summary.strip()
    for kw, flow in SUMMARY_KEYWORDS.items():
        if kw in s:
            if flow == Flow.FIXED:
                return Label(flow=flow, fixed_kind=FIXED_KIND_OF_KEYWORD.get(kw, kw), merchant=s)
            if flow == Flow.INCOME and not is_deposit:
                continue
            return Label(flow=flow, merchant=s)
    if is_deposit:
        return Label(flow=Flow.INCOME, confidence=0.5, merchant=s)
    merchant = normalize_merchant(s)
    return classify_merchant(merchant, hint=s, fallback=fallback)
