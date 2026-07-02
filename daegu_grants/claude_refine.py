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

# 모델은 env로 교체 가능(레포 variable). 미설정 시 기본값.
MODEL = os.environ.get("ANTHROPIC_REFINE_MODEL") or "claude-haiku-4-5"  # Anthropic 1순위
OPENAI_MODEL = os.environ.get("OPENAI_REFINE_MODEL") or "gpt-4.1-mini"  # 폴백/전용 (저렴)

SYSTEM = """너는 한국 정부지원사업 공고를 분석하는 분류기다. 고객은 영남(대구·부산·울산·경북·경남)의 사업자·(예비)창업자이며, 이들이 실제로 신청해 혜택받을 수 있는 공고만 통과시켜야 한다.
주어진 공고의 제목·기관·본문을 읽고 아래 JSON만 출력한다. 설명 금지.

{
  "regions": ["대구"|"부산"|"울산"|"경북"|"경남"|"전국" 중 해당되는 것 모두. 영남5개·전국 외 지역이거나 불명확하면 []],
  "is_for_business": true/false  (사업자·기업·소상공인·스타트업·예비창업자 대상이면 true, 개인·주민 복지면 false),
  "is_promotional": true/false  (신청 가능한 지원사업이 아니라 홍보/슬로건/단순 안내면 true),
  "amount_max_krw": 정수 또는 null (기업 1곳당 최대 지원금. "3천만원"=30000000. 불명이면 null),
  "category": "사업지원"|"대출·보증"|"매출·판로"|"제작·개발"|"창업준비"|"교육·컨설팅" 중 가장 맞는 1개,
  "confidence": "high"|"medium"|"low"
}

규칙:
1) is_for_business (가장 중요): 개인 복지는 false — 양육수당·아이돌봄·급식·학자금·주거비·전세보증금·희망통장·개인 바우처 등 가계 지원, 주민 생활·행정 안내, 시민 문화·건강 강좌, 개인 구직수당. 사업자(등록 예정 포함)·기업 혜택이면 true. 애매하면 true(놓치는 것이 더 나쁘다).
2) is_promotional: "의령군 변화의시작 더 살기좋은 의령" 같은 슬로건, 시스템 점검·매뉴얼, 선정 결과 발표, 단순 설명회·시상식 관람 안내는 true. 공모전·경진대회·챌린지·아이디어공모는 상금/지원/혜택이 있으면 신청 가능한 지원사업 → false (전국 대형 공모전을 놓치지 말 것). 박람회·전시회도 참가기업 모집(부스비·판로 지원)이면 false.
3) regions: 기관 소재지가 아니라 "신청 자격 지역" 기준. 중앙부처·전국 모집은 ["전국"]. "OO 소재 기업" 조건이 있으면 그 지역만. 영남5·전국 외 한정(예: 서울시 소재 기업만)이거나 판단 불가면 [].
4) amount_max_krw: 반드시 기업 1곳이 받는 최대액. 사업 총예산·총사업비를 기업당 금액으로 착각하지 말 것(그 경우 null).

예시:
- "2026 혁신 소상공인 AI 활용지원 참여 소상공인 모집" → is_for_business=true, is_promotional=false, regions=["전국"]
- "경북 청년농업인 영농정착 지원(경북 소재)" → true, false, ["경북"]
- "부산시 아이돌봄 양육수당 신청 안내" → is_for_business=false
- "달성군 사업관리시스템 사용자 매뉴얼 안내" → is_promotional=true"""


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


def _anthropic_classify(client, user_text: str) -> str | None:
    """Anthropic Haiku로 분류. 실패(크레딧소진·오류) 시 None."""
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=300, system=SYSTEM,
            messages=[{"role": "user", "content": user_text}],
        )
        return resp.content[0].text
    except Exception as exc:
        print(f"[claude_refine] anthropic 실패: {exc}")
        return None


def _openai_classify(user_text: str) -> str | None:
    """OpenAI gpt-4.1-mini로 분류(폴백). 키 없거나 실패 시 None."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": OPENAI_MODEL,
                "max_completion_tokens": 300,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user_text},
                ],
            },
            timeout=30,
        )
        if resp.status_code >= 300:
            print(f"[claude_refine] openai 실패({resp.status_code})")
            return None
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"[claude_refine] openai 오류: {exc}")
        return None


def refine_opportunities(opportunities: list, max_calls: int = 300) -> dict:
    """애매한 공고를 Claude로 정제하되 '한 번 정제한 공고는 건너뛴다'.
    ai_refined_at 이 차 있는 공고는 DB에 저장된 분류를 복원만 하고 재호출하지 않는다
    → 같은 공고 반복 정제 비용 제거. opp 객체를 직접 수정. 통계 dict 반환."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if (not api_key or Anthropic is None) and not openai_key:
        print("[claude_refine] LLM 키 없음(ANTHROPIC/OPENAI) — skip")
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

    # LLM_PROVIDER=openai 면 Claude를 아예 호출하지 않는다(크레딧 보호). 미설정이면 Claude 우선 + OpenAI 폴백.
    only_openai = os.environ.get("LLM_PROVIDER", "").strip().lower() == "openai"
    client = None if only_openai else (Anthropic(api_key=api_key) if (api_key and Anthropic is not None) else None)
    anthropic_ok = client is not None  # 실행 중 Anthropic이 죽으면 False로 내려 OpenAI만 쓴다
    if only_openai:
        print("[claude_refine] LLM_PROVIDER=openai → Claude 미사용, OpenAI로만 정제")
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
        # 1순위 Anthropic(품질 유지) → 실패 시 OpenAI 폴백. 둘 다 실패하면 skip.
        raw = None
        if anthropic_ok:
            raw = _anthropic_classify(client, text)
            if raw is None:
                anthropic_ok = False  # 이번 실행에선 Anthropic 죽음 → 남은 건 OpenAI로
        if raw is None:
            raw = _openai_classify(text)
        if raw is None:
            continue
        raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < 0:
            continue
        try:
            data = json.loads(raw[start : end + 1])
        except Exception:
            continue

        # 정상 분류됨 → 다음 실행에서 재정제 안 하도록 표시
        opp._ai_refined = True

        # 슬로건/홍보 또는 개인복지(사업자 무관)면 메일 제외 표시.
        # is_for_business는 명시적 false일 때만 제외(키 누락 시 통과 = 하위호환).
        if data.get("is_promotional") is True or data.get("is_for_business") is False:
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

    print(f"[claude_refine] 정제 완료: {refined}건 (홍보·비사업 제거 {promo}건, 복원 {restored}건)")
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
