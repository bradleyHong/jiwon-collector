from __future__ import annotations

from datetime import date
import hashlib
from html import escape
import json
from pathlib import Path
import re

from .parsers import normalize_opportunity_title, read_text_file
from .storage import Opportunity


def report_priority(opp: Opportunity) -> str:
    if opp.priority == "high_priority":
        return "높음"
    if opp.priority == "needs_review" or opp.status == "needs_review":
        return "검토"
    return "보통"


def markdown_link(label: str, url: str) -> str:
    return f"[{label}]({url})" if url else label


def visible_opportunities(opportunities: list[Opportunity]) -> list[Opportunity]:
    return unique_for_display(
        [opp for opp in opportunities if opp.status != "expired" and opp.score >= 40 and len(opp.title) <= 150]
    )


def build_report(opportunities: list[Opportunity], errors: list[str], today: date | None = None) -> str:
    today = today or date.today()
    visible = visible_opportunities(opportunities)
    rows = [
        "# 대구 정부지원사업 모니터링",
        "",
        f"- 실행일: {today.isoformat()}",
        f"- 후보 공고: {len(opportunities)}건",
        f"- 표시 공고: {len(visible)}건",
        "",
        "보기 좋은 HTML 리포트: `reports/latest.html`",
        "",
        "| 추천 | 기관 | 사업명 | 지원금 | 마감 | 관련성 | 다음 액션 |",
        "|---|---|---|---|---|---|---|",
    ]
    if not visible:
        rows.append("| - | - | 오늘은 조건에 맞는 신규 공고 없음 | - | - | - | - |")
    else:
        for opp in visible[:30]:
            rows.append(
                "| {priority} | {org} | {title} | {amount} | {deadline} {dday} | {rel} | {action} |".format(
                    priority=report_priority(opp),
                    org=escape_md(opp.org),
                    title=markdown_link(escape_md(short_title(opp.title, 72)), opp.url),
                    amount=escape_md(opp.amount_text),
                    deadline=opp.deadline or "확인 필요",
                    dday=opp.d_day or "",
                    rel=opp.relevance or "확인 필요",
                    action=escape_md(opp.next_action),
                )
            )
    if errors:
        rows.extend(["", "## Source Errors", ""])
        for error in errors:
            rows.append(f"- {escape_md(error)}")
    return "\n".join(rows) + "\n"


