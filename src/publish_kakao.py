"""카카오톡 '나에게 보내기' — 카드 5장을 5개의 메시지로 순서대로 보냅니다.

친구에게 보내는 API 와 달리 별도 심사가 필요 없습니다.
액세스 토큰은 6시간짜리라 매번 리프레시 토큰으로 새로 받고, 그 토큰 하나로
5번의 발송을 처리합니다 (매번 새로 리프레시할 필요 없음).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

DESC_LIMIT = 190  # 피드 템플릿 설명 한도(약 200자)에 여유를 둡니다
BETWEEN_SENDS_SEC = 1.2  # 연속 발송 사이 살짝 여유를 둡니다


def refresh_access_token() -> tuple[str, str | None]:
    """리프레시 토큰으로 액세스 토큰을 받습니다.

    반환: (access_token, 새 refresh_token 또는 None)
    카카오는 리프레시 토큰의 남은 유효기간이 1개월 미만일 때만
    새 리프레시 토큰을 함께 내려줍니다. 그때 반드시 저장해야 합니다.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": os.environ["KAKAO_REST_API_KEY"],
        "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
    }
    if os.environ.get("KAKAO_CLIENT_SECRET"):
        payload["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]

    r = requests.post(TOKEN_URL, data=payload, timeout=20)
    r.raise_for_status()
    body = r.json()
    return body["access_token"], body.get("refresh_token")


def _send_one(access_token: str, *, title: str, description: str, image_url: str, link_url: str) -> None:
    template = {
        "object_type": "feed",
        "content": {
            "title": title,
            "description": description[:DESC_LIMIT],
            "image_url": image_url,
            "image_width": 1080,
            "image_height": 1350,
            "link": {"web_url": link_url, "mobile_web_url": link_url},
        },
        "buttons": [
            {"title": "자세히 보기", "link": {"web_url": link_url, "mobile_web_url": link_url}}
        ],
    }

    r = requests.post(
        MEMO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        },
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"카카오 발송 실패 {r.status_code}: {r.text}")


def publish_series(cards: list[dict], *, token_dir: str) -> None:
    """cards: [{"title", "description", "image_url", "link_url"}, ...] 순서대로 발송.

    하나가 실패해도 나머지는 계속 시도하고, 끝에 실패 목록을 모아 예외로 알립니다.
    """
    access, new_refresh = refresh_access_token()
    if new_refresh:
        Path(token_dir).mkdir(parents=True, exist_ok=True)
        Path(token_dir, "kakao_refresh_token.txt").write_text(new_refresh)
        log.info("카카오 리프레시 토큰이 갱신되었습니다 — 시크릿에 저장합니다")

    failures = []
    for i, card in enumerate(cards, start=1):
        try:
            _send_one(
                access,
                title=card["title"],
                description=card["description"],
                image_url=card["image_url"],
                link_url=card["link_url"],
            )
            log.info("카카오 %d/%d 발송 완료", i, len(cards))
        except Exception:
            log.exception("카카오 %d/%d 발송 실패", i, len(cards))
            failures.append(i)
        time.sleep(BETWEEN_SENDS_SEC)

    if failures:
        raise RuntimeError(f"카카오 발송 실패: {len(failures)}/{len(cards)}장 (카드 {failures})")
