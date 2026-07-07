from __future__ import annotations

import os
import re
import tempfile
import time
import urllib.robotparser
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import certifi
import feedparser
import requests
from bs4 import BeautifulSoup

from .classifier import classify
from .parsers import (
    calculate_dday,
    clean_text,
    extract_attachment_links,
    extract_deadline,
    extract_posted_date,
    extract_region,
    extract_target,
    format_amount_summary,
    parse_money_value,
    summarize,
)
from .sources import Source
from .storage import Opportunity

# certifi 기본 번들 + 동봉한 중간 인증서를 합친 CA 번들 경로 (프로세스당 1회 생성).
# 일부 한국 기관 사이트(bepa.kr, cwip.or.kr 등)가 중간 인증서를 안 보내
# 검증이 실패하는데, 검증을 끄는 대신 누락분을 우리가 보충한다.
_CA_BUNDLE_PATH: str | None = None


def _combined_ca_bundle() -> str:
    global _CA_BUNDLE_PATH
    if _CA_BUNDLE_PATH:
        return _CA_BUNDLE_PATH
    supplement = Path(__file__).parent / "certs" / "intermediate-ca-supplement.pem"
    if not supplement.exists():
        _CA_BUNDLE_PATH = certifi.where()
        return _CA_BUNDLE_PATH
    combined = tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", prefix="ca-bundle-", delete=False
    )
    with combined:
        combined.write(Path(certifi.where()).read_text())
        combined.write("\n")
        combined.write(supplement.read_text())
    _CA_BUNDLE_PATH = combined.name
    return _CA_BUNDLE_PATH


