"""인스타그램 캐러셀(5장 한 게시물) 게시.

Instagram Content Publishing API 의 캐러셀 흐름 (2026년 기준, graph.instagram.com):
  1) 이미지마다 "자식 컨테이너"를 만든다 (is_carousel_item=true) — 이 상태로는 게시 안 됨
  2) 각 자식 컨테이너가 FINISHED 될 때까지 기다린다
  3) 자식 id 들을 모아 "부모(캐러셀) 컨테이너"를 만든다 (media_type=CAROUSEL)
  4) 부모 컨테이너도 FINISHED 될 때까지 기다린다
  5) 부모 컨테이너를 게시한다 (media_publish)

캐러셀은 2~10장이 가능하고, 전부 첫 장의 가로세로 비율에 맞춰 잘리므로
5장 모두 1080x1350 으로 통일해야 합니다 (render.py 가 이미 그렇게 만듭니다).

- 파일 업로드가 불가능합니다. 이미지가 공개 HTTPS URL 에 먼저 올라가 있어야 합니다.
- JPEG 만 받습니다. PNG 는 실패합니다.
- 본인 계정에만 올리면 앱 심사가 필요 없습니다 (개발 모드 + Instagram Tester, 또는 라이브 전환).
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


def _wait_until_public(url: str, attempts: int = 15, delay: int = 8) -> None:
    """GitHub Pages 배포 반영을 기다립니다.

    푸시 직후 바로 게시하면 인스타그램이 이미지를 못 읽어 실패합니다.
    """
    for i in range(attempts):
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(delay)
    raise RuntimeError(f"이미지 URL이 공개되지 않았습니다: {url}")


def _wait_finished(container_id: str, token: str, attempts: int = 20, delay: int = 5) -> None:
    """미디어 컨테이너가 FINISHED 될 때까지 대기 (자식·부모 컨테이너 공통)."""
    for _ in range(attempts):
        r = requests.get(
            f"{BASE}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=20,
        )
        status = r.json().get("status_code") if r.status_code == 200 else None
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"컨테이너 처리 오류 ({container_id}): {r.text}")
        time.sleep(delay)
    raise RuntimeError(f"컨테이너 처리 시간 초과: {container_id}")


def _create_child_container(image_url: str, token: str, user_id: str) -> str:
    r = requests.post(
        f"{BASE}/{user_id}/media",
        data={"image_url": image_url, "is_carousel_item": "true", "access_token": token},
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"자식 컨테이너 생성 실패 ({image_url}) {r.status_code}: {r.text}")
    return r.json()["id"]


def publish_carousel(*, image_urls: list[str], caption: str, token_dir: str) -> str:
    if not (2 <= len(image_urls) <= 10):
        raise ValueError(f"캐러셀은 2~10장만 가능합니다 (받은 장 수: {len(image_urls)})")

    token = os.environ["IG_ACCESS_TOKEN"]
    user_id = os.environ["IG_USER_ID"]

    for url in image_urls:
        _wait_until_public(url)

    # 1) 자식 컨테이너 5개 생성
    child_ids = [_create_child_container(url, token, user_id) for url in image_urls]
    log.info("자식 컨테이너 %d개 생성", len(child_ids))

    # 2) 전부 FINISHED 대기 — 하나라도 먼저 부모를 만들면 invalid_children 에러가 납니다
    for cid in child_ids:
        _wait_finished(cid, token)

    # 3) 부모(캐러셀) 컨테이너 생성
    r = requests.post(
        f"{BASE}/{user_id}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption[:CAPTION_LIMIT],
            "access_token": token,
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"캐러셀 컨테이너 생성 실패 {r.status_code}: {r.text}")
    carousel_id = r.json()["id"]

    # 4) 부모 컨테이너도 FINISHED 대기
    _wait_finished(carousel_id, token)

    # 5) 게시
    p = requests.post(
        f"{BASE}/{user_id}/media_publish",
        data={"creation_id": carousel_id, "access_token": token},
        timeout=60,
    )
    if p.status_code != 200:
        raise RuntimeError(f"게시 실패 {p.status_code}: {p.text}")

    media_id = p.json()["id"]
    log.info("인스타그램 캐러셀 게시 완료: %s (%d장)", media_id, len(image_urls))

    # 토큰 연장
    new_token = refresh_long_lived_token(token)
    if new_token and new_token != token:
        Path(token_dir).mkdir(parents=True, exist_ok=True)
        Path(token_dir, "ig_access_token.txt").write_text(new_token)
        log.info("인스타 토큰이 갱신되었습니다 — 시크릿에 저장합니다")

    return media_id
