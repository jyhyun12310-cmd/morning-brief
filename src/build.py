"""1단계: 데이터 수집 → 요약 → 카드 5장·상세페이지 생성.

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
from render import render_cards, render_detail_page
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


def _fmt_pct(pct: float | None) -> str:
    return f"{pct:+.2f}%" if pct is not None else "—"


def _build_kakao_cards(data: dict, summary: dict, image_urls: list[str], link_url: str) -> list[dict]:
    """카드 5장 각각에 대응하는 카카오 메시지(제목+설명)를 실제 데이터로 구성합니다.

    숫자가 들어가는 설명은 요약 JSON 이 아니라 원본 데이터에서 직접 만들어
    카드 이미지에 찍힌 숫자와 어긋나지 않게 합니다.
    """
    date_kr = data["date_kr"]
    korea = data.get("korea", {})

    titles = [it["title"] for it in summary["us_issues"]]
    issues_desc = " · ".join(titles) if titles else "핵심 이슈 3건"

    kospi = korea.get("코스피")
    kosdaq = korea.get("코스닥")
    flow = korea.get("수급", {})
    kr_bits = []
    if kospi:
        kr_bits.append(f"코스피 {_fmt_pct(kospi.get('pct'))}")
    if kosdaq:
        kr_bits.append(f"코스닥 {_fmt_pct(kosdaq.get('pct'))}")
    if "외국인" in flow:
        kr_bits.append(f"외국인 {flow['외국인']:+,}억")
    kr_desc = " · ".join(kr_bits) if kr_bits else "국내증시 데이터 확인"

    watch_desc = " · ".join(summary.get("watch", [])) or "특이 일정 없음"

    cards = [
        {
            "title": f"{date_kr} 조간 시황 · 코스피 {summary['kr_direction']} 전망",
            "description": summary["kakao_text"],
        },
        {
            "title": "어젯밤 미국 지수 마감",
            "description": summary.get("us_summary_line") or "지수 데이터는 카드에서 확인해 주세요.",
        },
        {
            "title": "어젯밤 미국장 핵심 이슈",
            "description": issues_desc,
        },
        {
            "title": "오늘 한국시장 체크",
            "description": kr_desc,
        },
        {
            "title": "오늘의 체크포인트",
            "description": watch_desc,
        },
    ]
    for card, url in zip(cards, image_urls):
        card["image_url"] = url
        card["link_url"] = link_url
    return cards


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

    log.info("카드 5장 렌더링 중")
    card_paths = render_cards(data, summary, f"{cfg.DOCS_DIR}/cards", slug)
    render_detail_page(data, summary, slug)

    image_urls = [f"{cfg.PAGES_BASE}/cards/{slug}-{n}.jpg" for n in range(1, len(card_paths) + 1)]
    link_url = f"{cfg.PAGES_BASE}/{slug}.html"

    state = {
        "slug": slug,
        "date_kr": data["date_kr"],
        "weekday_kr": data["weekday_kr"],
        "link_url": link_url,
        "instagram_image_urls": image_urls,
        "instagram_caption": summary["instagram_caption"],
        "kakao_cards": _build_kakao_cards(data, summary, image_urls, link_url),
    }

    Path(cfg.OUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(cfg.OUT_DIR, "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(cfg.OUT_DIR, "raw.json").write_text(
        json.dumps({"data": data, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log.info("완료: 카드 %d장 (%s ...)", len(card_paths), card_paths[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
