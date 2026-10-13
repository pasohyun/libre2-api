"""네이버 크롤링 동작 점검 (DB 저장 없음, 읽기 전용).

무엇을 확인하는가
  1) 구 경로: openapi.naver.com /v1/search/shop.json 이 아직 살아있는지
  2) 신규 경로: search.shopping.naver.com /ns/v1/search/paged-products 전량 수집
  3) 신규 응답을 기존 crawl_naver.py 필터·수량분석 로직에 통과시켜
     실제로 DB에 들어갈 행이 몇 건 나오는지

사용법:
    python3 -m scripts.check_naver_crawl            # 프록시 없이(한국 IP 전제)
    python3 -m scripts.check_naver_crawl --proxy    # Bright Data KR 주거용 경유
"""
import argparse
import os
import sys
import time
import types
import urllib.parse
import urllib.request

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings()
load_dotenv()
load_dotenv("proxy.env")

# crawl_naver.py 는 mysql.connector 를 모듈 최상단에서 import 한다.
# 이 점검은 DB를 건드리지 않으므로, 미설치 환경에서도 순수 로직을 재사용할 수 있게 stub 을 끼운다.
if "mysql" not in sys.modules:
    try:
        import mysql.connector  # noqa: F401
    except ImportError:
        _mysql = types.ModuleType("mysql")
        _connector = types.ModuleType("mysql.connector")
        _connector.connect = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("mysql.connector stub: DB 접속은 이 점검 스크립트에서 지원하지 않음")
        )
        _mysql.connector = _connector
        sys.modules["mysql"] = _mysql
        sys.modules["mysql.connector"] = _connector

import config
from scripts.crawl_naver import (  # noqa: E402
    analyze_product,
    _is_target_libre2_product,
    _normalize_mall_name,
)

KEYWORD = os.getenv("SEARCH_KEYWORD", config.SEARCH_KEYWORD)
ENC = urllib.parse.quote(KEYWORD)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
NS_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": f"https://search.shopping.naver.com/ns/search?query={ENC}",
}

# 신규 API 는 카테고리를 한글명이 아닌 ID 로 준다.
# 기존 valid_categories(혈당계/혈당측정기/당뇨관리용품/당뇨) 에 대응하는 ID 화이트리스트.
ALLOWED_SCAT_IDS = {"50002066"}   # 혈당계 계열
ALLOWED_MCAT_IDS = {"50000065"}

ACCESSORY_KEYWORDS = [
    "스크린 프로텍터", "화면 보호", "보호필름", "보호 필름",
    "케이스", "커버", "파우치", "홀스터", "랜야드",
    "충전 케이블", "충전케이블", "USB 케이블",
    "스킨그립", "스킨 그립", "오버패치",
    "클립", "카라비너", "벨트 클립",
]


def _proxies(use_proxy):
    if not use_proxy:
        return None
    server = os.getenv("BRIGHT_DATA_PROXY")
    user = os.getenv("BRIGHT_DATA_USERNAME")
    pwd = os.getenv("BRIGHT_DATA_PASSWORD")
    if not all((server, user, pwd)):
        print("  [WARN] Bright Data 크리덴셜 없음 → 직접 호출로 진행")
        return None
    url = server.replace("http://", f"http://{user}:{pwd}@")
    return {"http": url, "https": url}


# ---------------------------------------------------------------- 1) 구 경로
def check_legacy_api():
    print("=" * 72)
    print("1) 구 경로: openapi.naver.com /v1/search/shop.json")
    print("=" * 72)

    cid = config.NAVER_CLIENT_ID
    csec = config.NAVER_CLIENT_SECRET
    url = (f"https://openapi.naver.com/v1/search/shop.json"
           f"?query={ENC}&display=10&start=1&sort=sim")

    req = urllib.request.Request(url)
    if cid and csec:
        print(f"  크리덴셜: 있음 (client_id len={len(cid)})")
        req.add_header("X-Naver-Client-Id", cid)
        req.add_header("X-Naver-Client-Secret", csec)
    else:
        print("  크리덴셜: 없음 → 인증 없이 호출해 엔드포인트 생존 여부만 본다")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(f"  status={resp.getcode()} len={len(body)}")
            print(f"  head: {body[:200]}")
            print("  => 정상 응답")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"  HTTPError status={e.code}")
        print(f"  body: {body[:300]}")
        if e.code == 401:
            print("  => 401: 엔드포인트는 살아있고 인증만 실패 (키가 로컬에 없음)")
        elif e.code in (403, 404, 410):
            print(f"  => {e.code}: 엔드포인트 폐지/권한 회수 가능성")
        else:
            print(f"  => 기타 오류 {e.code}")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
    print()


# ------------------------------------------------------------- 2) 신규 경로
def fetch_ns_all(use_proxy=False, page_size=100, max_pages=20):
    proxies = _proxies(use_proxy)
    items = []
    cursor = 1
    pages = 0
    total = None

    while pages < max_pages:
        url = ("https://search.shopping.naver.com/ns/v1/search/paged-products"
               f"?cursor={cursor}&pageSize={page_size}&query={ENC}")
        t0 = time.time()
        try:
            r = requests.get(url, headers=NS_HEADERS, proxies=proxies,
                             timeout=45, verify=False)
        except Exception as e:
            print(f"  page{pages+1} cursor={cursor} FAIL: {type(e).__name__}: {e}")
            break
        dt = time.time() - t0

        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            print(f"  page{pages+1} cursor={cursor} status={r.status_code} "
                  f"ct={r.headers.get('content-type','')[:30]} → 차단/비정상, 중단")
            print(f"    head: {r.text[:160]!r}")
            break

        d = r.json()["data"]
        batch = d.get("data") or []
        total = d.get("total")
        items.extend(batch)
        pages += 1
        print(f"  page{pages} cursor={cursor} items={len(batch)} "
              f"누적={len(items)}/{total} {dt:.1f}s")

        if not d.get("hasMore"):
            break
        nxt = d.get("cursor")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)

    return items, total


