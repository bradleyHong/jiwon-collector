"""
Claude(Haiku) 기반 공고 정제.

정규식이 '애매해하는' 공고만 골라 Claude에게 보내 정확히 판정한다.
- 지역 미태깅("확인 필요" 또는 빈값)
- 지자체 슬로건 의심 (제목에 사업 키워드 없음)
- 지원금 불명

비용 절감: 전체가 아니라 애매한 ~20%만 호출. Haiku는 호출당 ~0.3원.

환경변수: ANTHROPIC_API_KEY (없으면 정제 skip → 정규식 결과 그대로)
"""

from __future__ import annotations

import json
import os
from typing import Iterable

import requests

try:
    from anthropic import Anthropic
except ImportError:  # 라이브러리 없으면 정제 비활성
    Anthropic = None  # type: ignore


MVP_REGIONS = ["대구", "부산", "울산", "경북", "경남", "전국"]

BUSINESS_TERMS = (
    "공고", "모집", "지원", "사업", "자금", "대출", "보증", "융자", "신청", "접수",
    "바우처", "창업", "보조", "지원금", "사업화", "컨설팅", "교육", "판로", "마케팅",
    "연구개발", "시제품", "인증", "특허", "수출", "장려", "공모", "R&D", "투자",
)

MODEL = "claude-haiku-4-5"  # 빠르고 저렴

SYSTEM = """너는 한국 정부지원사업 공고를 분석하는 분류기다.
주어진 공고의 제목·기관·본문을 읽고 아래 JSON만 출력한다. 설명 금지.

{
  "regions": ["대구"|"부산"|"울산"|"경북"|"경남"|"전국" 중 해당되는 것 모두. 영남5개·전국 외 지역이거나 불명확하면 []],
  "is_promotional": true/false  (지원사업이 아니라 지자체 홍보/슬로건/행사안내면 true),
  "amount_max_krw": 정수 또는 null (기업당 최대 지원금. "3천만원"=30000000. 불명이면 null),
  "category": "사업지원"|"대출·보증"|"매출·판로"|"제작·개발"|"창업준비"|"교육·컨설팅" 중 가장 맞는 1개,
  "confidence": "high"|"medium"|"low"
}

규칙:
- "의령군 변화의시작 더 살기좋은 의령" 처럼 사업 내용 없는 지자체 슬로건은 is_promotional=true
- 지역은 신청 가능 지역 기준. 중앙부처(중기부 등) 전국 사업은 ["전국"]
- 영남 5개 시도(대구·부산·울산·경북·경남)와 전국만 의미있음. 그 외 지역(서울 등)이면 regions=[]"""


def _needs_refine(opp) -> bool:
    """Claude 정제가 필요한 애매한 공고인지."""
    region = (getattr(opp, "region", "") or "").strip()
    title = getattr(opp, "title", "") or ""
    title_compact = title.replace(" ", "")

    # 1) 지역 미태깅
    if not region or region == "확인 필요":
        return True
    # 2) 슬로건 의심: 제목에 사업 키워드 0개
    if not any(t in title_compact for t in BUSINESS_TERMS):
        return True
    # 3) 금액 불명
    if getattr(opp, "amount_value", None) in (None, 0):
        return True
    return False


def _fetch_db_state(url: str, key: str, ids: list[str]) -> dict | None:
    """후보 공고들의 DB 상태(regions/amount/ai_refined_at)를 조회.
    실패하면 None을 돌려 호출부가 '전체 정제'(기존 동작)로 안전하게 폴백하게 한다."""
    if not ids:
        return {}
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    out: dict[str, dict] = {}
    CHUNK = 40
    for i in range(0, len(ids), CHUNK):
        in_list = ",".join(ids[i : i + CHUNK])
        endpoint = (
            f"{url.rstrip('/')}/rest/v1/programs"
            f"?select=id,regions,amount_max,amount_text,ai_refined_at&id=in.({in_list})"
        )
        try:
            resp = requests.get(endpoint, headers=headers, timeout=20)
            if resp.status_code >= 300:
                print(f"[claude_refine] DB 상태 조회 실패({resp.status_code}) — 전체 정제로 폴백")
                return None
            for row in resp.json():
                out[row["id"]] = row
        except requests.RequestException as exc:
            print(f"[claude_refine] DB 상태 조회 오류({exc}) — 전체 정제로 폴백")
            return None
    return out


