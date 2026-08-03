"""제목 정리·차단 회귀 테스트.

배경: 같은 공고인데 목록의 D-day가 매일 바뀌면서 제목이 달라지고, Supabase 행
id가 제목 해시 기반이라 같은 공고가 날마다 새 행으로 쌓였다(공모전 하나가 15개
변형으로 적재된 사례). 제목을 안정화해 그 원인을 없앤 것을 고정한다.
"""

from daegu_grants.parsers import clean_listing_title, is_garbled_title


def test_same_notice_with_different_dday_converges_to_one_title():
    """D-day·등록일자만 다른 같은 공고는 동일 제목으로 수렴해야 한다."""
    variants = [
        "공모전 D-58 마감일자 2026-08-06 2026년『제6회 대구 여성창업스타전』 공고 달구벌여성인력개발센터",
        "공모전 D-60 2026년『제6회 대구 여성창업스타전』 공고 달구벌여성인력개발센터 등록일자 2026",
        "공모전 D-63 2026년『제6회 대구 여성창업스타전』 공고 달구벌여성인력개발센터 등록일자 2026",
    ]
    cleaned = {clean_listing_title(v) for v in variants}
    assert len(cleaned) == 1, f"변형이 하나로 수렴하지 않음: {cleaned}"
    assert "여성창업스타전" in cleaned.pop()


def test_strips_list_row_metadata():
    cases = [
        ("1462 내수 [경북] 2026년 미래 전략 산업혁신 투자포럼 참가기업 모집 공고",
         "[경북] 2026년 미래 전략 산업혁신 투자포럼 참가기업 모집 공고"),
        ("새글 울산광역시여성회관 2026년 3학기 수강생 모집",
         "울산광역시여성회관 2026년 3학기 수강생 모집"),
        ("멘토링 컨설팅 2026년 투자유치를 위한 역량강화지원 참여기업 모집공고 마감 46일전",
         "2026년 투자유치를 위한 역량강화지원 참여기업 모집공고"),
        ("대구특구 이노폴리스캠퍼스지원사업 - 다이나믹이노베이터 10기 새로운게시글",
         "대구특구 이노폴리스캠퍼스지원사업 - 다이나믹이노베이터 10기"),
    ]
    for raw, expected in cases:
        assert clean_listing_title(raw) == expected, f"{raw!r} -> {clean_listing_title(raw)!r}"


def test_normal_title_unchanged():
    """정상 제목은 손대지 않는다(과잉 삭제 방지)."""
    for title in [
        "2026년 소상공인 온라인 판로지원사업",
        "대구 소상공인 특례보증 (저금리 운영자금)",
        "「2026년 경상북도 건축분야 건설공사」 안전점검 수행기관 모집 공고",
    ]:
        assert clean_listing_title(title) == title


def test_over_stripping_falls_back_to_original():
    """정리 후 너무 짧아지면 원문을 유지한다."""
    assert clean_listing_title("공모전 D-58") == "공모전 D-58"


def test_site_guide_text_is_blocked():
    """사이트 안내 문구가 제목으로 잡힌 것은 공고가 아니므로 차단."""
    for title in [
        "사업공고 필요한 지원사업을 찾아보세요.",
        "입주신청 입주공고(공실현황)를 확인하고 신청하세요.",
        "홈페이지 GBTP 메인화면으로 이동합니다. 바로가기",
    ]:
        assert is_garbled_title(title), title


def test_agency_recruitment_is_blocked():
    """기관 자체 채용 공고는 사업자 지원이 아니므로 차단."""
    for title in [
        "울산테크노파크 직원(위촉직) 채용 공고(제2026-008호)",
        "울산테크노파크 직원(청년인턴) 채용 공고 서류전형 결과 및 면접전형 안내",
        "임직원 친인척 채용 공개",
    ]:
        assert is_garbled_title(title), title


def test_real_notices_not_blocked():
    """진짜 공고는 차단되면 안 된다."""
    for title in [
        "2026년 소상공인 온라인 판로지원사업",
        "2026년 대구콘텐츠기업지원센터 콘텐츠 제작지원 사업 모집 공고",
        "「2026년 경상북도 건축분야 건설공사」 안전점검 수행기관 모집 공고",
    ]:
        assert not is_garbled_title(title), title
