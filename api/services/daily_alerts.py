from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

import config
from api.database import SessionLocal

KST = timezone(timedelta(hours=9))


@dataclass
class AlertConfig:
    enabled: bool
    recipient_email: str
    threshold_price: int
    source_times_kst: list[str]


def _normalize_source_times(raw: str | None) -> list[str]:
    if not raw:
        return ["00:00", "12:00"]
    out: list[str] = []
    for item in raw.split(","):
        t = item.strip()
        if not t:
            continue
        parts = t.split(":")
        if len(parts) != 2:
            raise ValueError("source_times_kst는 HH:MM 형식이어야 합니다.")
        hh = int(parts[0])
        mm = int(parts[1])
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            raise ValueError("source_times_kst 시간 범위가 올바르지 않습니다.")
        t_norm = f"{hh:02d}:{mm:02d}"
        if t_norm not in out:
            out.append(t_norm)
    return out or ["00:00", "12:00"]


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
    return AlertConfig(
        enabled=bool(row["enabled"]),
        recipient_email=(row["recipient_email"] or "").strip(),
        threshold_price=int(row["threshold_price"] or config.TARGET_PRICE),
        source_times_kst=_normalize_source_times(row.get("source_times_kst")),
    )


def get_alert_config_dict(db: Session) -> dict[str, Any]:
    conf = _load_alert_config(db)
    if conf is None:
        return {
            "enabled": False,
            "recipient_email": "",
            "threshold_price": config.TARGET_PRICE,
            "source_times_kst": ["00:00", "12:00"],
            "send_time_kst": os.getenv("ALERT_SEND_TIME_KST", "09:00"),
        }
    return {
        "enabled": conf.enabled,
        "recipient_email": conf.recipient_email,
        "threshold_price": conf.threshold_price,
        "source_times_kst": conf.source_times_kst,
        "send_time_kst": os.getenv("ALERT_SEND_TIME_KST", "09:00"),
    }


def upsert_alert_config(
    db: Session,
    *,
    enabled: bool,
    recipient_email: str,
    threshold_price: int,
    source_times_kst: list[str],
) -> dict[str, Any]:
    source_times_norm = _normalize_source_times(",".join(source_times_kst))
    source_times_str = ",".join(source_times_norm)
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
            "recipient_email": recipient_email.strip(),
            "threshold_price": threshold_price,
            "source_times_kst": source_times_str,
        },
    )
    db.commit()
    return get_alert_config_dict(db)


