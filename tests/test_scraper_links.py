"""
'기관 공고 사이트 열기'가 목록 페이지로 가버리던 버그의 회귀 테스트.

실제 사이트(k-startup.go.kr, startup.daegu.go.kr)에서 실측 검증한 URL 패턴을
오프라인으로 고정한다. 네트워크 호출 없음 — normalize_url/extract_candidate_blocks는
순수 문자열/HTML 파싱 함수라 Scraper 생성자에 아무 인자나 넣어도 된다.
"""

from bs4 import BeautifulSoup

from daegu_grants.scraper import Scraper


def _scraper() -> Scraper:
    return Scraper({"request_delay_seconds": 0, "timeout_seconds": 5, "detail_fetch_limit_per_source": 0})


def test_kstartup_go_view_includes_schM_view():
    # 실사이트 JS: go_view(id)는 schM=view + pbancSn을 같이 넣어야 상세화면이 뜬다.
    # schM 없이 pbancSn만 있으면 '모집중' 목록 페이지가 그대로 뜬다(실측 확인됨).
    s = _scraper()
    url = s.normalize_url(
        "javascript:go_view(178401)", "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
    )
    assert "schM=view" in url
    assert "pbancSn=178401" in url


def test_kstartup_go_view_blank_also_includes_schM_view():
    s = _scraper()
    url = s.normalize_url(
        "javascript:go_view_blank(178419)", "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
    )
    assert "schM=view" in url
    assert "pbancSn=178419" in url


def test_dash_daegu_onclick_project_detail():
    # startup.daegu.go.kr은 href가 아니라 onclick 속성에 실제 상세글 ID가 있다.
    s = _scraper()
    url = s.normalize_url(
        "fn_project_detail('PROJECT_00004885'); return false;",
        "https://startup.daegu.go.kr/index.do?menu_id=00002552",
    )
    assert "project_id=PROJECT_00004885" in url
    assert "projectFrontDetail" in url


def test_dip_or_kr_read_pattern_unaffected():
    # 기존에 이미 맞던 패턴이 이번 변경으로 안 깨졌는지 회귀 확인.
    s = _scraper()
    url = s.normalize_url("javascript:read('a','9088')", "https://www.dip.or.kr/home/notice/list")
    assert url == (
        "https://www.dip.or.kr/home/notice/businessbbs/boardRead.ubs?"
        "fboardcd=business&fboardnum=9088&sfpage=1&sfpsize=10&sfsearch=ftitle"
    )


def test_daegu_go_kr_fn_golinkview_unaffected():
    s = _scraper()
    url = s.normalize_url("javascript:fn_goLinkView('12345')", "https://www.daegu.go.kr/index.do")
    assert url == "https://www.daegu.go.kr/index.do?menu_id=00940170&gosiId=12345"


def test_extract_candidate_blocks_onclick_placeholder_href_falls_back_to_onclick():
    # href="javascript:;" + onclick="fn_project_detail(...)" 조합에서 진짜 링크를 뽑아내는지.
    html = """
    <html><body>
      <a href="javascript:;" onclick="fn_project_detail('PROJECT_00004900'); return false;">
        2026년 창업기업 모집 통합공고
      </a>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    s = _scraper()
    candidates = s.extract_candidate_blocks(soup, "https://startup.daegu.go.kr/index.do?menu_id=00002552")
    urls = [c["url"] for c in candidates if "창업기업 모집 통합공고" in c["title"]]
    assert urls, "onclick 기반 후보를 못 뽑음"
    assert "project_id=PROJECT_00004900" in urls[0]


def test_text_fallback_duplicate_of_anchor_is_suppressed():
    # 앵커로 이미 '진짜 링크'가 잡힌 공고가, 접두어 붙은 텍스트 폴백으로 목록URL 버전
    # 하나 더 생기던 버그(같은 공고가 두 행으로 쪼개짐)의 회귀 테스트.
    base_url = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
    html = f"""
    <html><body>
      <div>
        <a href="javascript:go_view_blank(178380)">
          2026년 지역 첨단제조 스타트업 스케일업 지원사업 창업기업 모집공고
        </a>
      </div>
      <div>
        사업화 D-18 마감일자 2026-07-24
        2026년 지역 첨단제조 스타트업 스케일업 지원사업 창업기업 모집공고
        기관명 창업진흥원
      </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    s = _scraper()
    s.split_text_candidates = lambda text: [
        {
            "title": "2026년 지역 첨단제조 스타트업 스케일업 지원사업 창업기업 모집공고 기관명 창업진흥원",
            "text": text,
        }
    ]
    candidates = s.extract_candidate_blocks(soup, base_url)
    list_url_dupes = [c for c in candidates if c["url"] == base_url]
    assert not list_url_dupes, "앵커로 이미 잡힌 공고가 목록URL 버전으로 중복 생성됨"
