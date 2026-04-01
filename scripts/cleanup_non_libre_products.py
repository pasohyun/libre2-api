import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

import mysql.connector

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config

LIBRE2_INCLUDE_PATTERNS = [
    r"프리스타일\s*리브레\s*2",
    r"리브레\s*2",
    r"freestyle\s*libre\s*2",
    r"libre\s*2",
]

NON_LIBRE_CGM_EXCLUDE_PATTERNS = [
    r"덱스콤",
    r"dexcom",
    r"\bg\s*7\b",
    r"\bg7\b",
    r"가디언",
    r"guardian",
    r"케어센스\s*에어",
]


def is_target_libre2_product(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return False

    if any(re.search(pattern, text, re.IGNORECASE) for pattern in NON_LIBRE_CGM_EXCLUDE_PATTERNS):
        return False

    return any(re.search(pattern, text, re.IGNORECASE) for pattern in LIBRE2_INCLUDE_PATTERNS)


def collect_non_target_rows() -> List[Tuple[int, str]]:
    conn = mysql.connector.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id, product_name FROM {config.DB_TABLE}")
            rows = cur.fetchall()
        return [(int(row[0]), row[1] or "") for row in rows if not is_target_libre2_product(row[1] or "")]
    finally:
        conn.close()


def delete_rows(row_ids: List[int]) -> int:
    if not row_ids:
        return 0

    conn = mysql.connector.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
    )
    try:
        placeholders = ",".join(["%s"] * len(row_ids))
        query = f"DELETE FROM {config.DB_TABLE} WHERE id IN ({placeholders})"
        with conn.cursor() as cur:
            cur.execute(query, tuple(row_ids))
            deleted = cur.rowcount
        conn.commit()
        return int(deleted or 0)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="DB에서 리브레2 비대상 상품(예: 덱스콤 G7) 행을 정리합니다."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 삭제를 수행합니다. 미지정 시 dry-run(조회만) 모드입니다.",
    )
    args = parser.parse_args()

    non_target_rows = collect_non_target_rows()
    print(f"비대상 상품 후보: {len(non_target_rows)}건")
    for row_id, title in non_target_rows[:30]:
        print(f"  - id={row_id} | {title[:100]}")
    if len(non_target_rows) > 30:
        print(f"  ... 외 {len(non_target_rows) - 30}건")

    if not args.apply:
        print("dry-run 모드입니다. 실제 삭제하려면 --apply 옵션을 사용하세요.")
        return

    deleted = delete_rows([row_id for row_id, _ in non_target_rows])
    print(f"삭제 완료: {deleted}건")


if __name__ == "__main__":
    main()
