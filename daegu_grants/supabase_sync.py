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
from datetime import datetime, timezone
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


LOCALIZED_REGISTRATION_KEYWORDS: tuple[str, ...] = (
    "관내 등록",
    "관내등록",
    "관내 이전",
    "관내이전",
    "지역 등록",
    "지역등록",
    "지역 사업자",
    "지역사업자",
    "지역 정착",
    "지역정착",
    "지역소재",
    "지역 소재",
    "본점 이전",
    "본점이전",
    "지역 본점",
    "지역본점",
    "지역 사무소",
    "현지 등록",
    "현지등록",
    "관할 등록",
    "사업자등록 예정",
    "사업자 등록 예정",
    "선정 후 사업자",
    "선정후 사업자",
    "지역 신규창업",
    "지역신규창업",
)


def _has_localized_registration(opp: Opportunity) -> bool:
    text = (opp.title or "") + " " + (opp.summary or "") + " " + (opp.target or "")
    return any(kw in text for kw in LOCALIZED_REGISTRATION_KEYWORDS)


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


def _build_industries(opp: Opportunity) -> list[str]:
    base = list(opp.keywords[:8])
    if _has_localized_registration(opp) and "신규사업자 등록" not in base:
        base.append("신규사업자 등록")
    return base


def to_program_row(opp: Opportunity) -> dict:
    return _clean_for_postgres({
        "id": opp.dedupe_key,
        "source": opp.source_id or "unknown",
        "source_url": opp.url,
        "title": opp.title,
        "org": opp.org,
        "regions": _parse_regions(opp.region),
        "categories": _infer_categories(opp),
        "industries": _build_industries(opp),
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
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    })


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
            sent += _upsert_rows_one_by_one(endpoint, headers, batch, start=i)
            continue
        sent += len(batch)
    print(f"[supabase_sync] upserted {sent}/{len(rows)} programs")
    return sent


def _upsert_rows_one_by_one(endpoint: str, headers: dict[str, str], rows: list[dict], start: int = 0) -> int:
    """Batch 실패 시 한 행씩 재시도해 전체 수집 실패를 막는다."""
    sent = 0
    for offset, row in enumerate(rows):
        try:
            resp = requests.post(endpoint, headers=headers, json=[row], timeout=20)
        except requests.RequestException as exc:
            print(f"[supabase_sync] row {start + offset} request error: {exc}")
            continue
        if resp.status_code >= 300:
            print(
                f"[supabase_sync] row {start + offset} skipped: "
                f"{resp.status_code} {resp.text[:200]} title={row.get('title', '')[:80]}"
            )
            continue
        sent += 1
    return sent


def _clean_for_postgres(value):
    """Postgres text/jsonb가 거부하는 NUL 제어문자를 재귀적으로 제거한다."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_clean_for_postgres(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean_for_postgres(item) for key, item in value.items()}
    return value
