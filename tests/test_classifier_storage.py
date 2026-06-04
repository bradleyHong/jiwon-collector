from datetime import date

from daegu_grants.classifier import classify
from daegu_grants.storage import Opportunity, deduplicate


def test_classifier_high_priority():
    result = classify(
        "대구 AI 영상 콘텐츠 제작지원 공고",
        "대구 소재 콘텐츠기업 대상",
        "대구",
        "콘텐츠기업",
        50_000_000,
        date(2026, 6, 10),
        today=date(2026, 6, 2),
    )
    assert result.priority == "high_priority"
    assert result.score >= 70


def test_classifier_needs_review_for_promising_unknown_amount():
    result = classify(
        "여성창업 사업화지원사업 모집",
        "지원금 규모는 공고문 확인 필요",
        "대구",
        "여성기업",
        None,
        date(2026, 6, 20),
        today=date(2026, 6, 2),
    )
    assert result.priority == "needs_review"


def test_classifier_alerts_policy_loan_large_budget():
    result = classify(
        "중소기업 정책자금 융자계획 공고",
        "전국 중소기업 대상 융자 지원. 주변 메뉴: 디지털콘텐츠 사업화",
        "전국",
        "중소기업",
        3_670_000_000_000,
        None,
        today=date(2026, 6, 2),
    )
    assert result.priority == "high_priority"


def test_classifier_does_not_alert_unrelated_public_works_bid():
    result = classify(
        "하수관로정비 BTL사업 제3자 제안 재공고",
        "대구 시설 공사 입찰 공고",
        "대구",
        "일반기업",
        3_670_000_000,
        None,
        today=date(2026, 6, 2),
    )
    assert result.priority == "normal"
    assert result.score < 40


def test_deduplicate_keeps_higher_score():
    low = Opportunity(org="A", title="같은 공고", url="https://example.com/1", deadline="2026-06-30", score=10)
    high = Opportunity(org="A", title="같은 공고", url="https://example.com/1", deadline="2026-06-30", score=90)
    result = deduplicate([low, high])
    assert len(result) == 1
    assert result[0].score == 90
