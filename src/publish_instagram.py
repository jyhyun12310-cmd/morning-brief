"""인스타그램 게시 (Instagram API with Instagram Login).

- 페이스북 페이지 연결이 필요 없습니다.
- 본인 계정에만 올리면 앱 심사도 필요 없습니다 (개발 모드 + Instagram Tester).
- 파일 업로드가 불가능합니다. 이미지가 공개 HTTPS URL 에 먼저 올라가 있어야 합니다.
- JPEG 만 받습니다. PNG 는 실패합니다.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
BASE = f"https://graph.instagram.com/{API_VERSION}"
CAPTION_LIMIT = 2200


def refresh_long_lived_token(token: str) -> str | None:
    """장기 토큰은 60일짜리이고 발급 24시간 뒤부터 갱신 가능합니다.

    매일 갱신하면 만료되지 않습니다. 24시간 규칙 때문에 실패해도 무시합니다.
    """
    try:
        r = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=20,
        )
        if r.status_code == 200:
            return r.json().get("access_token")
        log.warning("인스타 토큰 갱신 건너뜀: %s", r.text[:200])
    except Exception:
        log.exception("인스타 토큰 갱신 실패")
    return None


def _wait_until_public(url: str, attempts: int = 20, delay: int = 10) -> None:
    """GitHub Pages 배포 반영을 기다립니다.

    푸시 직후 바로 게시하면 인스타그램이 이미지를 못 읽어 실패합니다.
    """
    for i in range(attempts):
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                log.info("이미지 URL 확인 완료 (%d초)", i * delay)
                return
        except Exception:
            pass
        time.sleep(delay)
    raise RuntimeError(f"이미지 URL이 공개되지 않았습니다: {url}")


def publish(*, image_url: str, caption: str, token_dir: str) -> str:
    token = os.environ["IG_ACCESS_TOKEN"]
    user_id = os.environ["IG_USER_ID"]

    _wait_until_public(image_url)

    # 1단계 — 미디어 컨테이너 생성
    r = requests.post(
        f"{BASE}/{user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption[:CAPTION_LIMIT],
            "access_token": token,
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"컨테이너 생성 실패 {r.status_code}: {r.text}")
    creation_id = r.json()["id"]

    # 2단계 — 컨테이너가 준비될 때까지 대기
    for _ in range(12):
        s = requests.get(
            f"{BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=20,
        )
        status = s.json().get("status_code") if s.status_code == 200 else None
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"컨테이너 처리 오류: {s.text}")
        time.sleep(5)

    # 3단계 — 게시
    p = requests.post(
        f"{BASE}/{user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=60,
    )
    if p.status_code != 200:
        raise RuntimeError(f"게시 실패 {p.status_code}: {p.text}")

    media_id = p.json()["id"]
    log.info("인스타그램 게시 완료: %s", media_id)

    # 토큰 연장
    new_token = refresh_long_lived_token(token)
    if new_token and new_token != token:
        Path(token_dir).mkdir(parents=True, exist_ok=True)
        Path(token_dir, "ig_access_token.txt").write_text(new_token)
        log.info("인스타 토큰이 갱신되었습니다 — 시크릿에 저장합니다")

    return media_id