def _fetch_below_threshold_rows(
    db: Session,
    *,
    target_date: date,
    threshold_price: int,
    source_times_kst: list[str],
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                p.mall_name,
                MIN(p.unit_price) AS min_unit_price,
                MIN(COALESCE(p.snapshot_at, p.created_at)) AS first_seen_at
            FROM products p
            WHERE DATE(COALESCE(p.snapshot_at, p.created_at)) = :target_date
              AND TIME_FORMAT(COALESCE(p.snapshot_at, p.created_at), '%H:%i') IN :source_times
              AND p.unit_price < :threshold_price
            GROUP BY p.mall_name
            ORDER BY min_unit_price ASC, mall_name ASC
            """
        ),
        {
            "target_date": target_date.strftime("%Y-%m-%d"),
            "source_times": tuple(source_times_kst),
            "threshold_price": threshold_price,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


def _build_email_subject(target_date: date, threshold_price: int) -> str:
    return f"[Libre2 알람] {target_date:%Y-%m-%d} 기준 {threshold_price:,}원 미만 거래처"


def _build_email_body(
    *,
    target_date: date,
    threshold_price: int,
    source_times_kst: list[str],
    rows: list[dict[str, Any]],
) -> tuple[str, str]:
    time_label = ", ".join(source_times_kst)
    if rows:
        lines = [
            f"- {r.get('mall_name') or '(unknown)'}: {int(r['min_unit_price']):,}원"
            for r in rows
        ]
        text_body = (
            f"{target_date:%Y-%m-%d} ({time_label} KST) 수집 데이터 기준으로\n"
            f"셋팅가 {threshold_price:,}원 미만 거래처 목록입니다.\n\n"
            + "\n".join(lines)
        )
        html_rows = "".join(
            f"<li>{(r.get('mall_name') or '(unknown)')}: {int(r['min_unit_price']):,}원</li>"
            for r in rows
        )
        html_body = (
            f"<p><strong>{target_date:%Y-%m-%d}</strong> ({time_label} KST) 수집 데이터 기준으로 "
            f"셋팅가 <strong>{threshold_price:,}원</strong> 미만 거래처 목록입니다.</p>"
            f"<ul>{html_rows}</ul>"
        )
        return text_body, html_body

    text_body = (
        f"{target_date:%Y-%m-%d} ({time_label} KST) 수집 데이터 기준으로\n"
        f"셋팅가 {threshold_price:,}원 미만 거래처가 없습니다."
    )
    html_body = (
        f"<p><strong>{target_date:%Y-%m-%d}</strong> ({time_label} KST) 수집 데이터 기준으로 "
        f"셋팅가 <strong>{threshold_price:,}원</strong> 미만 거래처가 없습니다.</p>"
    )
    return text_body, html_body


def _send_email(*, recipient: str, subject: str, text_body: str, html_body: str) -> None:
    host = os.getenv("ALERT_SMTP_HOST", "").strip()
    user = os.getenv("ALERT_SMTP_USER", "").strip()
    password = os.getenv("ALERT_SMTP_PASSWORD", "").strip()
    mail_from = os.getenv("ALERT_FROM_EMAIL", user).strip()
    port = int(os.getenv("ALERT_SMTP_PORT", "587"))
    use_tls = os.getenv("ALERT_SMTP_USE_TLS", "true").lower() == "true"

    if not host or not user or not password or not mail_from:
        raise RuntimeError(
            "SMTP 설정이 없습니다. ALERT_SMTP_HOST/USER/PASSWORD/FROM_EMAIL 환경변수를 확인하세요."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = recipient
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port, timeout=20) as server:
        if use_tls:
            server.starttls()
        server.login(user, password)
        server.sendmail(mail_from, [recipient], msg.as_string())


def run_daily_alert_job(reference_now: datetime | None = None) -> dict[str, Any]:
    now_kst = (reference_now or datetime.now(KST)).astimezone(KST)
    target_date = (now_kst - timedelta(days=1)).date()

    with SessionLocal() as db:
        conf = _load_alert_config(db)
        if conf is None:
            return {"status": "skipped", "reason": "config_not_set"}
        if not conf.enabled:
            return {"status": "skipped", "reason": "disabled"}
        if not conf.recipient_email:
            return {"status": "skipped", "reason": "recipient_empty"}

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
                "recipient_email": conf.recipient_email,
                "threshold_price": conf.threshold_price,
            },
        ).first()
        if exists:
            return {"status": "skipped", "reason": "already_sent", "target_date": str(target_date)}

        rows = _fetch_below_threshold_rows(
            db,
            target_date=target_date,
            threshold_price=conf.threshold_price,
            source_times_kst=conf.source_times_kst,
        )
        subject = _build_email_subject(target_date, conf.threshold_price)
        text_body, html_body = _build_email_body(
            target_date=target_date,
            threshold_price=conf.threshold_price,
            source_times_kst=conf.source_times_kst,
            rows=rows,
        )

        _send_email(
            recipient=conf.recipient_email,
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
                "recipient_email": conf.recipient_email,
                "threshold_price": conf.threshold_price,
                "mall_count": len(rows),
                "sent_at": now_kst.replace(tzinfo=None),
            },
        )
        db.commit()
        return {
            "status": "sent",
            "target_date": str(target_date),
            "recipient_email": conf.recipient_email,
            "threshold_price": conf.threshold_price,
            "mall_count": len(rows),
            "source_times_kst": conf.source_times_kst,
        }