def escape_md(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")


def short_title(value: str, max_len: int = 96) -> str:
    value = (value or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


def build_html_report(opportunities: list[Opportunity], errors: list[str], today: date | None = None) -> str:
    today = today or date.today()
    visible = visible_opportunities(opportunities)
    company_keywords = load_company_keywords()
    company_info = load_company_info()
    company_conditions = load_company_conditions()
    fresh = [opp for opp in visible if opp.status in {"new", "updated"}]
    hot = [opp for opp in visible if opp.priority in {"high_priority", "needs_review"} or opp.status == "needs_review"]
    urgent = [opp for opp in visible if opp.d_day and opp.d_day.startswith("D-") and _dday_number(opp.d_day) <= 7]
    fresh_cards = "\n".join(build_card(opp) for opp in fresh[:3]) or empty_state_html("새로 올라온 공고가 없습니다.")
    cards = "\n".join(build_card(opp) for opp in visible[:3]) or empty_state_html()
    table_rows = "\n".join(build_table_row(opp) for opp in visible[:40]) or (
        '<tr><td colspan="8" class="empty">오늘은 조건에 맞는 신규 공고 없음</td></tr>'
    )
    details_json = json.dumps([opportunity_detail_payload(opp) for opp in visible[:80]], ensure_ascii=False).replace(
        "</", "<\\/"
    )
    keyword_buttons = "".join(
        f'<button type="button" data-text="{escape(keyword)}">{escape(keyword)}</button>' for keyword in company_keywords
    )
    errors_html = ""
    if errors:
        errors_html = (
            '<section class="panel muted"><h2>수집 오류</h2><ul class="errors">'
            + "".join(f"<li>{escape(error)}</li>" for error in errors)
            + "</ul></section>"
        )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>대구 정부지원사업 모니터링</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #64748b;
      --line: #e5e7eb;
      --blue: #2563eb;
      --blue-soft: #eaf2ff;
      --green: #047857;
      --green-soft: #e9f8f1;
      --amber: #b45309;
      --amber-soft: #fff4df;
      --red: #b42318;
      --red-soft: #ffe9e7;
      --shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
      line-height: 1.55;
    }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-end;
      margin-bottom: 18px;
    }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; word-break: keep-all; overflow-wrap: break-word; }}
    .subtitle {{ margin: 6px 0 0; color: var(--muted); font-size: 14px; }}
    .company-tools {{
      margin-top: 14px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .company-tools span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-right: 2px;
    }}
    .company-tools button {{
      border: 1px solid #cbd5e1;
      background: #ffffff;
      color: #334155;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }}
    .company-profile-panel {{
      margin-top: 14px;
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .company-profile-panel summary {{
      cursor: pointer;
      list-style: none;
      padding: 12px 14px;
      font-weight: 900;
      color: #334155;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }}
    .company-profile-panel summary::-webkit-details-marker {{ display: none; }}
    .company-profile-panel summary span {{ color: var(--muted); font-size: 12px; font-weight: 700; }}
    .condition-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 0 14px 14px;
    }}
    .condition-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .condition-card h3 {{ margin: 0 0 8px; font-size: 13px; }}
    .condition-card ul {{ margin: 0; padding-left: 17px; color: #475569; font-size: 12px; }}
    .condition-card li + li {{ margin-top: 5px; }}
    .run-date {{ color: var(--muted); font-size: 14px; white-space: nowrap; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 18px 0 22px;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
    }}
    .stat strong {{ display: block; font-size: 24px; line-height: 1.1; }}
    .stat span {{ display: block; margin-top: 5px; color: var(--muted); font-size: 13px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
      overflow: hidden;
    }}
    .panel.fresh {{
      border-color: #99f6e4;
      background: linear-gradient(180deg, #f0fdfa 0%, #ffffff 80%);
    }}
    .panel.fresh .panel-head {{
      background: #ccfbf1;
      border-bottom-color: #99f6e4;
    }}
    .fresh-label {{
      color: #0f766e;
      background: #ffffff;
      border: 1px solid #5eead4;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 800;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 20px;
      border-bottom: 1px solid var(--line);
      align-items: center;
    }}
    h2 {{ margin: 0; font-size: 18px; word-break: keep-all; }}
    .hint {{ color: var(--muted); font-size: 13px; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; padding: 16px; }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-height: 220px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .js-filter-item.is-hidden {{ display: none; }}
    .js-filter-item {{
      animation: resultIn 360ms cubic-bezier(.2,.75,.25,1) both;
      will-change: transform, opacity;
    }}
    body.has-filter .js-filter-item:not(.is-hidden) {{
      animation-name: resultFlow;
    }}
    @keyframes resultIn {{
      from {{ opacity: 0; transform: translateY(10px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes resultFlow {{
      from {{ opacity: 0; transform: translateY(18px) scale(.985); }}
      to {{ opacity: 1; transform: translateY(0) scale(1); }}
    }}
    .badges {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .b-high {{ color: var(--red); background: var(--red-soft); }}
    .b-review {{ color: var(--amber); background: var(--amber-soft); }}
    .b-normal {{ color: var(--blue); background: var(--blue-soft); }}
    .b-new {{ color: var(--green); background: var(--green-soft); }}
    .d-chip {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .d-urgent {{ color: var(--red); background: var(--red-soft); }}
    .d-normal {{ color: var(--blue); background: var(--blue-soft); }}
    .d-muted {{ color: var(--muted); background: #f1f5f9; }}
    .card h3 {{ margin: 0; font-size: 16px; line-height: 1.45; word-break: keep-all; overflow-wrap: break-word; }}
    .meta {{ color: var(--muted); font-size: 13px; }}
    .facts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .fact {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      background: #fbfcfe;
      min-height: 58px;
    }}
    .fact.strong {{ background: #eff6ff; border-color: #bfdbfe; }}
    .fact.warn {{ background: #fff7ed; border-color: #fed7aa; }}
    .fact-label {{ display: block; color: var(--muted); font-size: 11px; font-weight: 800; }}
    .fact-value {{ display: block; margin-top: 3px; color: var(--text); font-size: 13px; font-weight: 800; line-height: 1.35; }}
    .chip-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .mini-chip {{
      border: 1px solid var(--line);
      background: #ffffff;
      color: #475569;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
    }}
    .summary {{ color: #334155; font-size: 13px; margin: 0; }}
    .actions {{ margin-top: auto; display: flex; gap: 8px; flex-wrap: wrap; }}
    a.button,
    button.button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      border: 0;
      border-radius: 6px;
      padding: 7px 11px;
      color: #ffffff;
      background: var(--blue);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      font-family: inherit;
    }}
    .button.secondary {{ color: #1f2933; background: #f1f5f9; border: 1px solid #dbe3ee; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 920px; }}
    th {{
      text-align: left;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
      white-space: nowrap;
    }}
    td {{
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      font-size: 14px;
    }}
    .title-cell {{ min-width: 360px; }}
    .title-button {{
      border: 0;
      background: transparent;
      color: var(--text);
      text-align: left;
      padding: 0;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      line-height: 1.45;
    }}
    .title-button:hover {{ color: var(--blue); }}
    .org {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .deadline {{ white-space: nowrap; font-weight: 700; }}
    .money {{ white-space: nowrap; }}
    .next {{ color: #334155; max-width: 150px; }}
    .filters {{
      padding: 16px;
    }}
    .filter-grid {{
      display: grid;
      grid-template-columns: 180px minmax(220px, 1fr) auto;
      gap: 10px;
      align-items: end;
    }}
    .filter-field label {{ display: block; color: var(--muted); font-size: 12px; font-weight: 800; margin-bottom: 5px; }}
    .filter-field input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 40px;
      padding: 8px 10px;
      font-size: 14px;
      background: #ffffff;
    }}
    .quick-filters {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .quick-filters button {{
      border: 1px solid #bfdbfe;
      background: var(--blue-soft);
      color: #1d4ed8;
      border-radius: 999px;
      padding: 8px 10px;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }}
    #filter-count {{ color: var(--muted); font-size: 13px; margin-top: 10px; }}
    .muted {{ box-shadow: none; }}
    .muted h2 {{ padding: 18px 20px 0; }}
    .errors {{ margin: 10px 20px 18px; padding-left: 18px; color: var(--muted); font-size: 13px; }}
    .empty {{ color: var(--muted); text-align: center; padding: 28px; }}
    footer {{
      margin-top: 26px;
      color: var(--muted);
      font-size: 13px;
    }}
    .company-footer {{
      display: grid;
      grid-template-columns: 1.2fr 2fr;
      gap: 16px;
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px 20px;
    }}
    .company-footer strong {{ display: block; color: var(--text); font-size: 16px; margin-bottom: 6px; }}
    .company-lines {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 18px; }}
    .company-line b {{ color: #475569; margin-right: 6px; }}
    .service-note {{
      margin-top: 10px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
    }}
    /* Startup UI refresh */
    body {{ background: #eef2f7; }}
    .wrap {{ max-width: 1280px; padding: 18px 24px 52px; }}
    header.hero {{
      position: relative;
      overflow: hidden;
      min-height: 560px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 230px;
      align-items: flex-start;
      padding: 32px;
      background: #101827;
      border: 1px solid #263348;
      border-radius: 18px;
      color: #ffffff;
      box-shadow: 0 24px 70px rgba(15, 23, 42, 0.24);
    }}
    .media-canvas {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      opacity: .52;
      pointer-events: none;
    }}
    header.hero::before {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px),
        linear-gradient(180deg, rgba(255,255,255,.04) 1px, transparent 1px);
      background-size: 56px 56px;
      mask-image: linear-gradient(180deg, rgba(0,0,0,.9), rgba(0,0,0,.18));
      pointer-events: none;
    }}
    header.hero::after {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 42%;
      background: linear-gradient(180deg, transparent, rgba(16,24,39,.92));
      pointer-events: none;
    }}
    .hero-main, .hero-side {{ position: relative; z-index: 1; }}
    .hero-main {{ min-width: 0; max-width: 900px; }}
    .hero-side {{ width: 230px; display: grid; gap: 10px; justify-items: end; }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
      border-radius: 999px;
      padding: 5px 10px;
      color: #c7d2fe;
      font-size: 12px;
      font-weight: 900;
      margin-bottom: 12px;
    }}
    header.hero h1 {{ color: #ffffff; font-size: clamp(32px, 5vw, 58px); line-height: 1.06; max-width: 850px; word-break: keep-all; }}
    header.hero .subtitle {{ color: #d7deea; font-size: clamp(15px, 1.5vw, 18px); max-width: 760px; word-break: keep-all; }}
    header.hero .company-tools {{ margin-top: 18px; }}
    header.hero .company-tools span {{ color: #aab7cc; }}
    header.hero .company-tools button {{
      border-color: rgba(255,255,255,0.20);
      background: rgba(255,255,255,0.10);
      color: #ffffff;
      padding: 7px 11px;
    }}
    header.hero .company-tools button:hover {{ background: rgba(255,255,255,0.18); }}
    header.hero .company-profile-panel {{
      margin-top: 18px;
      background: rgba(255,255,255,0.06);
      border-color: rgba(255,255,255,0.14);
      border-radius: 14px;
    }}
    header.hero .company-profile-panel summary {{ color: #ffffff; }}
    header.hero .company-profile-panel summary span {{ color: #aab7cc; }}
    header.hero .condition-card {{
      border-color: rgba(255,255,255,0.12);
      background: rgba(255,255,255,0.08);
      border-radius: 12px;
    }}
    header.hero .condition-card h3 {{ color: #ffffff; }}
    header.hero .condition-card ul {{ color: #d7deea; }}
    .run-date {{
      color: #dbeafe;
      font-size: 13px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
      border-radius: 999px;
      padding: 7px 11px;
    }}
    .plan-card {{
      width: 100%;
      border: 1px solid rgba(255,255,255,0.16);
      background: rgba(255,255,255,0.10);
      border-radius: 14px;
      padding: 14px;
      color: #ffffff;
    }}
    .plan-card strong {{ display: block; font-size: 18px; line-height: 1; }}
    .plan-card span {{ display: block; margin-top: 6px; color: #cbd5e1; font-size: 12px; }}
    .stat, .panel, .card, .fact, .company-footer, .service-note {{ border-radius: 16px; }}
    .stat {{ padding: 18px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }}
    .panel {{ box-shadow: 0 18px 45px rgba(15, 23, 42, 0.10); }}
    .panel-head {{ padding: 18px 22px; }}
    .panel.fresh .panel-head {{ background: #d7fdf2; }}
    h2 {{ font-size: 19px; }}
    .card {{
      border-radius: 14px;
      transition: transform 140ms ease, box-shadow 140ms ease, border-color 140ms ease;
    }}
    .card:hover {{ border-color: #bfd0e7; box-shadow: 0 14px 35px rgba(15, 23, 42, 0.08); transform: translateY(-1px); }}
    .fact {{ border-radius: 12px; }}
    a.button, button.button {{ border-radius: 10px; background: #1f4ed8; }}
    .filters {{ padding: 18px; }}
    .filter-grid {{ grid-template-columns: 190px minmax(260px, 1fr) auto; gap: 12px; }}
    .filter-field input {{ border-radius: 12px; min-height: 44px; padding: 9px 12px; }}
    .quick-filters button {{ padding: 10px 12px; }}
    .business-search {{
      margin: 26px 0 18px;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
      max-width: 850px;
    }}
    .business-search-head {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 14px;
    }}
    .business-search h2 {{ font-size: 18px; margin: 0; color: #ffffff; }}
    .business-search p {{ margin: 5px 0 0; color: #aab7cc; font-size: 14px; }}
    .chat-row {{
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 8px;
      padding: 8px;
      border: 1px solid rgba(255,255,255,0.22);
      border-radius: 22px;
      background: rgba(255,255,255,0.94);
      box-shadow: 0 22px 70px rgba(2, 6, 23, .34);
    }}
    #business-query {{
      width: 100%;
      min-height: 60px;
      border: 0;
      border-radius: 16px;
      padding: 13px 18px;
      font-size: 18px;
      outline: none;
      background: transparent;
      color: #101827;
    }}
    #business-query:focus {{ box-shadow: none; }}
    #business-search-button {{
      border: 0;
      border-radius: 16px;
      min-height: 60px;
      padding: 0 22px;
      background: #101827;
      color: #ffffff;
      font-size: 15px;
      font-weight: 900;
      cursor: pointer;
    }}
    #business-search-button:hover {{ background: #1f4ed8; }}
    .search-examples {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .search-examples button {{
      border: 1px solid rgba(255,255,255,.18);
      background: rgba(255,255,255,.09);
      color: #ffffff;
      border-radius: 999px;
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }}
    .search-examples button:hover {{ background: rgba(255,255,255,.17); }}
    #business-response {{
      margin-top: 12px;
      border-radius: 14px;
      padding: 12px 14px;
      background: rgba(17, 185, 129, .12);
      border: 1px solid rgba(94, 234, 212, .26);
      color: #d1fae5;
      font-size: 14px;
      font-weight: 800;
      display: none;
    }}
    .result-lane {{
      margin-top: 22px;
      position: relative;
      z-index: 2;
    }}
    .result-lane-head {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      margin: 0 0 14px;
      color: #334155;
    }}
    .result-lane-head h2 {{ font-size: 20px; }}
    .result-state {{
      color: #64748b;
      font-size: 13px;
      font-weight: 800;
    }}
    .followup-search {{
      margin: 18px 0;
      padding: 18px;
      border: 1px solid #dbe3ee;
      border-radius: 18px;
      background: #ffffff;
      box-shadow: 0 16px 42px rgba(15, 23, 42, 0.08);
    }}
    .followup-search h2 {{ font-size: 18px; }}
    .followup-search p {{ margin: 4px 0 14px; color: #64748b; font-size: 13px; }}
    .followup-row {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 8px;
    }}
    #followup-query {{
      width: 100%;
      min-height: 48px;
      border: 1px solid #cbd5e1;
      border-radius: 14px;
      padding: 11px 13px;
      font-size: 14px;
      outline: none;
    }}
    #followup-query:focus {{ border-color: #1f4ed8; box-shadow: 0 0 0 4px rgba(31,78,216,.11); }}
    #followup-search-button {{
      border: 0;
      border-radius: 14px;
      padding: 0 16px;
      background: #101827;
      color: #ffffff;
      font-weight: 900;
      cursor: pointer;
    }}
    #search-history {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    #search-history span {{
      border: 1px solid #dbe3ee;
      background: #f8fafc;
      color: #475569;
      border-radius: 999px;
      padding: 5px 8px;
      font-size: 12px;
      font-weight: 800;
    }}
    .ad-slot {{
      margin: 18px 0;
      border: 1px dashed #adc0d7;
      border-radius: 16px;
      min-height: 92px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #f8fafc;
      color: #64748b;
      font-size: 13px;
      font-weight: 800;
    }}
    .subscribe-cta {{
      margin: 28px 0 18px;
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(260px, 0.7fr);
      gap: 18px;
      padding: 24px;
      border-radius: 18px;
      background: #101827;
      color: #ffffff;
      box-shadow: 0 24px 70px rgba(15, 23, 42, 0.22);
    }}
    .subscribe-cta h2 {{ color: #ffffff; font-size: 24px; }}
    .subscribe-cta p {{ color: #cbd5e1; margin: 8px 0 0; }}
    .subscribe-list {{ margin: 16px 0 0; padding-left: 18px; color: #d7deea; }}
    .subscribe-price {{
      border: 1px solid rgba(255,255,255,0.16);
      background: rgba(255,255,255,0.10);
      border-radius: 16px;
      padding: 18px;
    }}
    .subscribe-price strong {{ display: block; font-size: 30px; line-height: 1; }}
    .subscribe-price span {{ display: block; margin-top: 8px; color: #cbd5e1; font-size: 13px; }}
    .subscribe-button {{
      display: inline-flex;
      justify-content: center;
      width: 100%;
      margin-top: 16px;
      border-radius: 12px;
      padding: 12px 14px;
      background: #ffffff;
      color: #101827;
      text-decoration: none;
      font-weight: 900;
    }}
    body.is-subscriber .ad-slot,
    body.is-subscriber .subscribe-cta {{ display: none; }}
    [hidden] {{ display: none !important; }}
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      z-index: 100;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(15, 23, 42, 0.62);
    }}
    .modal {{
      width: min(760px, 100%);
      max-height: min(760px, calc(100vh - 40px));
      overflow: auto;
      border-radius: 18px;
      background: #ffffff;
      box-shadow: 0 26px 90px rgba(15, 23, 42, 0.35);
    }}
    .modal-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      padding: 20px 22px 14px;
      border-bottom: 1px solid var(--line);
    }}
    .modal-head h2 {{ margin-top: 6px; font-size: 21px; line-height: 1.35; }}
    .modal-close {{
      flex: 0 0 auto;
      width: 34px;
      height: 34px;
      border: 1px solid #dbe3ee;
      border-radius: 999px;
      background: #ffffff;
      color: #334155;
      font-size: 20px;
      line-height: 1;
      cursor: pointer;
    }}
    .modal-body {{ padding: 18px 22px 22px; }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }}
    .detail-box {{
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 11px 12px;
      background: #fbfcfe;
    }}
    .detail-box b {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .detail-box span {{ display: block; color: var(--text); font-weight: 800; line-height: 1.4; }}
    .detail-summary {{
      margin: 0 0 16px;
      color: #334155;
      line-height: 1.65;
    }}
    .detail-url {{
      margin: 12px 0 0;
      padding: 10px 12px;
      border-radius: 12px;
      background: #f8fafc;
      color: #64748b;
      font-size: 12px;
      word-break: break-all;
    }}
    .copy-status {{ color: #047857; font-size: 12px; font-weight: 800; align-self: center; }}
    @media (max-width: 820px) {{
      .wrap {{ padding: 22px 12px 36px; }}
      header.hero {{ display: block; min-height: auto; padding: 20px; border-radius: 16px; }}
      .hero-side {{ width: auto; justify-items: start; margin-top: 16px; }}
      .run-date {{ margin-top: 8px; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .cards {{ grid-template-columns: 1fr; }}
      .filter-grid {{ grid-template-columns: 1fr; }}
      .company-footer {{ grid-template-columns: 1fr; }}
      .company-lines {{ grid-template-columns: 1fr; }}
      .condition-grid {{ grid-template-columns: 1fr; }}
      .chat-row {{ grid-template-columns: 1fr; }}
      .followup-row {{ grid-template-columns: 1fr; }}
      #business-query {{ font-size: 15px; min-height: 52px; }}
      #business-search-button {{ min-height: 48px; }}
      .subscribe-cta {{ grid-template-columns: 1fr; }}
      .result-lane {{ margin-top: 16px; }}
      h1 {{ font-size: 23px; }}
      .company-profile-panel summary {{ display: block; }}
      .company-profile-panel summary span {{ display: block; margin-top: 4px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <canvas class="media-canvas" id="media-canvas" aria-hidden="true"></canvas>
      <div class="hero-main">
        <div class="eyebrow">DAEGU GRANT OS · 상상연필 맞춤형</div>
        <h1>대구 정부지원사업 모니터링</h1>
        <p class="subtitle">회사 프로필과 관심 종목을 기준으로 대구 지원사업, 정책자금, 보증/대출 공고를 선별합니다.</p>
        <section class="business-search" aria-label="맞춤 공고 검색">
          <div class="business-search-head">
            <div>
              <h2>여러분의 사업은 어떤건가요?</h2>
              <p>문장으로 적으면 관련 업종, 지원규모, 정책자금 조건으로 결과가 정리됩니다.</p>
            </div>
          </div>
          <div class="chat-row">
            <input id="business-query" type="search" placeholder="예: 대구 수성구 꽃집인데 온라인 판매랑 소상공인 대출 지원금 찾고 싶어요">
            <button id="business-search-button" type="button">맞춤 공고 찾기</button>
          </div>
          <div class="search-examples">
            <button type="button" data-example="대구 제조공장인데 로봇 자동화와 정책자금이 필요해요">제조공장 로봇 자동화</button>
            <button type="button" data-example="대구 꽃집인데 온라인 판매, 도소매, 소상공인 대출 지원을 찾고 싶어요">꽃집 온라인 판매</button>
            <button type="button" data-example="미디어아트 전시 콘텐츠 제작지원 2천만원 이상을 찾고 있어요">미디어아트 전시</button>
          </div>
          <div id="business-response"></div>
        </section>
        <div class="company-tools">
          <span>우리 회사 관심 종목</span>
          {keyword_buttons}
        </div>
        {company_conditions_html(company_conditions)}
      </div>
      <div class="hero-side">
        <div class="run-date">실행일 {escape(today.isoformat())}</div>
        <div class="plan-card"><strong>Basic</strong><span>월 3만원 · 매일 9시 맞춤 메일</span></div>
      </div>
    </header>

    <main class="result-lane" id="results">
      <div class="result-lane-head">
        <h2>오늘의 지원사업 인덱스</h2>
        <div class="result-state" id="result-state">검색하면 아래 공고가 부드럽게 추려집니다.</div>
      </div>
    <div class="ad-slot" data-ad-slot>광고 영역 · 구독자는 광고 없이 이용합니다</div>

    <section class="stats">
      <div class="stat"><strong>{len(opportunities)}</strong><span>수집 후보</span></div>
      <div class="stat"><strong>{len(visible)}</strong><span>표시 공고</span></div>
      <div class="stat"><strong>{len(fresh)}</strong><span>새 공고</span></div>
      <div class="stat"><strong>{len(urgent)}</strong><span>7일 이내 마감</span></div>
    </section>

    <section class="panel filters">
      <div class="filter-grid">
        <div class="filter-field">
          <label for="filter-amount">최소 지원규모</label>
          <input id="filter-amount" type="number" min="0" step="1000000" placeholder="예: 20000000">
        </div>
        <div class="filter-field">
          <label for="filter-text">대상/업종/조건 검색</label>
          <input id="filter-text" type="search" placeholder="창업 7년 이하, 신규창업, 제조업, 도소매, 로봇, 꽃, 대출">
        </div>
        <div class="quick-filters">
          <button type="button" data-amount="20000000">2천만원+</button>
          <button type="button" data-text="창업 7년 이하">창업 7년 이하</button>
          <button type="button" data-text="신규창업">신규창업</button>
          <button type="button" data-text="융자|보증|대출">대출/보증</button>
        </div>
      </div>
      <div id="filter-count">필터 전 전체 후보를 보여줍니다.</div>
    </section>

    <section class="panel fresh">
      <div class="panel-head">
        <h2>새로 올라온 공고</h2>
        <span class="fresh-label">NEW FIRST</span>
      </div>
      <div class="cards">{fresh_cards}</div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>오늘 먼저 볼 공고</h2>
        <span class="hint">상위 3개</span>
      </div>
      <div class="cards">{cards}</div>
    </section>

    <section class="followup-search" aria-label="추가 질문 검색">
      <h2>더 좁혀서 물어보기</h2>
      <p>아래에서 다시 질문하면 현재 결과가 한 번 더 맞춤 정리됩니다.</p>
      <div class="followup-row">
        <input id="followup-query" type="search" placeholder="예: 이번엔 대출 말고 콘텐츠 제작지원만 보여줘">
        <button id="followup-search-button" type="button">다시 추리기</button>
      </div>
      <div id="search-history"></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>전체 후보</h2>
        <span class="hint">상위 40개</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>추천</th>
              <th>마감</th>
              <th>사업명</th>
              <th>지원금</th>
              <th>대상/업력</th>
              <th>관련성</th>
              <th>신청 가능성</th>
              <th>다음 액션</th>
            </tr>
          </thead>
          <tbody id="opportunity-table">{table_rows}</tbody>
        </table>
      </div>
    </section>
    </main>

    {errors_html}
    <section class="subscribe-cta" id="subscribe">
      <div>
        <h2>자동으로 매일 9시 정보 구독하기</h2>
        <p>원하는 카테고리를 저장하면 매일 오전 9시에 맞춤 지원사업, 정책자금, 보증/대출 정보를 메일로 보내드립니다.</p>
        <ul class="subscribe-list">
          <li>관심 업종/지역/지원규모 회원 수정</li>
          <li>신규 공고와 D-7 마감 공고 우선 정리</li>
          <li>구독자 화면은 광고 없이 제공</li>
        </ul>
      </div>
      <div class="subscribe-price">
        <strong>월 3만원</strong>
        <span>자동결제 · 매일 9시 맞춤 메일</span>
        <a class="subscribe-button" href="#subscribe">구독 결제하기</a>
      </div>
    </section>
    {company_footer_html(company_info)}
  </div>
  <div class="modal-backdrop" id="detail-modal" hidden>
    <article class="modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
      <div class="modal-head">
        <div>
          <div class="badges" id="detail-badges"></div>
          <h2 id="detail-title"></h2>
          <div class="meta" id="detail-org"></div>
        </div>
        <button type="button" class="modal-close" id="detail-close" aria-label="닫기">×</button>
      </div>
      <div class="modal-body">
        <div class="detail-grid">
          <div class="detail-box"><b>지원금/규모</b><span id="detail-amount"></span></div>
          <div class="detail-box"><b>마감</b><span id="detail-deadline"></span></div>
          <div class="detail-box"><b>대상/업력</b><span id="detail-target"></span></div>
          <div class="detail-box"><b>신청 가능성</b><span id="detail-eligibility"></span></div>
        </div>
        <p class="detail-summary" id="detail-summary"></p>
        <div class="chip-row" id="detail-keywords"></div>
        <div class="actions" style="margin-top: 18px;">
          <a class="button" id="detail-open" target="_blank" rel="noopener noreferrer">원문 새창 열기</a>
          <button class="button secondary" type="button" id="detail-copy">주소 복사</button>
          <span class="copy-status" id="detail-copy-status" aria-live="polite"></span>
        </div>
        <div class="detail-url" id="detail-url"></div>
      </div>
    </article>
  </div>
  <script type="application/json" id="opportunity-details-data">{details_json}</script>
  <script>
    if (new URLSearchParams(window.location.search).get('subscriber') === '1') {{
      document.body.classList.add('is-subscriber');
    }}
    const amountInput = document.getElementById('filter-amount');
    const textInput = document.getElementById('filter-text');
    const countLabel = document.getElementById('filter-count');
    const businessQuery = document.getElementById('business-query');
    const businessButton = document.getElementById('business-search-button');
    const businessResponse = document.getElementById('business-response');
    const followupQuery = document.getElementById('followup-query');
    const followupButton = document.getElementById('followup-search-button');
    const searchHistory = document.getElementById('search-history');
    const resultState = document.getElementById('result-state');
    const items = Array.from(document.querySelectorAll('.js-filter-item'));
    const detailData = JSON.parse(document.getElementById('opportunity-details-data').textContent || '[]');
    const detailMap = new Map(detailData.map((item) => [item.id, item]));
    const detailModal = document.getElementById('detail-modal');
    const detailClose = document.getElementById('detail-close');
    const detailOpen = document.getElementById('detail-open');
    const detailCopy = document.getElementById('detail-copy');
    const detailCopyStatus = document.getElementById('detail-copy-status');
    function applyFilters() {{
      document.body.classList.add('has-filter');
      const minAmount = Number(amountInput.value || 0);
      const query = (textInput.value || '').trim().toLowerCase();
      let visibleCount = 0;
      for (const item of items) {{
        const amount = Number(item.dataset.amount || 0);
        const haystack = (item.dataset.search || '').toLowerCase();
        const amountOk = !minAmount || amount >= minAmount;
        const queryOk = !query || (query.includes('|') ? query.split('|').some((part) => haystack.includes(part.trim())) : haystack.includes(query));
        const show = amountOk && queryOk;
        item.classList.toggle('is-hidden', !show);
        if (show) {{
          item.style.animationDelay = `${{Math.min(visibleCount * 34, 306)}}ms`;
          visibleCount += 1;
        }} else {{
          item.style.animationDelay = '0ms';
        }}
      }}
      countLabel.textContent = `현재 필터 결과 ${{visibleCount}}건`;
      resultState.textContent = query
        ? `검색 조건에 맞는 공고 ${{visibleCount}}건을 다시 정렬했습니다.`
        : '검색하면 아래 공고가 부드럽게 추려집니다.';
    }}
    amountInput.addEventListener('input', applyFilters);
    textInput.addEventListener('input', applyFilters);
    document.querySelectorAll('.quick-filters button, .company-tools button').forEach((button) => {{
      button.addEventListener('click', () => {{
        if (button.dataset.amount) amountInput.value = button.dataset.amount;
        if (button.dataset.text) textInput.value = button.dataset.text;
        applyFilters();
      }});
    }});
    const businessRules = [
      ['꽃', ['꽃', '화훼', '소상공인', '도소매', '온라인', '전자상거래']],
      ['화훼', ['꽃', '화훼', '소상공인', '도소매']],
      ['제조', ['제조업', '공장', '로봇', '자동화', '정책자금']],
      ['공장', ['제조업', '공장', '로봇', '자동화', '정책자금']],
      ['로봇', ['로봇', '제조업', '기술보증', '정책자금']],
      ['도소매', ['도소매업', '소상공인', '전자상거래']],
      ['온라인', ['전자상거래', '도소매업', '소상공인']],
      ['콘텐츠', ['콘텐츠', '제작지원', '디지털콘텐츠']],
      ['제작지원', ['제작지원', '콘텐츠', '사업화']],
      ['영상', ['영상', '콘텐츠', '제작지원']],
      ['미디어아트', ['미디어아트', '전시', '콘텐츠']],
      ['미디어파사드', ['미디어파사드', '공공디자인', '콘텐츠']],
      ['전시', ['전시', '공공디자인', '콘텐츠']],
      ['대출', ['융자', '보증', '대출', '정책자금']],
      ['보증', ['융자', '보증', '대출', '정책자금']],
      ['창업', ['창업 7년 이하', '신규창업', '창업기업']],
      ['신규', ['신규창업', '예비창업자']]
    ];
    function inferBusinessQuery(value) {{
      const text = value.toLowerCase();
      const terms = [];
      const wantsExclude = text.includes('말고') || text.includes('제외') || text.includes('빼고');
      const financeNeedles = ['대출', '보증'];
      for (const [needle, mapped] of businessRules) {{
        if (wantsExclude && financeNeedles.includes(needle) && text.includes(needle.toLowerCase())) continue;
        if (text.includes(needle.toLowerCase())) terms.push(...mapped);
      }}
      const amountMatch = value.match(/([0-9]+)\\s*(억|천만|천만원|만원)/);
      if (amountMatch) {{
        const number = Number(amountMatch[1]);
        const unit = amountMatch[2];
        if (unit === '억') amountInput.value = String(number * 100000000);
        if (unit.startsWith('천만')) amountInput.value = String(number * 10000000);
        if (unit === '만원') amountInput.value = String(number * 10000);
      }} else if (text.includes('2천') || text.includes('2000')) {{
        amountInput.value = '20000000';
      }}
      return [...new Set(terms)].slice(0, 10);
    }}
    function addSearchHistory(value) {{
      if (!value) return;
      const chip = document.createElement('span');
      chip.textContent = value.length > 34 ? value.slice(0, 33) + '…' : value;
      searchHistory.prepend(chip);
      while (searchHistory.children.length > 5) searchHistory.lastElementChild.remove();
    }}
    function runBusinessSearch(sourceInput = businessQuery) {{
      const value = sourceInput.value.trim();
      const terms = inferBusinessQuery(value);
      if (!amountInput.value && (value.includes('지원금') || value.includes('사업비'))) amountInput.value = '20000000';
      textInput.value = terms.length ? terms.join('|') : value;
      applyFilters();
      businessResponse.style.display = 'block';
      businessResponse.textContent = terms.length
        ? `찾는 중... ${{terms.join(', ')}} 조건으로 맞춤 공고를 추렸습니다.`
        : '찾는 중... 입력한 문장 그대로 관련 공고를 검색했습니다.';
      addSearchHistory(value);
      document.getElementById('results').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }}
    businessButton.addEventListener('click', () => runBusinessSearch(businessQuery));
    businessQuery.addEventListener('keydown', (event) => {{
      if (event.key === 'Enter') runBusinessSearch(businessQuery);
    }});
    followupButton.addEventListener('click', () => runBusinessSearch(followupQuery));
    followupQuery.addEventListener('keydown', (event) => {{
      if (event.key === 'Enter') runBusinessSearch(followupQuery);
    }});
    document.querySelectorAll('.search-examples button').forEach((button) => {{
      button.addEventListener('click', () => {{
        businessQuery.value = button.dataset.example;
        runBusinessSearch(businessQuery);
      }});
    }});
    const mediaCanvas = document.getElementById('media-canvas');
    const mediaCtx = mediaCanvas.getContext('2d');
    let mediaTick = 0;
    function drawMediaField() {{
      const rect = mediaCanvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      mediaCanvas.width = Math.max(1, Math.floor(rect.width * ratio));
      mediaCanvas.height = Math.max(1, Math.floor(rect.height * ratio));
      mediaCtx.setTransform(ratio, 0, 0, ratio, 0, 0);
      mediaCtx.clearRect(0, 0, rect.width, rect.height);
      const cols = 18;
      const rows = 9;
      const gapX = rect.width / cols;
      const gapY = rect.height / rows;
      mediaCtx.lineWidth = 1;
      for (let y = 1; y < rows; y += 1) {{
        for (let x = 1; x < cols; x += 1) {{
          const pulse = Math.sin(mediaTick * .018 + x * .7 + y * .9);
          const px = x * gapX + pulse * 7;
          const py = y * gapY + Math.cos(mediaTick * .014 + x) * 7;
          mediaCtx.strokeStyle = pulse > .32 ? 'rgba(94,234,212,.42)' : 'rgba(255,255,255,.11)';
          mediaCtx.beginPath();
          mediaCtx.moveTo(px, py);
          mediaCtx.lineTo(px + gapX * .34, py + gapY * .18);
          mediaCtx.stroke();
          if (pulse > .72) {{
            mediaCtx.fillStyle = 'rgba(248,250,252,.72)';
            mediaCtx.fillRect(px - 1.5, py - 1.5, 3, 3);
          }}
        }}
      }}
      mediaTick += 1;
      requestAnimationFrame(drawMediaField);
    }}
    drawMediaField();
    function renderDetail(id) {{
      const item = detailMap.get(id);
      if (!item) return;
      document.getElementById('detail-badges').innerHTML = item.badges;
      document.getElementById('detail-title').textContent = item.title;
      document.getElementById('detail-org').textContent = `${{item.org}} · ${{item.status}}`;
      document.getElementById('detail-amount').textContent = item.amount || '확인 필요';
      document.getElementById('detail-deadline').textContent = item.d_day ? `${{item.deadline}} ${{item.d_day}}` : item.deadline;
      document.getElementById('detail-target').textContent = item.target || '대상 확인 필요';
      document.getElementById('detail-eligibility').textContent = item.eligibility || '확인 필요';
      document.getElementById('detail-summary').textContent = item.summary || item.next_action || '원문 확인이 필요합니다.';
      document.getElementById('detail-keywords').innerHTML = item.keywords.map((keyword) => `<span class="mini-chip">${{keyword}}</span>`).join('');
      document.getElementById('detail-url').textContent = item.url || '';
      detailOpen.href = item.url || '#';
      detailCopy.dataset.url = item.url || '';
      detailCopyStatus.textContent = '';
      detailModal.hidden = false;
      detailClose.focus();
    }}
    document.querySelectorAll('[data-detail-id]').forEach((button) => {{
      button.addEventListener('click', () => renderDetail(button.dataset.detailId));
    }});
    detailClose.addEventListener('click', () => {{
      detailModal.hidden = true;
    }});
    detailModal.addEventListener('click', (event) => {{
      if (event.target === detailModal) detailModal.hidden = true;
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') detailModal.hidden = true;
    }});
    detailCopy.addEventListener('click', async () => {{
      const url = detailCopy.dataset.url || '';
      if (!url) return;
      try {{
        await navigator.clipboard.writeText(url);
        detailCopyStatus.textContent = '복사 완료';
      }} catch (error) {{
        detailCopyStatus.textContent = '주소를 선택해서 복사해주세요';
      }}
    }});
  </script>
</body>
</html>
"""


def build_card(opp: Opportunity) -> str:
    detail_id = opportunity_detail_id(opp)
    return f"""
        <article class="card js-filter-item" data-amount="{opp.amount_value or 0}" data-search="{escape(search_blob(opp))}">
          <div class="badges">{priority_badge(opp)}{status_badge(opp)}</div>
          <h3>{escape(short_title(opp.title, 110))}</h3>
          <div class="meta">{escape(opp.org)} · {deadline_badge(opp)}</div>
          {fact_grid(opp)}
          {target_chips(opp)}
          <p class="summary">{escape(short_title(opp.summary or opp.next_action, 150))}</p>
          <div class="actions"><button class="button" type="button" data-detail-id="{detail_id}">상세 보기</button></div>
        </article>
    """


def build_table_row(opp: Opportunity) -> str:
    detail_id = opportunity_detail_id(opp)
    return f"""
            <tr class="js-filter-item" data-amount="{opp.amount_value or 0}" data-search="{escape(search_blob(opp))}">
              <td>{priority_badge(opp)}</td>
              <td class="deadline">{escape(display_deadline_text(opp))}<br><span class="meta">{deadline_badge(opp)}</span></td>
              <td class="title-cell"><button class="title-button" type="button" data-detail-id="{detail_id}">{escape(short_title(opp.title, 120))}</button><div class="org">{escape(opp.org)} · {escape(opp.status)}</div></td>
              <td class="money">{escape(display_amount_text(opp))}</td>
              <td>{escape(display_target_text(opp))}</td>
              <td>{escape(opp.relevance or "확인 필요")}</td>
              <td>{escape(display_eligibility_text(opp))}</td>
              <td class="next">{escape(display_next_action(opp))}</td>
            </tr>
    """


def fact_grid(opp: Opportunity) -> str:
    amount_cls = "fact strong" if opp.amount_value else "fact warn"
    return f"""
          <div class="facts">
            <div class="{amount_cls}"><span class="fact-label">{escape(amount_label(opp))}</span><span class="fact-value">{escape(short_title(display_amount_text(opp), 58))}</span></div>
            <div class="fact"><span class="fact-label">대상/업력</span><span class="fact-value">{escape(short_title(display_target_text(opp), 48))}</span></div>
            <div class="fact"><span class="fact-label">마감/운영</span><span class="fact-value">{deadline_fact_value_html(opp)}</span></div>
            <div class="fact"><span class="fact-label">지역/가능성</span><span class="fact-value">{escape(short_title(display_eligibility_text(opp), 48))}</span></div>
          </div>
    """


def target_chips(opp: Opportunity) -> str:
    chips = []
    for value in [*(opp.keywords or []), *(opp.target or "").split(", ")]:
        value = value.strip()
        if value and value != "확인 필요" and value not in chips:
            chips.append(value)
    if not chips:
        return ""
    return '<div class="chip-row">' + "".join(f'<span class="mini-chip">{escape(short_title(chip, 16))}</span>' for chip in chips[:6]) + "</div>"


def deadline_badge(opp: Opportunity) -> str:
    if not opp.d_day:
        if is_policy_finance(opp):
            return '<span class="d-chip d-muted">소진시까지</span>'
        return '<span class="d-chip d-muted">일정 확인</span>'
    number = _dday_number(opp.d_day)
    cls = "d-urgent" if number <= 7 else "d-normal"
    if opp.d_day.startswith("D+"):
        cls = "d-muted"
    return f'<span class="d-chip {cls}">{escape(opp.d_day)}</span>'


def deadline_fact_value_html(opp: Opportunity) -> str:
    if not opp.d_day:
        return escape(display_deadline_text(opp))
    return f"{escape(display_deadline_text(opp))} {deadline_badge(opp)}"


def search_blob(opp: Opportunity) -> str:
    return " ".join(
        [
            opp.title,
            opp.org,
            opp.amount_text,
            opp.target,
            opp.region,
            opp.relevance,
            opp.eligibility,
            " ".join(opp.keywords),
            opp.summary,
        ]
    )


def display_amount_text(opp: Opportunity) -> str:
    text = clean_display_text(opp)
    policy_summary = policy_finance_summary(text)
    if policy_summary:
        return policy_summary
    if opp.amount_text and opp.amount_text != "확인 필요":
        return opp.amount_text
    if re.search(r"(총사업비|사업비|지원규모|선정규모|기업당|개사당|과제당)", text):
        return "공고문 내 규모 확인"
    return "지원규모 확인 필요"


def amount_label(opp: Opportunity) -> str:
    if is_policy_finance(opp):
        return "정책자금/융자 규모"
    if re.search(r"(총사업비|사업비)", clean_display_text(opp)):
        return "총사업비/지원규모"
    return "지원금/규모"


def display_deadline_text(opp: Opportunity) -> str:
    if opp.deadline:
        return opp.deadline
    text = clean_display_text(opp)
    if re.search(r"(상시|수시|자금\s*소진|예산\s*소진)", text):
        return "소진시까지"
    if is_policy_finance(opp):
        return "소진시까지"
    return "접수 일정 확인 필요"


def display_target_text(opp: Opportunity) -> str:
    if opp.target and opp.target != "확인 필요":
        return opp.target
    text = clean_display_text(opp)
    inferred = []
    for keyword in ["중소기업", "소상공인", "여성기업", "창업기업", "예비창업자", "제조업", "도소매업", "콘텐츠기업"]:
        if keyword in text:
            inferred.append(keyword)
    return ", ".join(dict.fromkeys(inferred)) if inferred else "대상 조건 원문 확인"


def display_eligibility_text(opp: Opportunity) -> str:
    if opp.eligibility and opp.eligibility != "확인 필요":
        return opp.eligibility
    text = clean_display_text(opp)
    if "대구" in text or "대구" in (opp.region or ""):
        return "대구 기업 확인 대상"
    if is_national_public_source(opp):
        return "전국 공고, 대구 기업 가능성 높음"
    if re.search(r"(전국|중소기업|소상공인|창업기업)", text):
        return "전국/요건 확인"
    return "지역 제한 확인 필요"


def display_next_action(opp: Opportunity) -> str:
    text = clean_display_text(opp)
    if is_policy_finance(opp):
        if re.search(r"(이차보전|보증|융자)", text):
            return "기업별 한도·금리·보증요건 확인"
        return "세부 자금 신청요건 확인"
    if opp.amount_text and opp.amount_text != "확인 필요":
        return opp.next_action or "신청 자격과 제출서류 확인"
    return opp.next_action or "지원규모와 제출서류 확인"


def clean_display_text(opp: Opportunity) -> str:
    return " ".join([opp.title or "", opp.org or "", opp.amount_text or "", opp.summary or "", opp.target or "", opp.region or ""])


def is_policy_finance(opp: Opportunity) -> bool:
    return bool(re.search(r"(정책자금|융자|대출|보증|이차보전|경영안정자금|신용보증|기술보증)", clean_display_text(opp)))


def is_national_public_source(opp: Opportunity) -> bool:
    return any(
        name in (opp.org or "")
        for name in ["중소벤처기업", "중소벤처기업진흥공단", "소상공인", "신용보증기금", "기술보증기금", "기업마당", "K-Startup"]
    )


def policy_finance_summary(text: str) -> str:
    labels = [
        ("융자", r"융자\s*[\(:：]?\s*([0-9,]+\s*조\s*[0-9,]*\s*억\s*원?|[0-9,]+(?:\.\d+)?\s*억\s*원?)"),
        ("이차보전", r"이차보전\s*[\(:：]?\s*([0-9,]+\s*조\s*[0-9,]*\s*억\s*원?|[0-9,]+(?:\.\d+)?\s*억\s*원?)"),
        ("보증", r"보증\s*[\(:：]?\s*([0-9,]+\s*조\s*[0-9,]*\s*억\s*원?|[0-9,]+(?:\.\d+)?\s*억\s*원?)"),
        ("총규모", r"지원규모\s*([0-9,]+\s*조\s*[0-9,]*\s*억\s*원?|[0-9,]+(?:\.\d+)?\s*억\s*원?)"),
    ]
    parts = []
    for label, pattern in labels:
        match = re.search(pattern, text)
        if match:
            parts.append(f"{label} {normalize_money_phrase(match.group(1))}")
    if not parts:
        return ""
    suffix = " / 기업별 한도 확인"
    return " / ".join(dict.fromkeys(parts)) + suffix


def normalize_money_phrase(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("억 원", "억원").replace("조 ", "조 ")
    return value


def opportunity_detail_id(opp: Opportunity) -> str:
    raw = "|".join([opp.org, normalize_opportunity_title(opp.title), opp.deadline, opp.url])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def opportunity_detail_payload(opp: Opportunity) -> dict[str, object]:
    return {
        "id": opportunity_detail_id(opp),
        "title": opp.title,
        "org": opp.org,
        "status": opp.status,
        "badges": priority_badge(opp) + status_badge(opp),
        "amount": display_amount_text(opp),
        "deadline": display_deadline_text(opp),
        "d_day": opp.d_day,
        "target": display_target_text(opp),
        "eligibility": display_eligibility_text(opp),
        "summary": opp.summary,
        "next_action": display_next_action(opp),
        "keywords": [short_title(keyword, 20) for keyword in (opp.keywords or [])[:8]],
        "url": opp.url,
    }


def load_company_keywords(path: str = "company_profile.md") -> list[str]:
    text = read_text_file(path)
    keywords: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = "관심 업종" in stripped or "관심 종목" in stripped
            continue
        if in_section and stripped.startswith("- "):
            value = re.sub(r"\s+", " ", stripped[2:]).strip()
            if value and not value.startswith("TODO"):
                keywords.append(value)
    if not keywords:
        keywords = ["AI", "영상", "콘텐츠", "제조업", "도소매업", "정책자금", "대출", "보증", "창업 7년 이하"]
    return list(dict.fromkeys(keywords))[:18]


def load_company_info(path: str = "company_profile.md") -> dict[str, str]:
    text = read_text_file(path)
    info: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        key = key.strip()
        value = value.strip()
        if value and not value.startswith("TODO"):
            info[key] = value
    return info


def load_company_conditions(path: str = "company_profile.md") -> dict[str, list[str]]:
    text = read_text_file(path)
    sections: dict[str, list[str]] = {}
    in_parent = False
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_parent = "맞춤 검색 조건" in stripped
            current = ""
            continue
        if not in_parent:
            continue
        if stripped.startswith("### "):
            current = stripped[4:].strip()
            sections[current] = []
            continue
        if current and stripped.startswith("- "):
            value = stripped[2:].strip()
            if value:
                sections[current].append(value)
    return sections


def company_conditions_html(sections: dict[str, list[str]]) -> str:
    if not sections:
        return ""
    cards = []
    for title, items in sections.items():
        item_html = "".join(f"<li>{escape(item)}</li>" for item in items[:4])
        cards.append(f'<section class="condition-card"><h3>{escape(title)}</h3><ul>{item_html}</ul></section>')
    return f"""
        <details class="company-profile-panel" open>
          <summary>회사 맞춤 검색 조건 <span>관심 분야와 필터 기준 보기</span></summary>
          <div class="condition-grid">{''.join(cards)}</div>
        </details>
    """


def company_footer_html(info: dict[str, str]) -> str:
    name = info.get("회사명", "상상연필")
    lines = [
        ("대표자", info.get("대표자", "확인 필요")),
        ("소재지", info.get("소재지", "확인 필요")),
        ("업태", info.get("업태", "확인 필요")),
        ("종목", info.get("종목", "확인 필요")),
        ("개업일", info.get("개업일", "확인 필요")),
        ("사업자등록번호", info.get("사업자등록번호", "마스킹 표시")),
    ]
    line_html = "".join(f'<div class="company-line"><b>{escape(k)}</b>{escape(v)}</div>' for k, v in lines)
    return f"""
    <footer>
      <div class="company-footer">
        <div>
          <strong>{escape(name)}</strong>
          <div>대구 사업자를 위한 정부지원사업·정책자금 모니터링 리포트</div>
        </div>
        <div class="company-lines">{line_html}</div>
      </div>
      <div class="service-note">서비스 구상: 월 3만원 자동결제 기본형은 매일 9시 맞춤 카테고리 메일을 제공하고, 회원은 관심 업종/키워드를 수정할 수 있습니다. 지원서 초안·검수·전자세금계산서 포함 프리미엄은 별도 상품으로 운영합니다.</div>
    </footer>
    """


def priority_badge(opp: Opportunity) -> str:
    label = report_priority(opp)
    cls = "b-high" if label == "높음" else ("b-review" if label == "검토" else "b-normal")
    return f'<span class="badge {cls}">{escape(label)}</span>'


def status_badge(opp: Opportunity) -> str:
    if opp.status == "new":
        return '<span class="badge b-new">신규</span>'
    if opp.status == "updated":
        return '<span class="badge b-normal">업데이트</span>'
    if opp.status == "needs_review":
        return '<span class="badge b-review">금액 확인</span>'
    return ""


def empty_state_html(message: str = "오늘은 조건에 맞는 신규 공고 없음") -> str:
    return f'<div class="empty">{escape(message)}</div>'


def _dday_number(value: str) -> int:
    try:
        return int(value.replace("D-", "").strip())
    except ValueError:
        return 999


def unique_for_display(opportunities: list[Opportunity]) -> list[Opportunity]:
    chosen: dict[tuple[str, str, str], Opportunity] = {}
    for opp in opportunities:
        key = (opp.org, normalize_opportunity_title(opp.title), opp.deadline)
        current = chosen.get(key)
        if current is None or display_rank(opp) > display_rank(current):
            chosen[key] = opp
    return sorted(chosen.values(), key=lambda item: (item.status == "expired", -item.score, item.deadline or "9999"))


def display_rank(opp: Opportunity) -> tuple[int, int, int]:
    is_detail = int(any(token in opp.url for token in ["/business/", "boardRead", "detail", "pbancSn=", "pblancId="]))
    has_amount = int(bool(opp.amount_value))
    short_title = -len(opp.title)
    return (opp.score + is_detail * 5 + has_amount * 3, is_detail, short_title)


def write_reports(markdown: str, html: str, today: date | None = None) -> tuple[Path, Path, Path, Path]:
    today = today or date.today()
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    site_dir = Path("site")
    site_dir.mkdir(parents=True, exist_ok=True)
    dated = reports_dir / f"{today.isoformat()}.md"
    latest = reports_dir / "latest.md"
    dated_html = reports_dir / f"{today.isoformat()}.html"
    latest_html = reports_dir / "latest.html"
    site_index = site_dir / "index.html"
    dated.write_text(markdown, encoding="utf-8")
    latest.write_text(markdown, encoding="utf-8")
    dated_html.write_text(html, encoding="utf-8")
    latest_html.write_text(html, encoding="utf-8")
    site_index.write_text(html, encoding="utf-8")
    return dated, latest, dated_html, latest_html
