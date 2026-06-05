from __future__ import annotations

import re
import hashlib
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser


MONEY_PATTERNS = [
    re.compile(r"(?:최대|기업당|과제당|지원금|지원규모|총사업비|사업비)?\s*([0-9][0-9,\.]*)\s*(억\s*원|억원|억|천만\s*원|천만원|천원|백만\s*원|백만원|만\s*원|만원|원)"),
    re.compile(r"([0-9]+)\s*개사.*?([0-9][0-9,\.]*)\s*(억\s*원|억원|억|천만\s*원|천만원|천원|백만\s*원|백만원|만\s*원|만원|원)"),
]


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def parse_korean_date(value: str | None, default_year: int | None = None) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    default_year = default_year or date.today().year
    text = re.sub(r"\([^)]*\)", "", text)
    patterns = [
        r"(\d{4})[-./년 ]+(\d{1,2})[-./월 ]+(\d{1,2})",
        r"(\d{1,2})[-./월 ]+(\d{1,2})일?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = [int(p) for p in match.groups()]
        if len(parts) == 2:
            parts = [default_year, *parts]
        try:
            return date(parts[0], parts[1], parts[2])
        except ValueError:
            return None
    try:
        return date_parser.parse(text, fuzzy=True, default=datetime(default_year, 1, 1)).date()
    except (ValueError, TypeError, OverflowError):
        return None


def extract_deadline(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    compact = clean_text(text)
    deadline_labels = [
        r"(?:마감일자|마감일|접수마감|신청마감|공고마감|종료일|까지|~)\s*[:：]?\s*([0-9]{4}[-./년 ]+[0-9]{1,2}[-./월 ]+[0-9]{1,2})",
        r"(?:마감일자|마감일|접수마감|신청마감|공고마감|종료일|까지|~)\s*[:：]?\s*([0-9]{1,2}[-./월 ]+[0-9]{1,2})",
    ]
    for pattern in deadline_labels:
        match = re.search(pattern, compact)
        if match:
            parsed = parse_korean_date(match.group(1), today.year)
            if parsed:
                return parsed
    dates = [parse_korean_date(m.group(0), today.year) for m in re.finditer(r"\d{4}[-./년 ]+\d{1,2}[-./월 ]+\d{1,2}", compact)]
    dates = [d for d in dates if d]
    if dates:
        return max(dates)
    dday = re.search(r"D[-+]\s*(\d+)|마감\s*(\d+)\s*일전", compact, re.IGNORECASE)
    if dday:
        days = int(next(group for group in dday.groups() if group))
        return today.fromordinal(today.toordinal() + days)
    if "오늘마감" in compact or "오늘 마감" in compact:
        return today
    return None


def extract_posted_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    match = re.search(r"(?:등록일자|등록일|공고일|게재일자)\s*[:：]?\s*([0-9]{4}[-./년 ]+[0-9]{1,2}[-./월 ]+[0-9]{1,2})", clean_text(text))
    if match:
        return parse_korean_date(match.group(1), today.year)
    dates = [parse_korean_date(m.group(0), today.year) for m in re.finditer(r"\d{4}[-./년 ]+\d{1,2}[-./월 ]+\d{1,2}", clean_text(text))]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def money_to_krw(number: str, unit: str) -> int:
    value = float(number.replace(",", ""))
    unit = re.sub(r"\s+", "", unit)
    if unit in {"억원", "억"}:
        return int(value * 100_000_000)
    if unit == "천만원":
        return int(value * 10_000_000)
    if unit == "천원":
        return int(value * 1_000)
    if unit == "백만원":
        return int(value * 1_000_000)
    if unit == "만원":
        return int(value * 10_000)
    return int(value)


def parse_money_value(text: str | None) -> tuple[str, int | None]:
    text = clean_text(text)
    if not text:
        return "", None
    values: list[tuple[str, int]] = []
    for pattern in MONEY_PATTERNS:
        for match in pattern.finditer(text):
            if len(match.groups()) == 3:
                amount_text = f"{match.group(2)}{match.group(3)}"
                amount_value = money_to_krw(match.group(2), match.group(3))
            else:
                amount_text = f"{match.group(1)}{match.group(2)}"
                amount_value = money_to_krw(match.group(1), match.group(2))
            if amount_value >= 100_000:
                values.append((clean_text(amount_text), amount_value))
    if not values:
        return "", None
    amount_text, amount_value = max(values, key=lambda item: item[1])
    return amount_text, amount_value


def parse_selection_count(text: str | None) -> tuple[str, int | None]:
    text = clean_text(text)
    if not text:
        return "", None
    patterns = [
        r"(?:선정규모|선발규모|모집규모|지원규모|선발인원|선정|선발|모집)\s*[:：]?\s*([0-9][0-9,]*)\s*(개사|개\s*기업|기업|개|팀|명)",
        r"([0-9][0-9,]*)\s*(개사|개\s*기업|기업|팀|명)\s*(?:내외|선정|선발|모집|지원)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            count = int(match.group(1).replace(",", ""))
            unit = re.sub(r"\s+", "", match.group(2))
            if 0 < count <= 10000:
                return f"{count}{unit}", count
    return "", None


def format_krw(value: int | None) -> str:
    if not value:
        return "확인 필요"
    if value >= 100_000_000:
        amount = value / 100_000_000
        return f"{amount:g}억원"
    if value >= 10_000_000:
        amount = value / 10_000_000
        return f"{amount:g}천만원"
    if value >= 10_000:
        amount = value / 10_000
        return f"{amount:g}만원"
    return f"{value:,}원"


def format_amount_summary(amount_text: str, amount_value: int | None, text: str | None) -> str:
    if not amount_value:
        return amount_text or "확인 필요"
    count_text, count = parse_selection_count(text)
    text = clean_text(text)
    is_per_company = bool(re.search(r"(기업당|개사당|과제당|팀당|인당|1\s*개사)", text))
    if count and count > 1:
        if is_per_company:
            return f"기업당 {amount_text} / 선정 {count_text}"
        return f"총 {amount_text} / 선정 {count_text} / 기업당 약 {format_krw(amount_value // count)}"
    return amount_text


def calculate_dday(deadline: date | None, today: date | None = None) -> str:
    if not deadline:
        return ""
    today = today or date.today()
    delta = (deadline - today).days
    if delta == 0:
        return "D-0"
    if delta > 0:
        return f"D-{delta}"
    return f"D+{abs(delta)}"


def extract_region(text: str) -> str:
    text = clean_text(text)
    region_patterns = [
        ("대구", ["대구광역시", "대구 ", "대구시", "대구테크노파크", "대구디지털", "대구창조", "대구콘텐츠", "대구신용보증", "대구 소재"]),
        ("부산", ["부산광역시", "부산 ", "부산시", "부산테크노파크", "부산신용보증", "부산 소재"]),
        ("경북", ["경상북도", "경북 ", "경북도", "경북테크노파크", "경북신용보증", "경북 소재"]),
        ("경남", ["경상남도", "경남 ", "경남도", "경남테크노파크", "경남신용보증", "경남 소재"]),
    ]
    for region, patterns in region_patterns:
        if any(pattern in text for pattern in patterns):
            return region
    if "전국" in text or "소재지 제한" in text:
        return "전국"
    return ""


def extract_target(text: str) -> str:
    text = clean_text(text)
    candidates = []
    age_patterns = [
        r"(?:창업|업력)\s*([0-9]+)\s*년\s*(?:이내|이하|미만)",
        r"([0-9]+)\s*년\s*(?:이내|이하|미만)\s*(?:창업기업|기업|사업자)",
    ]
    for pattern in age_patterns:
        for match in re.finditer(pattern, text):
            candidates.append(f"창업 {match.group(1)}년 이하")
    if re.search(r"(신규\s*창업|신규창업|창업\s*예정|새로\s*창업)", text):
        candidates.append("신규창업")
    for keyword in [
        "여성기업",
        "창업기업",
        "예비창업자",
        "초기창업기업",
        "재창업기업",
        "중소기업",
        "소상공인",
        "콘텐츠기업",
        "제조업",
        "제조기업",
        "도소매업",
        "도매업",
        "소매업",
        "로봇기업",
        "화훼",
        "꽃",
        "예술기업",
        "문화예술",
        "사회적기업",
        "마을기업",
        "일반기업",
        "대학생",
    ]:
        if keyword in text:
            candidates.append(keyword)
    return ", ".join(dict.fromkeys(candidates))


def extract_attachment_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        label = clean_text(anchor.get_text(" "))
        if re.search(r"\.(pdf|hwp|hwpx|docx?|xlsx?)($|\?)", href, re.I) or "첨부" in label or "다운로드" in label:
            links.append(urljoin(base_url, href))
    return list(dict.fromkeys(links))


def summarize(text: str, max_len: int = 180) -> str:
    text = clean_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def normalize_opportunity_title(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"^(사업화|공모전|사업공고|공고|공지)\s*", "", text)
    text = re.sub(r"^D[-+]\d+\s*", "", text, flags=re.I)
    text = re.sub(r"마감일자\s*\d{4}[-./]\d{1,2}[-./]\d{1,2}", "", text)
    text = re.sub(r"등록일자\s*\d{4}[-./]\d{1,2}[-./]\d{1,2}", "", text)
    text = re.sub(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}\s*~\s*\d{4}[-./]\d{1,2}[-./]\d{1,2}", "", text)
    text = re.sub(r"조회\s*[0-9,]+", "", text)
    text = text.replace("새로운게시글", "")
    text = re.sub(r"\s+", " ", text).strip(" -_/")
    for suffix in ["달구벌여성인력개발센터", "대구상공회의소", "창업진흥원", "대구디지털혁신진흥원"]:
        text = re.sub(rf"\s*{re.escape(suffix)}\s*$", "", text).strip()
    return clean_text(text)


def slugify_filename(value: str, max_len: int = 80) -> str:
    value = clean_text(value)
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    ascii_part = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    ascii_part = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_part).strip("._")
    ascii_part = ascii_part[: max(10, max_len - 11)].strip("._")
    return f"{ascii_part or 'grant'}_{digest}"[:max_len]


def read_text_file(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def join_nonempty(values: Iterable[str], sep: str = ", ") -> str:
    return sep.join([v for v in values if v])