class Scraper:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.session = requests.Session()
        self.session.verify = _combined_ca_bundle()
        self.session.headers.update(
            {
                "User-Agent": settings.get("user_agent", "daegu-grants-monitor/1.0"),
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            }
        )
        self.timeout = int(settings.get("timeout_seconds", 15))
        self.delay = float(settings.get("request_delay_seconds", 1.5))
        self.minimum_amount = int(settings.get("minimum_amount_krw", 20_000_000))
        self.detail_fetch_limit = int(settings.get("detail_fetch_limit_per_source", 6))
        self.max_runtime_seconds = int(settings.get("max_runtime_seconds", 0) or 0)
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = urljoin(base, "/robots.txt")
            rp.set_url(robots_url)
            try:
                response = self.session.get(robots_url, timeout=min(self.timeout, 5))
                if response.status_code >= 400:
                    return True
                rp.parse(response.text.splitlines())
            except Exception:
                return True
            self._robots[base] = rp
        return self._robots[base].can_fetch(self.session.headers["User-Agent"], url)

    def get(self, url: str) -> requests.Response:
        if not self.can_fetch(url):
            raise RuntimeError(f"robots.txt disallows fetching {url}")
        time.sleep(self.delay)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding
        return response

    def scrape(self, sources: list[Source], today: date | None = None) -> tuple[list[Opportunity], list[str]]:
        today = today or date.today()
        opportunities: list[Opportunity] = []
        errors: list[str] = []
        started_at = time.monotonic()
        for index, source in enumerate(sources, start=1):
            if self.max_runtime_seconds and time.monotonic() - started_at > self.max_runtime_seconds:
                remaining = len(sources) - index + 1
                errors.append(
                    f"time budget reached after {index - 1}/{len(sources)} sources; "
                    f"skipped {remaining} remaining sources"
                )
                break
            try:
                if source.adapter == "rss":
                    opportunities.extend(self.scrape_rss(source, today))
                elif source.adapter == "bizinfo_api":
                    opportunities.extend(self.scrape_bizinfo(source, today))
                else:
                    opportunities.extend(self.scrape_html_list(source, today))
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
        return opportunities, errors

    def scrape_rss(self, source: Source, today: date) -> list[Opportunity]:
        response = self.get(source.url)
        feed = feedparser.parse(response.content)
        opportunities = []
        for entry in feed.entries[:80]:
            title = clean_text(entry.get("title", ""))
            url = entry.get("link", source.url)
            body = clean_text(entry.get("summary", "") or entry.get("description", ""))
            posted = ""
            if entry.get("published"):
                try:
                    posted = parsedate_to_datetime(entry.published).date().isoformat()
                except Exception:
                    posted = ""
            opportunities.append(self.make_opportunity(source, title, url, body, today, posted_date=posted))
        return opportunities

    def scrape_bizinfo(self, source: Source, today: date) -> list[Opportunity]:
        api_key = os.getenv(source.api_key_env or "BIZINFO_API_KEY")
        if not api_key:
            fallback = Source(
                id=source.id,
                name=source.name,
                org=source.org,
                adapter="html_list",
                url=source.fallback_url or source.search_url,
                search_url=source.search_url,
            )
            return self.scrape_html_list(fallback, today)
        params = dict(source.params)
        params["crtfcKey"] = api_key
        response = self.get_with_params(source.url, params)
        payload = response.json()
        items = payload.get("jsonArray") or payload.get("item") or payload.get("items") or []
        if isinstance(items, dict):
            items = items.get("item", [])
        opportunities = []
        for item in items[:300]:  # 기업마당 포괄 수집(전국·전분야). Eaasy가 영남5+전국으로 필터.
            title = clean_text(item.get("pblancNm") or item.get("title"))
            url = item.get("pblancUrl") or item.get("link") or source.search_url
            summary = clean_text(item.get("bsnsSumryCn") or item.get("description"))
            reqst = clean_text(item.get("reqstDt"))
            posted = clean_text(item.get("pubDate", "")).split(" ")[0]
            deadline = ""
            if "~" in reqst:
                deadline = reqst.split("~")[-1].strip()
            attachments = [item.get("flpthNm") or "", item.get("printFlpthNm") or ""]
            opp = self.make_opportunity(source, title, url, f"{summary} {reqst} {item.get('hashTags','')}", today, posted_date=posted)
            opp.attachments = [a for a in attachments if a]
            opportunities.append(opp)
        return opportunities

    def get_with_params(self, url: str, params: dict[str, Any]) -> requests.Response:
        if not self.can_fetch(url):
            raise RuntimeError(f"robots.txt disallows fetching {url}")
        time.sleep(self.delay)
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response

    def scrape_html_list(self, source: Source, today: date) -> list[Opportunity]:
        response = self.get(source.url)
        soup = BeautifulSoup(response.text, "html.parser")
        attachment_links = extract_attachment_links(soup, source.url)
        candidates = self.extract_candidate_blocks(soup, source.url)
        if not candidates:
            candidates = [{"title": source.name, "url": source.url, "text": soup.get_text(" ")}]
        opportunities = []
        detail_fetches = 0
        for candidate in candidates[:80]:
            title = clean_text(candidate["title"])
            if len(title) < 8 or self.is_navigation_title(title):
                continue
            text = clean_text(candidate.get("text") or title)
            url = candidate.get("url") or source.url
            attachments = attachment_links[:5]
            if detail_fetches < self.detail_fetch_limit and self.should_fetch_detail(source.url, url, title, text):
                detail_text, detail_attachments = self.fetch_detail_text(url)
                if detail_text:
                    text = clean_text(f"{text} {detail_text}")
                    attachments = list(dict.fromkeys([*detail_attachments, *attachments]))[:8]
                    detail_fetches += 1
            opp = self.make_opportunity(source, title, url, text, today)
            opp.attachments = attachments
            opportunities.append(opp)
        return opportunities

    def should_fetch_detail(self, source_url: str, candidate_url: str, title: str, text: str) -> bool:
        if not candidate_url or candidate_url == source_url:
            return False
        source_host = urlparse(source_url).netloc
        candidate_host = urlparse(candidate_url).netloc
        if source_host and candidate_host and source_host != candidate_host:
            return False
        haystack = f"{title} {text}"
        return any(
            token in haystack
            for token in [
                "지원",
                "공고",
                "모집",
                "사업화",
                "제작",
                "콘텐츠",
                "AI",
                "창업",
                "디자인",
                "실증",
                "R&D",
            ]
        )

    def fetch_detail_text(self, url: str) -> tuple[str, list[str]]:
        try:
            response = self.get(url)
        except Exception:
            return "", []
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return clean_text(soup.get_text(" ")), extract_attachment_links(soup, url)

    def extract_candidate_blocks(self, soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        anchor_titles: list[str] = []
        for anchor in soup.find_all("a", href=True):
            title = clean_text(anchor.get_text(" "))
            raw_href = anchor["href"].strip()
            onclick = clean_text(anchor.get("onclick") or "")
            # 일부 사이트(예: startup.daegu.go.kr)는 실제 상세글 ID를 href가 아니라
            # onclick 속성의 JS 호출에만 담아둔다(href는 "javascript:;" 같은 자리표시자).
            # href가 자리표시자면 onclick 쪽을 대신 넘겨서 normalize_url이 파싱하게 한다.
            link_source = (
                onclick if raw_href.lower() in ("javascript:;", "javascript:void(0);", "javascript:void(0)", "#") and onclick
                else raw_href
            )
            href = self.normalize_url(link_source, base_url)
            if not href:
                continue
            parent = anchor.find_parent(["li", "tr", "article", "div"]) or anchor
            text = clean_text(parent.get_text(" "))
            if len(title) >= 8 and any(k in f"{title} {text}" for k in ["지원", "공고", "모집", "사업", "창업", "콘텐츠", "AI", "디자인"]):
                candidates.append({"title": title, "url": href, "text": text})
                anchor_titles.append(title)

        page_text = clean_text(soup.get_text(" "))
        for match in self.split_text_candidates(page_text):
            title = match["title"]
            # 텍스트 폴백은 진짜 링크가 없어 base_url(목록 페이지)을 그대로 쓴다.
            # 같은 공고를 앵커 스캔이 이미 '진짜 상세 링크'로 잡아뒀다면 이 목록URL짜리
            # 중복을 버린다 — 안 그러면 같은 공고가 정상 링크 버전과 목록URL 버전 둘로
            # 쪼개져 저장된다. 앵커 제목엔 보통 "분류 D-일 마감일자 ... " 접두어가 붙어
            # 단순 접두어 비교로는 못 잡으므로, 텍스트 폴백 제목 앞부분이 앵커 제목 어딘가에
            # 그대로 들어있는지(부분 문자열 포함)로 판단한다.
            core = title[:18]
            if len(core) >= 8 and any(core in at for at in anchor_titles):
                continue
            candidates.append({"title": title, "url": base_url, "text": match["text"]})
        deduped = []
        seen = set()
        for item in candidates:
            key = (item["title"], item["url"])
            if key not in seen:
                deduped.append(item)
                seen.add(key)
        return deduped

    def normalize_url(self, href: str, base_url: str) -> str:
        href = (href or "").strip()
        # onclick에서 넘어온 텍스트(예: "fn_project_detail('PROJECT_00004885'); return false;")는
        # "javascript:" 접두사가 없어 아래 startswith 분기들을 안 타므로 먼저 따로 처리한다.
        if "fn_project_detail(" in href:
            match = re.search(r"fn_project_detail\('([^']+)'\)", href)
            if match and "startup.daegu.go.kr" in base_url:
                return (
                    "https://startup.daegu.go.kr/index.do?menu_id=00002552"
                    f"&menu_link=/front/project/projectFrontDetail.do?project_id={match.group(1)}"
                )
            return ""
        if href.lower().startswith("javascript:read"):
            match = re.search(r"read\('[^']*','?(\d+)'?\)", href)
            if match and "dip.or.kr" in base_url:
                return (
                    "https://www.dip.or.kr/home/notice/businessbbs/boardRead.ubs?"
                    f"fboardcd=business&fboardnum={match.group(1)}&sfpage=1&sfpsize=10&sfsearch=ftitle"
                )
        if href.lower().startswith("javascript:go_view"):
            # go_view(id)/go_view_blank(id) 둘 다 매치. 실제 사이트 JS(go_view 함수)는
            # schM=view를 pbancSn과 함께 넣어야 상세화면으로 간다. schM 없이 pbancSn만
            # 붙이면 목록 페이지(모집중)가 그대로 뜬다 — 예전엔 이 파라미터가 빠져 있었음.
            match = re.search(r"go_view(?:_blank)?\((\d+)\)", href)
            if match and "k-startup.go.kr" in base_url:
                return (
                    "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
                    f"?schM=view&pbancSn={match.group(1)}"
                )
        if href.lower().startswith("javascript:fn_golinkview"):
            match = re.search(r"fn_goLinkView\('([^']+)'", href)
            if match and "daegu.go.kr" in base_url:
                return f"https://www.daegu.go.kr/index.do?menu_id=00940170&gosiId={match.group(1)}"
        if href.lower().startswith("javascript:"):
            return ""
        return urljoin(base_url, href)

    def split_text_candidates(self, text: str) -> list[dict[str, str]]:
        text = clean_text(text)
        chunks: list[dict[str, str]] = []
        categories = r"(?:사업화|창업교육|시설공간|시설·공간·보육|행사\s*네트워크|행사ㆍ네트워크|판로ㆍ해외진출|정책자금|공모전|글로벌|멘토링ㆍ컨설팅ㆍ교육|인력)"
        patterns = [
            rf"({categories}\s+(?:D[-+]\d+\s+)?(?:마감일자\s+\d{{4}}-\d{{2}}-\d{{2}}\s+)?(.{{8,120}}?)\s+(?:기관명|등록일자|조회|창업진흥원|대구스케일업허브))",
            r"(게시판 목록\s+진행중\s+(.{8,120}?)\s+(?:D[-+]\d+\s+)?\d{3,6}\s+DIP\s+사업\s+\d{4}-\d{2}-\d{2}\s+~\s+\d{4}-\d{2}-\d{2})",
            r"(고시 공고\s+-\s+사업\s+(.{8,120}?)\s+\d{4}-\d{2}-\d{2})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                raw = clean_text(match.group(1))
                title = clean_text(match.group(2))
                if self.is_navigation_title(title):
                    continue
                chunks.append({"title": title, "text": raw})
        return chunks[:60]

    def is_navigation_title(self, title: str) -> bool:
        banned = {"개인정보처리방침", "이용약관", "사이트맵", "로그인", "회원가입", "검색", "처음", "이전", "다음", "마지막"}
        noisy = ["본문 바로가기", "로그아웃 안내", "전체메뉴", "누리집", "화면확대", "찾아오시는 길"]
        generic = ["콘텐츠 산업 육성", "대구콘텐츠코리아랩", "대구콘텐츠기업지원센터", "대구콘텐츠비즈니스센터", "대구메타버스지원센터"]
        return (
            title in banned
            or title in generic
            or title.startswith("Image:")
            or any(token in title for token in noisy)
            or len(title) > 150
        )

    def make_opportunity(
        self,
        source: Source,
        title: str,
        url: str,
        text: str,
        today: date,
        posted_date: str = "",
    ) -> Opportunity:
        amount_text, amount_value = parse_money_value(text)
        amount_text = format_amount_summary(amount_text, amount_value, text)
        deadline_date = extract_deadline(text, today)
        posted = posted_date or (extract_posted_date(text, today).isoformat() if extract_posted_date(text, today) else "")
        deadline = deadline_date.isoformat() if deadline_date else ""
        region = extract_region(text)
        target = extract_target(text)
        summary = summarize(text)
        classified = classify(title, summary, region, target, amount_value, deadline_date, self.minimum_amount, today)
        return Opportunity(
            org=source.org or source.name,
            title=title,
            url=url,
            posted_date=posted,
            deadline=deadline,
            d_day=calculate_dday(deadline_date, today),
            amount_text=amount_text or "확인 필요",
            amount_value=amount_value,
            region=region or "확인 필요",
            target=target or "확인 필요",
            keywords=classified.keywords,
            summary=summary,
            score=classified.score,
            status=classified.status_hint,
            priority=classified.priority,
            relevance=classified.relevance,
            eligibility=classified.eligibility,
            next_action=classified.next_action,
            source_id=source.id,
        )
