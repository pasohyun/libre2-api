#!/usr/bin/env python3
"""
Railway 배포된 API 테스트 스크립트
사용법: python scripts/test_api.py https://본인의-railway-url.up.railway.app
"""
import sys
import requests
from datetime import datetime

def test_api(base_url: str):
    """API 엔드포인트 테스트"""
    base_url = base_url.rstrip('/')
    
    print(f"🔍 API 테스트 시작: {base_url}\n")
    
    # 1. 헬스 체크
    print("1️⃣  헬스 체크...")
    try:
        response = requests.get(f"{base_url}/health", timeout=10)
        if response.status_code == 200:
            print(f"   ✅ Health check 성공: {response.json()}\n")
        else:
            print(f"   ❌ Health check 실패: {response.status_code}\n")
    except Exception as e:
        print(f"   ❌ 에러: {e}\n")
        return
    
    # 2. 최신 상품 데이터 확인
    print("2️⃣  최신 상품 데이터 조회...")
    try:
        response = requests.get(f"{base_url}/products/latest", timeout=10)
        if response.status_code == 200:
            data = response.json()
            snapshot_time = data.get("snapshot_time")
            count = data.get("count", 0)
            
            print(f"   ✅ 데이터 조회 성공!")
            print(f"   📊 상품 개수: {count}개")
            
            if snapshot_time:
                # 시간 파싱 및 표시
                try:
                    if isinstance(snapshot_time, str):
                        dt = datetime.fromisoformat(snapshot_time.replace('Z', '+00:00'))
                        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                        time_diff = now - dt.replace(tzinfo=None) if dt.tzinfo else now - dt
                        
                        print(f"   🕐 최신 스냅샷 시간: {snapshot_time}")
                        
                        # 오늘 12시와 비교
                        today_12pm = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
                        if dt.tzinfo:
                            today_12pm = dt.replace(hour=12, minute=0, second=0, microsecond=0)
                        
                        if dt.date() == today_12pm.date() and dt.hour == 12:
                            print(f"   ✅ 오늘 12시 크롤링 데이터 확인됨!")
                        elif dt.date() == today_12pm.date() and dt.hour == 0:
                            print(f"   ✅ 오늘 자정(00:00) 크롤링 데이터 확인됨!")
                        else:
                            hours_ago = time_diff.total_seconds() / 3600
                            print(f"   ⚠️  최신 데이터는 {hours_ago:.1f}시간 전입니다.")
                    else:
                        print(f"   🕐 최신 스냅샷 시간: {snapshot_time}")
                except Exception as e:
                    print(f"   🕐 최신 스냅샷 시간: {snapshot_time}")
            else:
                print(f"   ⚠️  데이터가 없습니다. 크롤링이 아직 실행되지 않았을 수 있습니다.")
            
            print()
        else:
            print(f"   ❌ 데이터 조회 실패: {response.status_code}")
            print(f"   응답: {response.text}\n")
    except Exception as e:
        print(f"   ❌ 에러: {e}\n")
    
    # 3. 최저가 상품 조회
    print("3️⃣  최저가 상품 조회 (상위 5개)...")
    try:
        response = requests.get(f"{base_url}/products/lowest?limit=5", timeout=10)
        if response.status_code == 200:
            data = response.json()
            count = len(data) if isinstance(data, list) else data.get("count", 0)
            print(f"   ✅ 최저가 상품 {count}개 조회 성공!\n")
        else:
            print(f"   ❌ 조회 실패: {response.status_code}\n")
    except Exception as e:
        print(f"   ❌ 에러: {e}\n")
    
    print("✅ 테스트 완료!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python scripts/test_api.py <Railway_URL>")
        print("예시: python scripts/test_api.py https://libre2-api-production-xxxx.up.railway.app")
        sys.exit(1)
    
    url = sys.argv[1]
    test_api(url)
