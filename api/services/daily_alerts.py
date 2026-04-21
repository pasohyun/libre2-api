from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

import config
from api.database import SessionLocal
from api.services.range_report_builder import build_range_report

KST = timezone(timedelta(hours=9))


@dataclass
class AlertConfig:
    enabled: bool
    recipient_emails: list[str]
    threshold_price: int


def _normalize_recipient_emails(raw: str | None) -> list[str]:
    if not raw:
        return []
    emails: list[str] = []
    for part in raw.replace(";", ",").split(","):
        e = part.strip().lower()
        if not e:
            continue
        if "@" not in e:
            raise ValueError(f"유효하지 않은 이메일 형식입니다: {part}")
        if e not in emails:
            emails.append(e)
    if len(emails) > 5:
        raise ValueError("수신 이메일은 최대 5개까지 설정할 수 있습니다.")
    return emails


def _load_alert_config(db: Session) -> AlertConfig | None:
    row = db.execute(
        text(
            """
            SELECT enabled, recipient_email, threshold_price, source_times_kst
            FROM alert_settings
            WHERE id = 1
            """
        )
    ).mappings().first()
    if not row:
        return None
    recipients = _normalize_recipient_emails((row["recipient_email"] or "").strip())
    return AlertConfig(
        enabled=bool(row["enabled"]),
        recipient_emails=recipients,
        threshold_price=int(row["threshold_price"] or config.TARGET_PRICE),
    )


def get_alert_config_dict(db: Session) -> dict[str, Any]:
    conf = _load_alert_config(db)
    if conf is None:
        return {
            "enabled": False,
            "recipient_emails": [],
            "threshold_price": config.TARGET_PRICE,
            "send_time_kst": os.getenv("ALERT_SEND_TIME_KST", "09:00"),
        }
    return {
        "enabled": conf.enabled,
        "recipient_emails": conf.recipient_emails,
        "threshold_price": conf.threshold_price,
        "send_time_kst": os.getenv("ALERT_SEND_TIME_KST", "09:00"),
    }


def upsert_alert_config(
    db: Session,
    *,
    enabled: bool,
    recipient_emails: list[str],
    threshold_price: int,
) -> dict[str, Any]:
    recipients = _normalize_recipient_emails(",".join(recipient_emails))
    if not recipients:
        raise ValueError("수신 이메일을 최소 1개 입력해주세요.")
    recipient_csv = ",".join(recipients)
    db.execute(
        text(
            """
            INSERT INTO alert_settings (
                id, enabled, recipient_email, threshold_price, source_times_kst
            )
            VALUES (1, :enabled, :recipient_email, :threshold_price, :source_times_kst)
            ON DUPLICATE KEY UPDATE
                enabled=VALUES(enabled),
                recipient_email=VALUES(recipient_email),
                threshold_price=VALUES(threshold_price),
                source_times_kst=VALUES(source_times_kst)
            """
        ),
        {
            "enabled": 1 if enabled else 0,
            "recipient_email": recipient_csv,
            "threshold_price": threshold_price,
                "source_times_kst": "00:00,12:00",
        },
    )
    db.commit()
    return get_alert_config_dict(db)


def _build_email_subject(target_date: date, threshold_price: int) -> str:
    return f"[Libre2 알람] {target_date:%Y-%m-%d} 기준 {threshold_price:,}원 미만 거래처"


def _build_email_body(
    *,
    target_date: date,
    threshold_price: int,
    report: dict[str, Any],
) -> tuple[str, str]:
    summary = report.get("summary") or {}
    below = report.get("below_threshold_list") or []
    top5 = summary.get("top5_lowest") or []

    summary_lines = [
        f"- 기준가 이하 셀러 수: {int(summary.get('below_threshold_seller_count') or 0)}곳",
    ]
    if summary.get("global_min_price") is not None:
        summary_lines.append(
            "- 최저 단가: "
            f"{int(summary.get('global_min_price')):,}원 "
            f"({summary.get('global_min_seller') or '-'}) @ {summary.get('global_min_time') or '-'}"
        )
    if top5:
        summary_lines.append("- 최저가격 상위 5개 거래처:")
        for item in top5:
            summary_lines.append(
                f"  - {item.get('seller_name') or '-'}: "
                f"{int(item.get('min_unit_price') or 0):,}원 "
                f"({item.get('platform') or '-'}) @ {item.get('min_time') or '-'}"
            )

    detail_lines = []
    if below:
        for item in below:
            detail_lines.append(
                f"- {item.get('seller_name') or '-'} | {item.get('platform') or '-'} | "
                f"{int(item.get('unit_price') or 0):,}원 | "
                f"{int(item.get('total_price') or 0):,}원 | 수량 {int(item.get('quantity') or 0)} | "
                f"{item.get('time') or '-'}"
            )
    else:
        detail_lines.append("기준가 이하 거래처가 없습니다.")

    text_body = (
        f"{target_date:%Y-%m-%d} 기준 알람 리포트 (기준가 {threshold_price:,}원)\n\n"
        "① 요약\n"
        + "\n".join(summary_lines)
        + "\n\n② 기준가 이하 리스트\n"
        + "\n".join(detail_lines)
    )

    top5_html = ""
    if top5:
        top5_rows = "".join(
            "<li>"
            f"{item.get('seller_name') or '-'}: {int(item.get('min_unit_price') or 0):,}원 "
            f"({item.get('platform') or '-'}) @ {item.get('min_time') or '-'}"
            "</li>"
            for item in top5
        )
        top5_html = (
            "<div style='margin-top:8px;'><strong>최저가격 상위 5개 거래처</strong>"
            f"<ul style='margin:6px 0 0 20px;'>{top5_rows}</ul></div>"
        )

    if below:
        detail_rows = "".join(
            "<tr>"
            f"<td>{item.get('seller_name') or '-'}</td>"
            f"<td>{item.get('platform') or '-'}</td>"
            f"<td style='text-align:right;'>{int(item.get('unit_price') or 0):,}원</td>"
            f"<td style='text-align:right;'>{int(item.get('total_price') or 0):,}원</td>"
            f"<td style='text-align:right;'>{int(item.get('quantity') or 0)}</td>"
            f"<td>{item.get('time') or '-'}</td>"
            "</tr>"
            for item in below
        )
        detail_html = (
            "<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
            "<thead><tr>"
            "<th style='text-align:left;border-bottom:1px solid #ddd;padding:6px;'>판매처</th>"
            "<th style='text-align:left;border-bottom:1px solid #ddd;padding:6px;'>채널</th>"
            "<th style='text-align:right;border-bottom:1px solid #ddd;padding:6px;'>최저 단가</th>"
            "<th style='text-align:right;border-bottom:1px solid #ddd;padding:6px;'>총 금액</th>"
            "<th style='text-align:right;border-bottom:1px solid #ddd;padding:6px;'>수량</th>"
            "<th style='text-align:left;border-bottom:1px solid #ddd;padding:6px;'>시점</th>"
            "</tr></thead>"
            f"<tbody>{detail_rows}</tbody></table>"
        )
    else:
        detail_html = "<p>기준가 이하 거래처가 없습니다.</p>"

    html_body = (
        f"<p><strong>{target_date:%Y-%m-%d}</strong> 기준 알람 리포트 "
        f"(기준가 <strong>{threshold_price:,}원</strong>)</p>"
        "<h3 style='margin:8px 0 4px;'>① 요약</h3>"
        f"<p style='margin:0;'>기준가 이하 셀러 수: <strong>{int(summary.get('below_threshold_seller_count') or 0)}곳</strong></p>"
        + (
            f"<p style='margin:4px 0 0;'>최저 단가: <strong>{int(summary.get('global_min_price') or 0):,}원</strong> "
            f"({summary.get('global_min_seller') or '-'}) @ {summary.get('global_min_time') or '-'}</p>"
            if summary.get("global_min_price") is not None
            else ""
        )
        + top5_html
        + "<h3 style='margin:14px 0 6px;'>② 기준가 이하 리스트</h3>"
        + detail_html
    )
    return text_body, html_body


