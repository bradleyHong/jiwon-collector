from __future__ import annotations

from datetime import date
from pathlib import Path

from .parsers import normalize_opportunity_title, read_text_file, slugify_filename
from .storage import Opportunity


def should_generate_draft(opp: Opportunity) -> bool:
    noisy = ["본문 바로가기", "로그아웃 안내", "전체메뉴", "누리집", "화면확대"]
    if any(token in opp.title for token in noisy) or len(opp.title) > 150:
        return False
    return opp.status in {"new", "updated", "needs_review"} and (
        opp.priority == "high_priority" or (opp.priority == "needs_review" and opp.score >= 50) or opp.score >= 60
    )


def generate_draft(opp: Opportunity, today: date | None = None) -> Path:
    today = today or date.today()
    company_profile = read_text_file("company_profile.md")
    project_profile = read_text_file("project_profile.md")
    target_dir = Path("drafts") / today.isoformat() / slugify_filename(opp.title)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "application_draft.md"
    path.write_text(build_draft(opp, company_profile, project_profile), encoding="utf-8")
    return path


def generate_drafts(opportunities: list[Opportunity], today: date | None = None) -> dict[str, Path]:
    result = {}
    seen_titles = set()
    for opp in opportunities:
        display_key = (opp.org, normalize_opportunity_title(opp.title), opp.deadline)
        if display_key in seen_titles:
            continue
        if should_generate_draft(opp):
            result[opp.dedupe_key] = generate_draft(opp, today)
            seen_titles.add(display_key)
    return result


def build_draft(opp: Opportunity, company_profile: str, project_profile: str) -> str:
    return f"""# 지원서 초안

- 공고명: {opp.title}
- 기관: {opp.org}
- 원문 링크: {opp.url}
- 마감일: {opp.deadline or "TODO: 마감일 확인"}
- 지원금/지원규모: {opp.amount_text or "TODO: 지원금 확인"}
- 상태: {opp.status}

## 사업 신청 배경

TODO: 아래 회사/프로젝트 프로필을 바탕으로 이 공고의 신청 배경을 구체화하세요. 공고 원문에서 요구하는 사업 목적과 신청 자격을 확인한 뒤 작성해야 합니다.

## 과제 목표

TODO: 정량 목표와 산출물을 입력하세요. 예: 시제품, 콘텐츠 결과물, 실증 횟수, 전시/상영 계획, 매출/고용 목표.

## AI/미디어아트/미디어파사드/영상 활용 계획

TODO: 실제 보유 기술과 수행 가능한 범위만 작성하세요. 아직 확인되지 않은 기술, 장비, 파트너사는 지어내지 마세요.

## 추진 일정

| 단계 | 기간 | 주요 내용 |
|---|---|---|
| 기획 | TODO | 요구사항 분석, 콘셉트/시나리오 설계 |
| 제작/개발 | TODO | AI/영상/콘텐츠 제작 또는 시스템 개발 |
| 실증/전시 | TODO | 현장 테스트, 사용자 피드백, 보완 |
| 결과 정리 | TODO | 결과보고서, 정산, 후속 사업화 계획 |

## 예산 사용 계획

| 항목 | 금액 | 산출 근거 |
|---|---:|---|
| 인건비 | TODO | TODO |
| 외주/용역비 | TODO | TODO |
| 장비/소프트웨어 | TODO | TODO |
| 홍보/전시/실증 | TODO | TODO |
| 기타 | TODO | TODO |

## 기대효과

TODO: 사업 종료 후 기술/콘텐츠 완성도, 매출, 고용, 지역 확산, 공공 활용 가능성을 정리하세요.

## 대구 지역 기여도

TODO: 대구 소재 기업/기관/공간/행사와 연결되는 지역 기여 내용을 작성하세요.

## 여성기업/창업기업/지역기업 관점의 강점

TODO: company_profile.md의 실제 정보에 근거해 작성하세요. 여성기업 인증 여부, 창업 연차, 지역 고용 등은 확인 전까지 TODO로 둡니다.

## 공고에서 확인해야 할 TODO

- TODO: 신청 자격 세부 조건
- TODO: 총사업비, 정부지원금, 민간부담금 비율
- TODO: 필수 제출 서류
- TODO: 평가 기준
- TODO: 접수 방식과 접수처

## 참고 프로필

### Company

{company_profile.strip() or "TODO: company_profile.md 작성 필요"}

### Project

{project_profile.strip() or "TODO: project_profile.md 작성 필요"}
"""
