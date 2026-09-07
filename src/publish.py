"""2단계: 카톡과 인스타로 발송.

GitHub Pages 에 이미지가 올라간 뒤에 실행해야 합니다.
한쪽이 실패해도 다른 쪽은 계속 시도합니다.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import config as cfg
import publish_instagram
import publish_kakao

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("publish")

TOKEN_DIR = f"{cfg.OUT_DIR}/tokens"


def main() -> int:
    if Path(cfg.OUT_DIR, "skip").exists():
        log.info("휴장일이라 발송을 건너뜁니다.")
        return 0

    state = json.loads(Path(cfg.OUT_DIR, "state.json").read_text(encoding="utf-8"))
    failures = []

    if os.environ.get("KAKAO_REFRESH_TOKEN"):
        try:
            publish_kakao.publish(
                title=state["kakao_title"],
                description=state["kakao_text"],
                image_url=state["image_url"],
                link_url=state["link_url"],
                token_dir=TOKEN_DIR,
            )
        except Exception as e:
            log.exception("카카오 발송 실패")
            failures.append(f"kakao: {e}")
    else:
        log.info("카카오 시크릿이 없어 건너뜁니다.")

    if os.environ.get("IG_ACCESS_TOKEN"):
        try:
            publish_instagram.publish(
                image_url=state["image_url"],
                caption=state["instagram_caption"],
                token_dir=TOKEN_DIR,
            )
        except Exception as e:
            log.exception("인스타그램 발송 실패")
            failures.append(f"instagram: {e}")
    else:
        log.info("인스타 시크릿이 없어 건너뜁니다.")

    if failures:
        log.error("실패 항목: %s", "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
