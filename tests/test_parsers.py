from datetime import date

from daegu_grants.parsers import (
    calculate_dday,
    extract_deadline,
    extract_region,
    extract_target,
    format_amount_summary,
    normalize_opportunity_title,
    parse_money_value,
    parse_selection_count,
)


def test_parse_money_억원():
    text, value = parse_money_value("기업당 최대 1.5억원 지원")
    assert text == "1.5억원"
    assert value == 150_000_000


def test_parse_money_백만원():
    _, value = parse_money_value("지원규모 기업당 25백만원 이내")
    assert value == 25_000_000


def test_parse_money_spaced_korean_units():
    text, value = parse_money_value("기업당 최대 5천만 원, 총사업비 20,000천원")
    assert text == "5천만 원"
    assert value == 50_000_000


def test_amount_summary_divides_total_by_selection_count():
    body = "총사업비 2억원, 선정규모 4개사"
    text, value = parse_money_value(body)
    assert parse_selection_count(body) == ("4개사", 4)
    assert format_amount_summary(text, value, body) == "총 2억원 / 선정 4개사 / 기업당 약 5천만원"


def test_extract_target_business_age_and_industry():
    target = extract_target("창업 7년 이내 신규창업 제조업 및 도소매업 소상공인 대상")
    assert "창업 7년 이하" in target
    assert "신규창업" in target
    assert "제조업" in target
    assert "도소매업" in target
    assert "소상공인" in target


def test_extract_region_prefers_yeongnam_regions():
    assert extract_region("부산테크노파크 2026년 기업 지원사업 공고") == "부산"
    assert extract_region("경상북도 구미시 중소기업 지원사업") == "경북"
    assert extract_region("경남 하동군청 소상공인 지원 공고") == "경남"
    assert extract_region("대구 소재 창업기업 모집") == "대구"


def test_extract_deadline_full_date():
    assert extract_deadline("신청기간 2026-05-01 ~ 2026-06-12", date(2026, 6, 2)) == date(2026, 6, 12)


def test_calculate_dday():
    assert calculate_dday(date(2026, 6, 12), date(2026, 6, 2)) == "D-10"


def test_normalize_opportunity_title():
    left = "사업화 D-10 2026년도 창업패키지(AI 인재 실증형) 창업기업 모집공고 창업진흥원 등록일자 2026-05-18 마감일자 2026-06-12 조회 281"
    right = "2026년도 창업패키지(AI 인재 실증형) 창업기업 모집공고"
    assert normalize_opportunity_title(left) == right
