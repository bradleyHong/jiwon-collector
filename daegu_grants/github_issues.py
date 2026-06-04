from __future__ import annotations

import os
from pathlib import Path

import requests

from .parsers import normalize_opportunity_title
from .storage import Opportunity


def should_create_issue(opp: Opportunity) -> bool:
    return opp.status in {"new", "updated", "needs_review"} and opp.priority in {"high_priority", "needs_review"}


def issue_title(opp: Opportunity) -> str:
    amount = opp.amount_text if opp.amount_value else "금액확인"
    dday = opp.d_day or "D-?"
    return f"[지원사업][{dday}][{amount}] {opp.title[:60]}"


def issue_body(opp: Opportunity, draft_path: Path | None) -> str:
    draft = str(draft_path) if draft_path else "TODO: 지원서 초안 생성 여부 확인"
    return f"""## 공고 요약

{opp.summary or "TODO: 원문 확인"}

## 왜 우리에게 맞는지

- 관련 키워드: {", ".join(opp.keywords) or "TODO: 관련성 확인"}
- 신청 가능성: {opp.eligibility or "TODO: 신청 가능성 확인"}
- 추천 점수: {opp.score}

## 지원금/사업비

{opp.amount_text or "TODO: 지원금/사업비 확인"}

## 마감일과 남은 일수

- 마감일: {opp.deadline or "TODO: 마감일 확인"}
- D-day: {opp.d_day or "TODO"}

## 신청 자격

{opp.target or "TODO: 신청 자격 확인"}

## 준비해야 할 서류 체크리스트

- [ ] 공고문 상세 확인
- [ ] 사업계획서 양식 다운로드
- [ ] 회사 기본 서류 준비
- [ ] 재무/4대보험/국세·지방세 증빙 확인
- [ ] 견적서 또는 산출 근거 준비
- [ ] 제출 전 신청 자격 재확인

## 지원서 초안 링크

{draft}

## 원문 링크

{opp.url}
"""


def create_issue(opp: Opportunity, draft_path: Path | None, dry_run: bool = False) -> str | None:
    if dry_run:
        return None
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    assignee = os.getenv("GH_USERNAME")
    payload = {
        "title": issue_title(opp),
        "body": issue_body(opp, draft_path),
        "labels": ["지원사업", opp.priority],
    }
    if assignee:
        payload["assignees"] = [assignee]
    response = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("html_url")


def create_issues(opportunities: list[Opportunity], draft_paths: dict[str, Path], dry_run: bool = False) -> list[str]:
    urls = []
    seen_titles = set()
    for opp in opportunities:
        display_key = (opp.org, normalize_opportunity_title(opp.title), opp.deadline)
        if display_key in seen_titles:
            continue
        if should_create_issue(opp):
            created = create_issue(opp, draft_paths.get(opp.dedupe_key), dry_run=dry_run)
            seen_titles.add(display_key)
            if created:
                urls.append(created)
    return urls