def _send_email(*, recipients: list[str], subject: str, text_body: str, html_body: str) -> None:
    host = os.getenv("ALERT_SMTP_HOST", "").strip()
    user = os.getenv("ALERT_SMTP_USER", "").strip()
    password = os.getenv("ALERT_SMTP_PASSWORD", "").strip()
    # 발신 주소는 SMTP 로그인 계정과 동일 (Gmail 등에서 권장).
    mail_from = user
    port = int(os.getenv("ALERT_SMTP_PORT", "587"))
    use_tls = os.getenv("ALERT_SMTP_USE_TLS", "true").lower() == "true"

    if not host or not user or not password or not mail_from:
        raise RuntimeError(
            "SMTP 설정이 없습니다. ALERT_SMTP_HOST/USER/PASSWORD 환경변수를 확인하세요."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=20) as server:
        if use_tls:
            server.starttls()
        server.login(user, password)
        server.sendmail(mail_from, recipients, msg.as_string())


def run_daily_alert_job(reference_now: datetime | None = None) -> dict[str, Any]:
    now_kst = (reference_now or datetime.now(KST)).astimezone(KST)
    target_date = (now_kst - timedelta(days=1)).date()

    with SessionLocal() as db:
        conf = _load_alert_config(db)
        if conf is None:
            return {"status": "skipped", "reason": "config_not_set"}
        if not conf.enabled:
            return {"status": "skipped", "reason": "disabled"}
        if not conf.recipient_emails:
            return {"status": "skipped", "reason": "recipient_empty"}
        recipient_key = ",".join(conf.recipient_emails)

        exists = db.execute(
            text(
                """
                SELECT id
                FROM alert_delivery_logs
                WHERE target_date = :target_date
                  AND recipient_email = :recipient_email
                  AND threshold_price = :threshold_price
                LIMIT 1
                """
            ),
            {
                "target_date": target_date.strftime("%Y-%m-%d"),
                "recipient_email": recipient_key,
                "threshold_price": conf.threshold_price,
            },
        ).first()
        if exists:
            return {"status": "skipped", "reason": "already_sent", "target_date": str(target_date)}

        report = build_range_report(
            db,
            start_date=target_date.strftime("%Y-%m-%d"),
            end_date=target_date.strftime("%Y-%m-%d"),
            threshold_price=conf.threshold_price,
            channel="all",
        )
        below = report.get("below_threshold_list") or []
        subject = _build_email_subject(target_date, conf.threshold_price)
        text_body, html_body = _build_email_body(
            target_date=target_date,
            threshold_price=conf.threshold_price,
            report=report,
        )

        _send_email(
            recipients=conf.recipient_emails,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

        db.execute(
            text(
                """
                INSERT INTO alert_delivery_logs (
                    target_date, recipient_email, threshold_price, mall_count, sent_at
                )
                VALUES (
                    :target_date, :recipient_email, :threshold_price, :mall_count, :sent_at
                )
                """
            ),
            {
                "target_date": target_date.strftime("%Y-%m-%d"),
                "recipient_email": recipient_key,
                "threshold_price": conf.threshold_price,
                "mall_count": len(below),
                "sent_at": now_kst.replace(tzinfo=None),
            },
        )
        db.commit()
        return {
            "status": "sent",
            "target_date": str(target_date),
            "recipient_emails": conf.recipient_emails,
            "threshold_price": conf.threshold_price,
            "mall_count": len(below),
        }
