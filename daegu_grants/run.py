from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from . import classifier
from .draft_generator import generate_drafts
from .github_issues import create_issues
from .notifier import build_email_subject, build_email_text, build_message, send_email, send_telegram
from .report import build_html_report, build_report, write_reports
from .scraper import Scraper
from .sources import load_config
from .storage import apply_seen_status, deduplicate, ensure_dirs, load_seen, save_csv, save_seen, update_seen
from .supabase_sync import upsert_programs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="대구 정부지원사업 모니터링 자동화")
    parser.add_argument("--sources", default="sources.yaml", help="sources.yaml 경로")
    parser.add_argument("--dry-run", action="store_true", help="Issue/Telegram 전송 없이 수집과 보고서 생성만 수행")
    parser.add_argument("--no-update-seen", action="store_true", help="seen.json 업데이트 생략")
    parser.add_argument("--min-amount", type=int, help="high_priority 기준 최소 지원금(원)")
    parser.add_argument("--region", help="우선 모니터링 지역. 예: 대구")
    parser.add_argument("--keywords", help="쉼표로 구분한 관련 키워드 목록")
    return parser.parse_args()


def parse_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def apply_cli_overrides(settings: dict, args: argparse.Namespace) -> None:
    if args.min_amount:
        settings["minimum_amount_krw"] = args.min_amount
    if args.region:
        settings["preferred_region"] = args.region
    keywords = parse_keywords(args.keywords)
    if keywords:
        classifier.RELEVANCE_KEYWORDS[:] = list(dict.fromkeys(keywords))


def main() -> None:
    args = parse_args()
    ensure_dirs()
    settings, sources = load_config(args.sources)
    apply_cli_overrides(settings, args)
    tz = ZoneInfo(settings.get("timezone", "Asia/Seoul"))
    today = datetime.now(tz).date()

    scraper = Scraper(settings)
    raw, errors = scraper.scrape(sources, today=today)
    opportunities = apply_seen_status(deduplicate(raw), load_seen())

    draft_paths = generate_drafts(opportunities, today=today)
    markdown = build_report(opportunities, errors, today=today)
    html = build_html_report(opportunities, errors, today=today)
    dated_report, latest_report, dated_html, latest_html = write_reports(markdown, html, today=today)
    save_csv(opportunities)
    upserted = upsert_programs(opportunities)

    issue_urls = create_issues(opportunities, draft_paths, dry_run=args.dry_run)
    message = build_message(opportunities)
    telegram_sent = send_telegram(message, dry_run=args.dry_run)
    email_sent = send_email(build_email_subject(opportunities), html, build_email_text(opportunities), dry_run=args.dry_run)

    if not args.dry_run and not args.no_update_seen:
        save_seen(update_seen(opportunities, load_seen()))
    elif args.dry_run and not args.no_update_seen:
        # Dry-runs should be repeatable and should not suppress the next real alert.
        pass

    print(f"opportunities={len(opportunities)}")
    print(f"supabase_upserted={upserted}")
    print(f"report={dated_report}")
    print(f"latest={latest_report}")
    print(f"html={dated_html}")
    print(f"latest_html={latest_html}")
    print(f"drafts={len(draft_paths)}")
    print(f"errors={len(errors)}")
    if args.dry_run:
        print("dry_run=true; skipped GitHub Issue and Telegram notification")
    else:
        print(f"github_issues={len(issue_urls)}")
        print(f"telegram_sent={telegram_sent}")
        print(f"email_sent={email_sent}")


if __name__ == "__main__":
    main()
