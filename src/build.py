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


def _build_kakao_cards(data: dict, summary: dict, image_urls: list[str], link_url: str) -> list[dict]:
    """카드 5장에 대응하는 카카오 메시지. 숫자는 원본 데이터에서 직접 만듭니다."""
    f = data.get("focus", {})
    market = data.get("market", {})
    tk = f.get("ticker", "")
    pct = f.get("pct")
    tk_txt = f"{tk} {pct:+.2f}%" if tk and pct is not None else "오늘의 종목"

    def _line(rows, n=4):
        return " · ".join(
            f"{r['label']} {r['pct']:+.2f}%" for r in (rows or [])[:n] if r.get("pct") is not None
        )

    val = f.get("valuation") or {}
    val_bits = []
    if val.get("per") is not None:
        val_bits.append(f"PER {val['per']:.1f}")
    if val.get("pbr") is not None:
        val_bits.append(f"PBR {val['pbr']:.1f}")
    ern = f.get("earnings") or {}
    if ern.get("surprise") is not None:
        val_bits.append(f"EPS {'Beat' if ern.get('beat') else 'Miss'} {ern['surprise']:+.1f}%")

    a = f.get("analyst") or {}
    tgt_txt = (
        f"목표가 평균 ${a['target_mean']:,.0f}"
        + (f" · 상승여력 {a['upside']:+.1f}%" if a.get("upside") is not None else "")
        if a.get("target_mean") else summary.get("wallst_note", "")
    )

    cards = [
        {"title": f"{data['date_kr']} · {tk_txt}",
         "description": summary.get("kakao_text", "")},
        {"title": "간밤 시장 맥락",
         "description": _line(market.get("indices")) or summary.get("macro_line", "")},
        {"title": f"{tk} 펀더멘털",
         "description": " · ".join(val_bits) or summary.get("fundamental_note", "")},
        {"title": "밸류체인 · 월가 시각",
         "description": tgt_txt or summary.get("chain_note", "")},
        {"title": "오늘의 3줄 요약",
         "description": " / ".join(summary.get("summary3", [])) or summary.get("kr_line", "")},
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
