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


def load_history() -> list[dict]:
    """최근 선정 이력. 같은 종목이 반복되지 않도록 쿨다운에 씁니다."""
    p = Path(cfg.HISTORY_FILE)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        log.warning("선정 이력을 읽지 못했습니다 — 새로 시작합니다")
        return []


def save_history(history: list[dict], entry: dict) -> None:
    p = Path(cfg.HISTORY_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = [entry] + [h for h in history if h.get("date") != entry["date"]]
    p.write_text(
        json.dumps(merged[: cfg.HISTORY_KEEP], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def _fmt_pct(pct: float | None) -> str:
    return f"{pct:+.2f}%" if pct is not None else "—"


# 인스타 캡션 하단 고정 문구. 매일 같은 자리에 같은 문장이 와야 브랜드로 각인됩니다.
CAPTION_FOOTER = """오늘의 움직임보다, 움직인 이유를 봅니다.

매일 아침 7시, 미국 증시에서 가장 주목할 종목 하나를
7장으로 정리해서 올립니다.

놓치지 않으려면 팔로우해 주세요 @{handle}
저장해두면 나중에 다시 꺼내보기 좋습니다."""

CAPTION_DISCLAIMER = "본 게시물은 공개된 시장 데이터를 정리한 투자 참고용 자료이며, 특정 종목의 매수·매도를 권유하지 않습니다."


def _build_caption(data: dict, summary: dict) -> str:
    """AI 가 쓴 본문 + 고정 팔로우 문구 + 해시태그를 조립합니다.

    본문만 AI 에 맡기고 팔로우 유도는 고정으로 둡니다. 매번 새로 쓰게 하면
    문구가 들쭉날쭉해져 브랜드로 쌓이지 않습니다.
    """
    f = data.get("focus", {})
    tk = f.get("ticker", "")
    name = f.get("name") or tk
    pct = f.get("pct")

    head = f"{name} ({tk}) {pct:+.2f}%" if tk and pct is not None else name
    body = (summary.get("instagram_caption") or "").strip()
    if not body:
        body = summary.get("p7_line") or summary.get("hook2") or ""

    footer = CAPTION_FOOTER.format(handle=cfg.INSTAGRAM_HANDLE)

    tags = list(cfg.INSTAGRAM_TAGS)
    if tk and f"#{tk}" not in tags:
        tags.insert(0, f"#{tk}")
    tag_line = " ".join(tags)

    parts = [head, "", body, "", footer, "", CAPTION_DISCLAIMER, "", tag_line]
    caption = "\n".join(p for p in parts if p is not None)
    return caption[:2000]


def _build_kakao_cards(data: dict, summary: dict, image_urls: list[str], link_url: str) -> list[dict]:
    """카드 7장에 대응하는 카카오 메시지. 각 장의 핵심 문장을 그대로 씁니다."""
    f = data.get("focus", {})
    tk = f.get("ticker", "")
    pct = f.get("pct")
    name = f.get("name") or tk
    tk_txt = f"{tk} {pct:+.2f}%" if tk and pct is not None else name

    def _first(items, key, sep=" · "):
        return sep.join(str(i.get(key, "")) for i in (items or [])[:2] if i.get(key))

    metrics = _first(summary.get("p4_metrics"), "value")
    if metrics:
        labels = _first(summary.get("p4_metrics"), "label")
        metrics = f"{labels} → {metrics}"

    cards = [
        {"title": f"{data['date_kr']} · {tk_txt}",
         "description": summary.get("p1_line") or summary.get("kakao_text", "")},
        {"title": summary.get("p2_headline") or "무슨 일이 있었나",
         "description": summary.get("p2_reaction", "")},
        {"title": summary.get("p3_headline") or "왜 중요한가",
         "description": summary.get("p3_note", "")},
        {"title": summary.get("p4_headline") or "진짜 실적",
         "description": summary.get("p4_note") or metrics},
        {"title": summary.get("p5_headline") or "지금 주가는",
         "description": summary.get("p5_read", "")},
        {"title": summary.get("p6_headline") or "시장의 기대",
         "description": summary.get("p6_read", "")},
        {"title": "오늘의 결론",
         "description": summary.get("conclusion") or summary.get("kr_line", "")},
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
    history = load_history()
    data = collect_all(history)

    focus = data.get("focus", {})
    if not focus.get("ticker"):
        log.error("오늘의 종목을 선정하지 못했습니다.")
        return 1

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
        "instagram_caption": _build_caption(data, summary),
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

    save_history(history, {
        "date": slug,
        "ticker": focus["ticker"],
        "name": focus.get("name", ""),
        "pct": focus.get("pct"),
        "rvol": focus.get("rvol"),
    })

    log.info("완료: %s · 카드 %d장", focus["ticker"], len(card_paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
