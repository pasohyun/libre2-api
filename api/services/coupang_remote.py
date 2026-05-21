# api/services/coupang_remote.py
"""
회사 서버(사내망)에서 도는 쿠팡 크롤러를 SSH로 fire-and-forget 트리거.

전제:
- 회사 서버에서는 crontab으로 같은 스크립트가 정기 실행되고 있으며,
  결과는 공통 DB에 적재된다.
- 본 모듈은 "수동 크롤링" 버튼 클릭 시 사내망 SSH로 즉시 한 번 더 실행시키는 용도.
- 사내망 전용이므로 호출자가 회사 와이파이/VPN 연결 상태여야 한다.
"""
from __future__ import annotations

import logging
import os
import shlex
import socket
from dataclasses import dataclass
from typing import Optional

import paramiko

logger = logging.getLogger(__name__)


@dataclass
class CoupangSSHConfig:
    host: str
    port: int
    user: str
    password: str
    workdir: str
    python: str
    module: str

    @classmethod
    def from_env(cls) -> Optional["CoupangSSHConfig"]:
        host = os.getenv("COUPANG_SSH_HOST", "").strip()
        user = os.getenv("COUPANG_SSH_USER", "").strip()
        password = os.getenv("COUPANG_SSH_PASSWORD", "")
        if not host or not user or not password:
            return None
        return cls(
            host=host,
            port=int(os.getenv("COUPANG_SSH_PORT", "2220")),
            user=user,
            password=password,
            workdir=os.getenv(
                "COUPANG_SSH_WORKDIR",
                "/home/develop/daewoong/libre2-monitor/libre2-api",
            ),
            python=os.getenv("COUPANG_SSH_PYTHON", ".venv/bin/python"),
            module=os.getenv("COUPANG_SSH_MODULE", "scripts.crawl_coupang_brand"),
        )


def trigger_coupang_crawl(*, connect_timeout: float = 10.0) -> dict:
    """
    회사 서버에 SSH로 접속해 쿠팡 크롤러를 nohup 백그라운드로 띄우고 바로 연결을 끊는다.
    스크립트 종료를 기다리지 않으므로 호출자는 거의 즉시 응답을 받는다.
    """
    cfg = CoupangSSHConfig.from_env()
    if cfg is None:
        return {
            "status": "skipped",
            "message": "COUPANG_SSH_* 환경변수가 설정되지 않았습니다.",
        }

    # crontab과 동일한 명령어를 nohup으로 감싸 백그라운드 실행
    # 로그는 회사 서버의 coupang_manual.log 로 남긴다 (정기 실행 로그와 분리)
    remote_cmd = (
        f"cd {shlex.quote(cfg.workdir)} && "
        f"nohup {cfg.python} -m {cfg.module} "
        f">> coupang_manual.log 2>&1 < /dev/null &"
    )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.user,
            password=cfg.password,
            timeout=connect_timeout,
            banner_timeout=connect_timeout,
            auth_timeout=connect_timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        # exec_command는 비차단으로 명령을 보낸다.
        # nohup ... & 로 백그라운드화했으므로 채널을 바로 닫아도 서버 측 프로세스는 계속 돈다.
        client.exec_command(f"bash -lc {shlex.quote(remote_cmd)}", timeout=connect_timeout)
        logger.info("Coupang remote crawl triggered on %s:%s", cfg.host, cfg.port)
        return {
            "status": "triggered",
            "host": cfg.host,
            "module": cfg.module,
        }
    except (paramiko.SSHException, socket.error, OSError) as e:
        logger.exception("Coupang SSH trigger failed")
        return {"status": "error", "message": f"SSH trigger failed: {e}"}
    finally:
        try:
            client.close()
        except Exception:
            pass