def check_ns_api(use_proxy=False):
    print("=" * 72)
    print(f"2) 신규 경로: ns/v1/search/paged-products  "
          f"({'Bright Data KR 프록시' if use_proxy else '직접 호출'})")
    print("=" * 72)
    print(f"  keyword: {KEYWORD!r}")
    items, total = fetch_ns_all(use_proxy=use_proxy)
    print(f"  => 수집 {len(items)}건 (total={total})")
    print()
    return items


# --------------------------------------------- 3) 기존 필터 파이프라인 통과
def run_pipeline(items):
    print("=" * 72)
    print("3) 기존 crawl_naver 필터·수량분석 파이프라인 통과 결과")
    print("=" * 72)

    stats = {
        "non_target": 0, "category": 0, "accessory": 0,
        "qty_pending": 0, "under_65k": 0, "no_price": 0, "kept": 0,
    }
    rows = []
    # 수량 미확정 계산방식은 기존 코드에서 DB 저장 제외 대상이다.
    from scripts.crawl_naver import MANUAL_QUANTITY_PENDING_METHODS

    for it in items:
        title = (it.get("productName") or "").strip()
        if not _is_target_libre2_product(title):
            stats["non_target"] += 1
            continue

        scat = str(it.get("sCatId") or "")
        mcat = str(it.get("mCatId") or "")
        if scat not in ALLOWED_SCAT_IDS and mcat not in ALLOWED_MCAT_IDS:
            stats["category"] += 1
            continue

        low = title.lower()
        if any(k.lower() in low for k in ACCESSORY_KEYWORDS):
            import re as _re
            if not _re.search(r"센서\s*\d+\s*(개|팩|세트|박스)", title):
                stats["accessory"] += 1
                continue

        total_price = int(it.get("discountedSalePrice")
                          or it.get("salePrice") or 0)
        if total_price <= 0:
            stats["no_price"] += 1
            continue

        link = (it.get("productUrl") or {}).get("pcUrl") or ""
        mall = _normalize_mall_name(it.get("mallName") or "")

        qty, unit_price, method = analyze_product(title, total_price, link, None)

        if method in MANUAL_QUANTITY_PENDING_METHODS:
            stats["qty_pending"] += 1
            continue
        if unit_price < 65000:
            stats["under_65k"] += 1
            continue

        imgs = it.get("images") or []
        rows.append({
            "product_name": title,
            "unit_price": unit_price,
            "quantity": qty,
            "total_price": total_price,
            "mall_name": mall,
            "calc_method": method,
            "link": link,
            "image_url": imgs[0].get("imageUrl") if imgs else "",
            # 신규 API 만 주는 힌트 (수량 추정 개선용)
            "_options": len(it.get("catalogPurchaseOptions") or []),
        })
        stats["kept"] += 1

    print(f"  입력 {len(items)}건")
    for k, v in stats.items():
        print(f"    {k:12}: {v}")
    print()

    if rows:
        rows.sort(key=lambda r: r["unit_price"])
        print(f"  --- 최저 단가 상위 15건 (기준가 {config.TARGET_PRICE:,}원) ---")
        for r in rows[:15]:
            flag = "★" if r["unit_price"] <= config.TARGET_PRICE else " "
            print(f"  {flag} {r['unit_price']:>8,}원/개  x{r['quantity']}  "
                  f"총{r['total_price']:>9,}  [{r['mall_name'][:10]:<10}] "
                  f"({r['calc_method']}, opt={r['_options']}) {r['product_name'][:42]}")
        below = [r for r in rows if r["unit_price"] <= config.TARGET_PRICE]
        malls = {}
        for r in rows:
            malls[r["mall_name"]] = malls.get(r["mall_name"], 0) + 1
        print(f"\n  기준가 이하: {len(below)}건 / 전체 {len(rows)}건")
        print(f"  판매처 수: {len(malls)}개  상위: "
              f"{sorted(malls.items(), key=lambda x: -x[1])[:6]}")
        opt_rich = sum(1 for r in rows if r["_options"] > 0)
        print(f"  catalogPurchaseOptions 보유: {opt_rich}/{len(rows)}건 "
              f"(수량 추정 개선 여지)")
    else:
        print("  [WARN] 통과한 행이 0건 — 필터 또는 수집 단계 점검 필요")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", action="store_true",
                    help="Bright Data KR 주거용 프록시 경유")
    ap.add_argument("--skip-legacy", action="store_true")
    args = ap.parse_args()

    print(f"\n네이버 크롤링 점검  keyword={KEYWORD!r}  "
          f"(DB 저장 없음 / 읽기 전용)\n")
    if not args.skip_legacy:
        check_legacy_api()
    items = check_ns_api(use_proxy=args.proxy)
    if items:
        run_pipeline(items)
    else:
        print("수집 0건 → 파이프라인 점검 생략")


if __name__ == "__main__":
    main()
