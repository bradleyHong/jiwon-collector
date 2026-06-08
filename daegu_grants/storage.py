from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


CSV_FIELDS = [
    "기관명",
    "사업명",
    "원문 링크",
    "공고일",
    "마감일",
    "D-day",
    "지원금/지원규모",
    "지원금 숫자값",
    "지역 조건",
    "신청 대상",
    "관련 키워드",
    "첨부파일 링크",
    "요약",
    "추천도 점수",
    "상태",
]


@dataclass
class Opportunity:
    org: str
    title: str
    url: str
    posted_date: str = ""
    deadline: str = ""
    d_day: str = ""
    amount_text: str = ""
    amount_value: int | None = None
    region: str = ""
    target: str = ""
    keywords: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    summary: str = ""
    score: int = 0
    status: str = "seen"
    priority: str = "normal"
    relevance: str = ""
    eligibility: str = ""
    next_action: str = "원문 확인"
    source_id: str = ""

    @property
    def dedupe_key(self) -> str:
        raw = "|".join([self.title.strip(), self.org.strip(), self.deadline.strip(), self.url.strip()])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @property
    def semantic_dedupe_key(self) -> str:
        raw = "|".join([
            normalize_title_for_dedupe(self.title),
            self.deadline.strip() or "rolling",
            normalize_amount_for_dedupe(self.amount_text),
        ])
        if len(raw.replace("|", "")) < 10:
            return self.dedupe_key
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_csv_row(self) -> dict[str, str]:
        return {
            "기관명": self.org,
            "사업명": self.title,
            "원문 링크": self.url,
            "공고일": self.posted_date,
            "마감일": self.deadline,
            "D-day": self.d_day,
            "지원금/지원규모": self.amount_text,
            "지원금 숫자값": str(self.amount_value or ""),
            "지역 조건": self.region,
            "신청 대상": self.target,
            "관련 키워드": ", ".join(self.keywords),
            "첨부파일 링크": ", ".join(self.attachments),
            "요약": self.summary,
            "추천도 점수": str(self.score),
            "상태": self.status,
        }


def ensure_dirs() -> None:
    for path in ["data", "reports", "drafts"]:
        Path(path).mkdir(parents=True, exist_ok=True)


def load_seen(path: str | Path = "data/seen.json") -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8") or "{}")


def save_seen(seen: dict[str, str], path: str | Path = "data/seen.json") -> None:
    Path(path).write_text(json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def deduplicate(opportunities: list[Opportunity]) -> list[Opportunity]:
    by_key: dict[str, Opportunity] = {}
    for opp in opportunities:
        key = opp.semantic_dedupe_key
        current = by_key.get(key)
        if current is None or opportunity_rank(opp) > opportunity_rank(current):
            by_key[key] = opp
    return sorted(by_key.values(), key=lambda item: (item.status == "expired", -item.score, item.deadline or "9999"))


def opportunity_rank(opp: Opportunity) -> tuple[int, int, int]:
    has_direct_url = int(bool(opp.url and not opp.url.endswith("/")))
    has_amount = int(opp.amount_value is not None or bool(opp.amount_text))
    return (opp.score, has_amount, has_direct_url)


def normalize_title_for_dedupe(title: str) -> str:
    text = title.lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\d{4}[-./년]\s*\d{1,2}[-./월]\s*\d{1,2}일?", " ", text)
    text = re.sub(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", " ", text)
    text = re.sub(r"\bd[-+]?\d+\b", " ", text)
    text = re.sub(r"조회\s*\d+", " ", text)
    text = re.sub(r"등록일자\s*\S+", " ", text)
    text = re.sub(r"마감일자\s*\S+", " ", text)
    text = re.sub(r"(사업)?공고|모집공고|모집|참가기업|참여기업|지원사업|사업화", " ", text)
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_amount_for_dedupe(amount: str) -> str:
    text = amount.lower().strip()
    if not text or "확인" in text:
        return "amount_unknown"
    return re.sub(r"[^0-9억만원천백십]+", "", text)[:24] or "amount_unknown"


def apply_seen_status(opportunities: list[Opportunity], seen: dict[str, str]) -> list[Opportunity]:
    for opp in opportunities:
        key = opp.dedupe_key
        fingerprint = opp.fingerprint
        if opp.status == "expired":
            continue
        if key not in seen:
            if opp.status == "seen":
                opp.status = "new"
        elif seen[key] != fingerprint:
            if opp.status != "needs_review":
                opp.status = "updated"
        else:
            if opp.status not in {"needs_review", "expired"}:
                opp.status = "seen"
    return opportunities


def update_seen(opportunities: list[Opportunity], seen: dict[str, str]) -> dict[str, str]:
    for opp in opportunities:
        seen[opp.dedupe_key] = opp.fingerprint
    return seen


def save_csv(opportunities: list[Opportunity], path: str | Path = "data/opportunities.csv") -> None:
    path = Path(path)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for opp in opportunities:
            writer.writerow(opp.to_csv_row())
