#!/usr/bin/env python3
"""
Railway에서 실행되는 크롤링 스케줄러
매일 12시(정오)와 24시(자정)에 크롤링 실행
"""
import schedule
import time
from datetime import datetime
from scripts.crawl_naver import run_crawling

def job():
    """크롤링 작업 실행"""
    print(f"\n{'='*60}")
    print(f"🕐 스케줄러 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    try:
        run_crawling()
        print(f"\n✅ 크롤링 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"\n❌ 크롤링 실패: {e}")
        import traceback
        traceback.print_exc()
    print(f"{'='*60}\n")

if __name__ == "__main__":
    # 매일 12시(정오)와 24시(자정)에 실행
    schedule.every().day.at("12:00").do(job)
    schedule.every().day.at("00:00").do(job)
    
    print("⏰ 크롤링 스케줄러가 시작되었습니다.")
    print("📅 매일 12:00(정오)와 00:00(자정)에 자동 크롤링이 실행됩니다.")
    print("🛑 종료하려면 Ctrl+C를 누르세요.\n")
    
    # 즉시 한 번 실행 (선택사항)
    # job()
    
    # 스케줄러 실행 루프
    while True:
        schedule.run_pending()
        time.sleep(60)  # 1분마다 스케줄 확인
