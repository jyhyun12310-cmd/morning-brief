"""1단계: 데이터 수집 → 요약 → 카드·상세페이지 생성.

발송은 하지 않습니다. GitHub Pages 에 푸시된 다음 publish.py 가 발송합니다.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from pathlib import Path

import config as cfg
from collect import collect_all
from render import render_card, render_detail_page
from summarize import summarize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build")


def is_market_holiday(now: dt.datetime) -> bool:
    """한국 증시 휴장일이면 True. 판단이 불확실하면 False (그냥 실행)."""
    try:
        from pykrx import stock

        today = now.strftime("%Y%m%d")
        return stock.get_nearest_business_day_in_a_week(date=today, prev=True) != today
    except Exception:
        log.warning("휴장일 확인 실패 — 그대로 진행합니다")
        return False


def main() -> int:
    now = dt.datetime.now(cfg.KST)

    if "--force" not in sys.argv and is_market_holiday(now):
        log.info("오늘은 한국 증시 휴장일입니다. 브리핑을 건너뜁니다.")
        Path(cfg.OUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(cfg.OUT_DIR, "skip").write_text("holiday")
        return 0

    slug = now.strftime("%Y-%m-%d")

    log.info("데이터 수집 중")
    data = collect_all()

    log.info("요약 생성 중")
    summary = summarize(data)

    log.info("카드 렌더링 중")
    card_path = f"{cfg.DOCS_DIR}/cards/{slug}.jpg"
    render_card(data, summary, card_path)
    render_detail_page(data, summary, slug)

    state = {
        "slug": slug,
        "date_kr": data["date_kr"],
        "weekday_kr": data["weekday_kr"],
        "image_url": f"{cfg.PAGES_BASE}/cards/{slug}.jpg",
        "link_url": f"{cfg.PAGES_BASE}/{slug}.html",
        "kakao_title": f"{data['date_kr']} 조간 시황 · 코스피 {summary['kr_direction']} 전망",
        "kakao_text": summary["kakao_text"],
        "instagram_caption": summary["instagram_caption"],
    }

    Path(cfg.OUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(cfg.OUT_DIR, "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(cfg.OUT_DIR, "raw.json").write_text(
        json.dumps({"data": data, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log.info("완료: %s", card_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
