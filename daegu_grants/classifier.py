from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .parsers import clean_text


RELEVANCE_KEYWORDS = [
    "AI",
    "인공지능",
    "미디어아트",
    "미디어파사드",
    "영상",
    "콘텐츠",
    "실감콘텐츠",
    "XR",
    "VR",
    "AR",
    "전시",
    "디자인",
    "공공디자인",
    "공공미디어",
    "디지털콘텐츠",
    "메타버스",
    "가상융합",
    "ABB",
    "게임",
    "웹툰",
    "정책자금",
    "융자",
    "대출",
    "보증",
    "특례보증",
    "이자지원",
    "경영안정자금",
    "신용보증",
    "기술보증",
    "제조",
    "도소매",
    "화훼",
    "꽃",
    "로봇",
]

PROMISING_UNKNOWN_AMOUNT = [
    "콘텐츠 제작지원",
    "제작지원",
    "실증",
    "R&D",
    "기술개발",
    "창업패키지",
    "사업화",
    "여성기업",
    "여성창업",
    "바우처",
    "스케일업",
    "정책자금",
    "융자",
    "대출",
    "특례보증",
    "이자지원",
    "경영안정자금",
]

EXCLUSION_TITLE_KEYWORDS = [
    "입찰",
    "하수관로",
    "BTL",
    "시설개선",
    "제3자 제안",
]


@dataclass
class Classification:
    score: int
    keywords: list[str]
    relevance: str
    eligibility: str
    priority: str
    status_hint: str
    next_action: str


def classify(
    title: str,
    summary: str,
    region: str,
    target: str,
    amount_value: int | None,
    deadline: date | None,
    minimum_amount_krw: int = 20_000_000,
    today: date | None = None,
) -> Classification:
    today = today or date.today()
    haystack = clean_text(f"{title} {summary} {region} {target}").lower()
    title_haystack = clean_text(title).lower()
    matched = [kw for kw in RELEVANCE_KEYWORDS if kw.lower() in haystack]
    promising = [kw for kw in PROMISING_UNKNOWN_AMOUNT if kw.lower() in haystack]
    title_matched = [kw for kw in RELEVANCE_KEYWORDS if kw.lower() in title_haystack]
    title_promising = [kw for kw in PROMISING_UNKNOWN_AMOUNT if kw.lower() in title_haystack]
    is_relevant = bool(matched or promising)
    is_title_relevant = bool(title_matched or title_promising)
    is_excluded_title = any(keyword.lower() in title_haystack for keyword in EXCLUSION_TITLE_KEYWORDS) and not is_title_relevant

    score = 0
    if "대구" in haystack:
        score += 25
    elif "전국" in haystack or not region:
        score += 12
    score += min(len(matched) * 9, 35)
    if amount_value and amount_value >= minimum_amount_krw and is_title_relevant:
        score += 30
    elif amount_value is None and title_promising:
        score += 18
    if deadline:
        days_left = (deadline - today).days
        if 0 <= days_left <= 14:
            score += 15
        elif days_left < 0:
            score -= 50

    eligibility = "대구 신청 가능성 높음" if "대구" in haystack else "전국/확인 필요"
    relevance = "높음" if len(matched) >= 2 else ("보통" if matched or promising else "낮음")

    priority = "normal"
    status_hint = "seen"
    next_action = "원문 확인"
    if is_excluded_title:
        score = min(score, 25)
    if deadline and deadline < today:
        status_hint = "expired"
        next_action = "마감 여부 확인"
    elif amount_value and amount_value >= minimum_amount_krw and is_title_relevant:
        priority = "high_priority"
        status_hint = "new"
        next_action = "지원요건/서류 즉시 확인"
    elif amount_value is None and title_promising:
        priority = "needs_review"
        status_hint = "needs_review"
        next_action = "지원금 규모 확인"
    elif matched and score >= 45:
        status_hint = "new"
        next_action = "상세 공고 검토"

    return Classification(
        score=max(score, 0),
        keywords=matched or promising,
        relevance=relevance,
        eligibility=eligibility,
        priority=priority,
        status_hint=status_hint,
        next_action=next_action,
    )