def refine_opportunities(opportunities: list, max_calls: int = 300) -> dict:
    """애매한 공고를 Claude로 정제하되 '한 번 정제한 공고는 건너뛴다'.
    ai_refined_at 이 차 있는 공고는 DB에 저장된 분류를 복원만 하고 재호출하지 않는다
    → 같은 공고 반복 정제 비용 제거. opp 객체를 직접 수정. 통계 dict 반환."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or Anthropic is None:
        print("[claude_refine] ANTHROPIC_API_KEY 없음 또는 anthropic 미설치 — skip")
        return {"refined": 0, "skipped": len(opportunities), "promotional_removed": 0, "restored": 0}

    candidates = [o for o in opportunities if _needs_refine(o)]

    # 이미 정제된 공고는 DB 분류를 복원하고 Claude 호출에서 제외한다.
    su_url = os.environ.get("SUPABASE_URL")
    su_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    db_state = (
        _fetch_db_state(su_url, su_key, [o.dedupe_key for o in candidates])
        if (su_url and su_key)
        else None
    )

    targets = []
    restored = 0
    for o in candidates:
        rec = db_state.get(o.dedupe_key) if db_state else None
        if rec and rec.get("ai_refined_at"):
            # 이미 정제됨 → 저장된 값 복원(덮어쓰기 방지), Claude 호출 안 함
            regions = [r for r in (rec.get("regions") or []) if r in MVP_REGIONS]
            if regions:
                o.region = ", ".join(regions)
            if rec.get("amount_max") and not getattr(o, "amount_value", None):
                o.amount_value = rec["amount_max"]
                o.amount_text = rec.get("amount_text") or o.amount_text
            o._ai_refined = True
            restored += 1
        else:
            targets.append(o)
    targets = targets[:max_calls]
    print(
        f"[claude_refine] 후보 {len(candidates)}건 중 "
        f"이미정제 {restored}건 복원, 신규 {len(targets)}건 정제 시도"
    )

    client = Anthropic(api_key=api_key)
    refined = 0
    promo = 0
    for opp in targets:
        text = "\n".join(
            filter(
                None,
                [
                    f"제목: {getattr(opp, 'title', '')}",
                    f"기관: {getattr(opp, 'org', '')}",
                    f"본문: {(getattr(opp, 'summary', '') or '')[:600]}",
                ],
            )
        )
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=300,
                system=SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            raw = resp.content[0].text.strip()
            # JSON 추출
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end < 0:
                continue
            data = json.loads(raw[start : end + 1])
        except Exception as exc:
            print(f"[claude_refine] 호출 실패: {exc}")
            continue

        # 정상 분류됨 → 다음 실행에서 재정제 안 하도록 표시
        opp._ai_refined = True

        # 슬로건/홍보면 메일 제외 표시
        if data.get("is_promotional") is True:
            opp.status = "expired"  # 메일·검색에서 빠지게
            promo += 1
            refined += 1
            continue

        regions = [r for r in (data.get("regions") or []) if r in MVP_REGIONS]
        if regions:
            opp.region = ", ".join(regions)
        amt = data.get("amount_max_krw")
        if isinstance(amt, int) and amt > 0 and not getattr(opp, "amount_value", None):
            opp.amount_value = amt
            opp.amount_text = _fmt_krw(amt)
        refined += 1

    print(f"[claude_refine] 정제 완료: {refined}건 (홍보제거 {promo}건, 복원 {restored}건)")
    return {
        "refined": refined,
        "skipped": len(opportunities) - len(candidates),
        "promotional_removed": promo,
        "restored": restored,
    }


def _fmt_krw(value: int) -> str:
    if value >= 100_000_000:
        v = value / 100_000_000
        return f"{v:g}억원"
    if value >= 10_000_000:
        return f"{value // 10_000_000 * 1000:,}만원"
    if value >= 10_000:
        return f"{value // 10_000:,}만원"
    return f"{value:,}원"
