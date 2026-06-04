from __future__ import annotations

import os
import re
import time
import urllib.robotparser
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

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


class Scraper:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.session = requests.Session()
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
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(urljoin(base, "/robots.txt"))
            try:
                rp.read()
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
        for source in sources:
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
        for item in items[:100]:
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
        for anchor in soup.find_all("a", href=True):
            title = clean_text(anchor.get_text(" "))
            href = self.normalize_url(anchor["href"], base_url)
            if not href:
                continue
            parent = anchor.find_parent(["li", "tr", "article", "div"]) or anchor
            text = clean_text(parent.get_text(" "))
            if len(title) >= 8 and any(k in f"{title} {text}" for k in ["지원", "공고", "모집", "사업", "창업", "콘텐츠", "AI", "디자인"]):
                candidates.append({"title": title, "url": href, "text": text})

        page_text = clean_text(soup.get_text(" "))
        for match in self.split_text_candidates(page_text):
            candidates.append({"title": match["title"], "url": base_url, "text": match["text"]})
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
        if href.lower().startswith("javascript:read"):
            match = re.search(r"read\('[^']*','?(\d+)'?\)", href)
            if match and "dip.or.kr" in base_url:
                return (
                    "https://www.dip.or.kr/home/notice/businessbbs/boardRead.ubs?"
                    f"fboardcd=business&fboardnum={match.group(1)}&sfpage=1&sfpsize=10&sfsearch=ftitle"
                )
        if href.lower().startswith("javascript:go_view"):
            match = re.search(r"go_view\((\d+)\)", href)
            if match and "k-startup.go.kr" in base_url:
                return f"https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?pbancSn={match.group(1)}"
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
