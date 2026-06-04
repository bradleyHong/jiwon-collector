from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import requests

from .parsers import normalize_opportunity_title
from .storage import Opportunity


def build_message(opportunities: list[Opportunity]) -> str:
    hot = [
        opp
        for opp in opportunities
        if opp.status in {"new", "updated", "needs_review"} and opp.priority in {"high_priority", "needs_review"}
    ]
    hot = unique_hot(hot)
    if not hot:
        return "오늘은 조건에 맞는 신규 공고 없음"
    lines = ["대구 지원사업 유망 공고 TOP 3"]
    for idx, opp in enumerate(hot[:3], start=1):
        lines.append(f"{idx}. {opp.title}")
        lines.append(f"   {opp.org} / {opp.d_day or 'D-?'} / {opp.amount_text}")
        lines.append(f"   {opp.url}")
    return "\n".join(lines)


def build_email_subject(opportunities: list[Opportunity]) -> str:
    hot = unique_hot(
        [
            opp
            for opp in opportunities
            if opp.status in {"new", "updated", "needs_review"} and opp.priority in {"high_priority", "needs_review"}
        ]
    )
    if not hot:
        return "[대구 지원사업] 오늘은 조건에 맞는 신규 공고 없음"
    lead = hot[0]
    return f"[대구 지원사업][{lead.d_day or 'D-?'}] {lead.title[:42]}"


def build_email_text(opportunities: list[Opportunity]) -> str:
    return build_message(opportunities) + "\n\nHTML 리포트는 reports/latest.html 파일에서 확인할 수 있습니다."


def send_email(subject: str, html: str, text: str, dry_run: bool = False) -> bool:
    if dry_run:
        return False
    host = os.getenv("SMTP_HOST")
    mail_to = os.getenv("MAIL_TO")
    mail_from = os.getenv("MAIL_FROM") or os.getenv("SMTP_USERNAME")
    if not host or not mail_to or not mail_from:
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = mail_to
    message.set_content(text)
    message.add_alternative(inline_email_css(html), subtype="html")

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


def inline_email_css(html: str) -> str:
    notice = (
        '<div style="margin:0 0 16px;padding:12px 14px;border-radius:8px;'
        'background:#eaf2ff;color:#1d4ed8;font-family:Arial,sans-serif;font-size:13px;">'
        "이 메일은 자동 생성된 대구 지원사업 모니터링 요약입니다."
        "</div>"
    )
    return html.replace('<div class="wrap">', f'<div class="wrap">{notice}', 1)


def unique_hot(opportunities: list[Opportunity]) -> list[Opportunity]:
    chosen: dict[tuple[str, str, str], Opportunity] = {}
    for opp in opportunities:
        key = (opp.org, normalize_opportunity_title(opp.title), opp.deadline)
        current = chosen.get(key)
        if current is None or opp.score > current.score:
            chosen[key] = opp
    return list(chosen.values())


def send_telegram(message: str, dry_run: bool = False) -> bool:
    if dry_run:
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
    return True
