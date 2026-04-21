from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFont
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
            f"<td style='text-align:center;'>{int(item.get('quantity') or 0)}</td>"
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
            "<th style='text-align:center;border-bottom:1px solid #ddd;padding:6px;'>수량</th>"
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


def _load_image_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    env_path = os.getenv("ALERT_REPORT_FONT_PATH", "").strip()
    candidates = [
        env_path,
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansKR-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumSquareR.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    max_width: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
    line_height: int,
) -> int:
    words = (text or "").split(" ")
    if not words:
        return y + line_height
    line = ""
    for w in words:
        candidate = (line + " " + w).strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width or not line:
            line = candidate
            continue
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
        line = w
    if line:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _build_report_image_png_with_browser(
    *,
    target_date: date,
    threshold_price: int,
    report: dict[str, Any],
) -> bytes:
    # Chromium 렌더링으로 폰트 fallback이 잘 동작해 한글 깨짐 가능성을 크게 줄인다.
    from playwright.sync_api import sync_playwright

    summary = report.get("summary") or {}
    below = report.get("below_threshold_list") or []
    top5 = summary.get("top5_lowest") or []
    shown_rows = below[:35]

    top5_items = "".join(
        f"<li>{escape(str(item.get('seller_name') or '-'))}: "
        f"{int(item.get('min_unit_price') or 0):,}원 "
        f"({escape(str(item.get('platform') or '-'))}) @ "
        f"{escape(str(item.get('min_time') or '-'))}</li>"
        for item in top5
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('seller_name') or '-'))}</td>"
        f"<td>{escape(str(item.get('platform') or '-'))}</td>"
        f"<td class='num'>{int(item.get('unit_price') or 0):,}원</td>"
        f"<td class='num'>{int(item.get('total_price') or 0):,}원</td>"
        f"<td class='qty'>{int(item.get('quantity') or 0)}</td>"
        f"<td>{escape(str(item.get('time') or '-'))}</td>"
        "</tr>"
        for item in shown_rows
    )
    if not table_rows:
        table_rows = "<tr><td colspan='6'>기준가 이하 거래처가 없습니다.</td></tr>"

    html = f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <style>
    body {{
      margin: 0;
      background: #f8fafc;
      font-family: "Noto Sans KR", "Noto Sans CJK KR", "NanumGothic", "Malgun Gothic", sans-serif;
      color: #0f172a;
    }}
    .wrap {{ width: 1200px; box-sizing: border-box; padding: 36px; }}
    h1 {{ margin: 0 0 8px; font-size: 42px; }}
    .sub {{ margin: 0 0 24px; font-size: 26px; color: #334155; }}
    h2 {{ margin: 20px 0 10px; font-size: 28px; color: #1e40af; }}
    .line {{ font-size: 21px; line-height: 1.6; }}
    ul {{ margin-top: 8px; font-size: 20px; line-height: 1.6; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #fff; font-size: 19px; }}
    th {{ background: #e2e8f0; text-align: left; border: 1px solid #cbd5e1; padding: 9px; }}
    td {{ border: 1px solid #e2e8f0; padding: 9px; }}
    .num {{ text-align: right; }}
    .qty {{ text-align: center; }}
    .note {{ margin-top: 12px; color: #64748b; font-size: 16px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Libre2 일일 모니터링 리포트 ({target_date:%Y-%m-%d})</h1>
    <p class="sub">기준가: {threshold_price:,}원</p>
    <h2>① 요약</h2>
    <div class="line">- 기준가 이하 셀러 수: {int(summary.get("below_threshold_seller_count") or 0)}곳</div>
    {"<div class='line'>- 최저 단가: <strong>" + f"{int(summary.get('global_min_price') or 0):,}원</strong> (" + escape(str(summary.get("global_min_seller") or "-")) + ") @ " + escape(str(summary.get("global_min_time") or "-")) + "</div>" if summary.get("global_min_price") is not None else ""}
    {"<div class='line' style='margin-top:6px;'>- 최저가격 상위 5개 거래처</div><ul>" + top5_items + "</ul>" if top5 else ""}
    <h2>② 기준가 이하 리스트</h2>
    <table>
      <thead>
        <tr>
          <th>판매처</th><th>채널</th><th style="text-align:right;">최저 단가</th>
          <th style="text-align:right;">총 금액</th><th style="text-align:center;">수량</th><th>시점</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
    {"<div class='note'>* 이미지에는 상위 35건만 표시되었습니다. 전체 건수: " + str(len(below)) + "건</div>" if len(below) > 35 else ""}
  </div>
</body>
</html>
"""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 2400})
            page.set_content(html, wait_until="domcontentloaded")
            clip = page.locator("body").bounding_box()
            if not clip:
                raise RuntimeError("failed to measure report body for screenshot")
            png = page.screenshot(
                clip={
                    "x": clip["x"],
                    "y": clip["y"],
                    "width": clip["width"],
                    "height": max(clip["height"], 900),
                },
                type="png",
            )
            return png
        finally:
            browser.close()


def _build_report_image_png(
    *,
    target_date: date,
    threshold_price: int,
    report: dict[str, Any],
) -> bytes:
    try:
        return _build_report_image_png_with_browser(
            target_date=target_date,
            threshold_price=threshold_price,
            report=report,
        )
    except Exception:
        # 브라우저 렌더 실패 시 기존 Pillow 렌더로 폴백.
        pass

    summary = report.get("summary") or {}
    below = report.get("below_threshold_list") or []
    top5 = summary.get("top5_lowest") or []

    width = 1200
    padding = 36
    line_height = 30
    section_gap = 26
    row_height = 34
    max_rows = 35
    shown_rows = below[:max_rows]

    base_rows = 14 + len(top5) + len(shown_rows)
    height = max(900, padding * 2 + base_rows * line_height + 240)

    image = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(image)
    font_title = _load_image_font(36)
    font_h2 = _load_image_font(26)
    font_body = _load_image_font(20)
    font_small = _load_image_font(17)

    content_x = padding
    content_w = width - (padding * 2)
    y = padding

    draw.text(
        (content_x, y),
        f"Libre2 일일 모니터링 리포트 ({target_date:%Y-%m-%d})",
        font=font_title,
        fill=(15, 23, 42),
    )
    y += 52
    draw.text(
        (content_x, y),
        f"기준가: {threshold_price:,}원",
        font=font_h2,
        fill=(30, 41, 59),
    )
    y += 52

    draw.text((content_x, y), "① 요약", font=font_h2, fill=(30, 64, 175))
    y += 40
    y = _draw_wrapped_text(
        draw,
        f"- 기준가 이하 셀러 수: {int(summary.get('below_threshold_seller_count') or 0)}곳",
        content_x,
        y,
        content_w,
        font_body,
        (15, 23, 42),
        line_height,
    )
    if summary.get("global_min_price") is not None:
        y = _draw_wrapped_text(
            draw,
            "- 최저 단가: "
            f"{int(summary.get('global_min_price') or 0):,}원 "
            f"({summary.get('global_min_seller') or '-'}) @ {summary.get('global_min_time') or '-'}",
            content_x,
            y,
            content_w,
            font_body,
            (15, 23, 42),
            line_height,
        )
    if top5:
        y = _draw_wrapped_text(
            draw,
            "- 최저가격 상위 5개 거래처",
            content_x,
            y,
            content_w,
            font_body,
            (15, 23, 42),
            line_height,
        )
        for item in top5:
            y = _draw_wrapped_text(
                draw,
                f"  · {item.get('seller_name') or '-'}: "
                f"{int(item.get('min_unit_price') or 0):,}원 "
                f"({item.get('platform') or '-'}) @ {item.get('min_time') or '-'}",
                content_x + 18,
                y,
                content_w - 18,
                font_body,
                (51, 65, 85),
                line_height,
            )

    y += section_gap
    draw.text((content_x, y), "② 기준가 이하 리스트", font=font_h2, fill=(30, 64, 175))
    y += 44

    headers = ["판매처", "채널", "최저 단가", "총 금액", "수량", "시점"]
    widths = [280, 140, 170, 170, 100, content_w - (280 + 140 + 170 + 170 + 100)]
    row_x = content_x
    for idx, h in enumerate(headers):
        draw.rectangle(
            [row_x, y, row_x + widths[idx], y + row_height],
            fill=(226, 232, 240),
            outline=(203, 213, 225),
            width=1,
        )
        if idx == 4:
            hb = draw.textbbox((0, 0), h, font=font_small)
            hw = hb[2] - hb[0]
            draw.text(
                (row_x + (widths[idx] - hw) / 2, y + 6),
                h,
                font=font_small,
                fill=(30, 41, 59),
            )
        else:
            draw.text((row_x + 8, y + 6), h, font=font_small, fill=(30, 41, 59))
        row_x += widths[idx]
    y += row_height

    if shown_rows:
        for item in shown_rows:
            row_x = content_x
            values = [
                str(item.get("seller_name") or "-"),
                str(item.get("platform") or "-"),
                f"{int(item.get('unit_price') or 0):,}원",
                f"{int(item.get('total_price') or 0):,}원",
                str(int(item.get("quantity") or 0)),
                str(item.get("time") or "-"),
            ]
            for idx, value in enumerate(values):
                draw.rectangle(
                    [row_x, y, row_x + widths[idx], y + row_height],
                    fill=(255, 255, 255),
                    outline=(226, 232, 240),
                    width=1,
                )
                if idx == 4:
                    vb = draw.textbbox((0, 0), value, font=font_small)
                    vw = vb[2] - vb[0]
                    draw.text(
                        (row_x + (widths[idx] - vw) / 2, y + 7),
                        value,
                        font=font_small,
                        fill=(15, 23, 42),
                    )
                else:
                    draw.text((row_x + 8, y + 7), value, font=font_small, fill=(15, 23, 42))
                row_x += widths[idx]
            y += row_height
    else:
        draw.rectangle(
            [content_x, y, content_x + content_w, y + row_height],
            fill=(255, 255, 255),
            outline=(226, 232, 240),
            width=1,
        )
        draw.text(
            (content_x + 8, y + 7),
            "기준가 이하 거래처가 없습니다.",
            font=font_small,
            fill=(71, 85, 105),
        )
        y += row_height

    if len(below) > max_rows:
        y += 16
        draw.text(
            (content_x, y),
            f"* 이미지에는 상위 {max_rows}건만 표시되었습니다. 전체 건수: {len(below)}건",
            font=font_small,
            fill=(100, 116, 139),
        )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _send_email(
    *,
    recipients: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    report_image_png: bytes | None = None,
) -> None:
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

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)
    if report_image_png:
        image_part = MIMEImage(report_image_png, _subtype="png")
        image_part.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"libre2-report-{datetime.now(KST):%Y%m%d}.png",
        )
        msg.attach(image_part)

    with smtplib.SMTP(host, port, timeout=20) as server:
        if use_tls:
            server.starttls()
        server.login(user, password)
        server.sendmail(mail_from, recipients, msg.as_string())


def run_daily_alert_job(
    reference_now: datetime | None = None,
    *,
    force_send: bool = False,
) -> dict[str, Any]:
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

        if not force_send:
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
            report_image_png=_build_report_image_png(
                target_date=target_date,
                threshold_price=conf.threshold_price,
                report=report,
            ),
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
                ON DUPLICATE KEY UPDATE
                    mall_count=VALUES(mall_count),
                    sent_at=VALUES(sent_at)
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
            "force_send": force_send,
        }
