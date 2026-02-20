"""Generate a monthly LLM report and store it in DB.

Usage:
  python scripts/generate_monthly_report.py --month 2026-02 --threshold 90000 --channel naver --no-llm
"""

from __future__ import annotations

import argparse
from pathlib import Path

from api.database import SessionLocal, init_db
from api.services.monthly_report_builder import build_monthly_report, render_markdown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--threshold", required=True, type=int, help="threshold price (KRW)")
    parser.add_argument("--channel", default="naver")
    parser.add_argument("--crawl-schedule", default="00/12")
    parser.add_argument("--top-cards", type=int, default=10)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--out", default="monthly_report.md", help="markdown output path")

    args = parser.parse_args()

    init_db()

    db = SessionLocal()
    try:
        report = build_monthly_report(
            db,
            month=args.month,
            threshold_price=args.threshold,
            channel=args.channel,
            crawl_schedule=args.crawl_schedule,
            platforms=[args.channel],
            top_cards=args.top_cards,
            use_llm=not args.no_llm,
            store=True,
        )

        md = render_markdown(report)
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"✅ Stored monthly report to DB and wrote markdown: {args.out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()