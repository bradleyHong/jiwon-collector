"""
Opportunity → Supabase `programs` 테이블 upsert.

환경변수:
    SUPABASE_URL                : https://<project>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY   : service_role 키 (서버 전용)

둘 중 하나라도 없으면 호출 시 no-op로 빠진다 (기존 CSV 흐름은 그대로 유지).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import requests

from .storage import Opportunity


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "보조금": ["보조", "지원금", "사업화", "패키지", "바우처"],
    "융자": ["융자", "대출", "정책자금", "운영자금"],
    "보증": ["보증", "특례보증"],
    "R&D": ["R&D", "연구개발", "기술개발", "실증"],
    "창업": ["창업", "예비창업"],
    "판로": ["판로", "마케팅", "홍보", "라이브커머스", "스마트스토어"],
    "제작지원": ["제작지원", "콘텐츠 제작", "영상", "전시"],
    "컨설팅": ["컨설팅", "멘토링", "교육"],
}


def _infer_categories(opp: Opportunity) -> list[str]:
    text = " ".join([opp.title, opp.summary, " ".join(opp.keywords)]).lower()
    found: list[str] = []
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw.lower() in text for kw in kws):
            found.append(cat)
    return found or ["보조금"]


RESULT_KEYWORDS: tuple[str, ...] = (
    "선정결과",
    "선정 결과",
    "최종 선정",
    "최종선정",
    "결과 발표",
    "결과발표",
    "심사 결과",
    "심사결과",
    "선정 안내",
    "선정안내",
    "선정자",
    "당선",
    "최종 합격",
    "합격자",
    "수상자",
)


def _is_result_announcement(opp: Opportunity) -> bool:
    title = opp.title or ""
    return any(kw in title for kw in RESULT_KEYWORDS)


def _funding_type(opp: Opportunity) -> str:
    text = (opp.title + " " + opp.summary).lower()
    if "보증" in text:
        return "guarantee"
    if "융자" in text or "대출" in text:
        return "loan"
    return "grant"


def _parse_regions(region: str) -> list[str]:
    if not region:
        return []
    cleaned = region.replace("(", " ").replace(")", " ")
    parts = re.split(r"[,/]\s*|\s+및\s+|\s*·\s*", cleaned)
    return [p.strip() for p in parts if p.strip()]


def _to_date(s: str) -> str | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y년 %m월 %d일"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_program_row(opp: Opportunity) -> dict:
    return {
        "id": opp.dedupe_key,
        "source": opp.source_id or "unknown",
        "source_url": opp.url,
        "title": opp.title,
        "org": opp.org,
        "regions": _parse_regions(opp.region),
        "categories": _infer_categories(opp),
        "industries": opp.keywords[:8],
        "keywords": opp.keywords,
        "target_summary": opp.target or opp.eligibility,
        "amount_min": None,
        "amount_max": opp.amount_value,
        "amount_text": opp.amount_text,
        "funding_type": _funding_type(opp),
        "apply_start": _to_date(opp.posted_date),
        "apply_end": _to_date(opp.deadline),
        "is_rolling": False,
        "priority": opp.priority or "normal",
        "raw_text": opp.summary,
        "is_result_announcement": _is_result_announcement(opp),
    }


def upsert_programs(opportunities: Iterable[Opportunity]) -> int:
    """Supabase programs 테이블에 upsert. 키 없으면 조용히 skip."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("[supabase_sync] SUPABASE_URL/SERVICE_ROLE_KEY 미설정 — skip")
        return 0

    rows = [to_program_row(o) for o in opportunities]
    if not rows:
        return 0

    endpoint = f"{url.rstrip('/')}/rest/v1/programs?on_conflict=id"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    BATCH = 100
    sent = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        try:
            resp = requests.post(endpoint, headers=headers, json=batch, timeout=30)
        except requests.RequestException as exc:
            print(f"[supabase_sync] batch {i}-{i+len(batch)} request error: {exc}")
            continue
        if resp.status_code >= 300:
            print(
                f"[supabase_sync] batch {i}-{i+len(batch)} failed: "
                f"{resp.status_code} {resp.text[:200]}"
            )
            continue
        sent += len(batch)
    print(f"[supabase_sync] upserted {sent}/{len(rows)} programs")
    return sent
