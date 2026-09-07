"""카드 이미지(JPEG)와 GitHub Pages 상세 페이지를 만듭니다.

인스타그램은 PNG 를 안 받습니다. 반드시 JPEG 로 저장합니다.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

import config as cfg

SRC = Path(__file__).parent


def _cls(pct: float | None) -> str:
    if pct is None:
        return "flat"
    return "up" if pct > 0 else "down" if pct < 0 else "flat"


def _fmt_num(v: float) -> str:
    return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"


def _decorate(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        pct = r.get("pct")
        out.append(
            {
                **r,
                "cls": _cls(pct),
                "fmt_last": _fmt_num(r["last"]),
                "fmt_pct": f"{pct:+.2f}%" if pct is not None else "—",
            }
        )
    return out


def render_card(data: dict, summary: dict, out_path: str) -> str:
    env = Environment(loader=FileSystemLoader(SRC), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("card.html")

    dir_class = {"상승": "up", "하락": "down"}.get(summary["kr_direction"], "flat")

    page_html = tpl.render(
        date_kr=data["date_kr"],
        weekday_kr=data["weekday_kr"],
        s=summary,
        dir_class=dir_class,
        indices=_decorate(data["us"]["indices"]),
        macro=_decorate(data["us"]["macro"] + data["us"]["korea_proxy"]),
    )

    tmp = Path(cfg.OUT_DIR) / "_card.html"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(page_html, encoding="utf-8")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--font-render-hinting=none"])
        page = browser.new_page(
            viewport={"width": cfg.CARD_WIDTH, "height": cfg.CARD_HEIGHT},
            device_scale_factor=1,
        )
        page.goto(tmp.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")   # 웹폰트 로딩 대기 — 안 하면 한글이 깨집니다
        page.wait_for_timeout(600)
        page.screenshot(path=out_path, type="jpeg", quality=92, full_page=False)
        browser.close()

    return out_path


DETAIL_TPL = """<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{date} 조간 시황</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  body {{ margin:0; background:#0F1720; color:#E9EEF4;
         font-family:Pretendard,"Noto Sans KR",sans-serif;
         font-variant-numeric:tabular-nums; }}
  .wrap {{ max-width:720px; margin:0 auto; padding:28px 22px 72px; }}
  img {{ width:100%; border-radius:14px; display:block; }}
  h2 {{ font-size:20px; font-weight:700; color:#7E8D9E; margin:38px 0 14px;
        letter-spacing:-.02em; }}
  .row {{ display:flex; justify-content:space-between; padding:13px 0;
          border-bottom:1px solid #26333F; font-size:17px; letter-spacing:-.02em; }}
  .row b {{ font-weight:700; }}
  .up {{ color:#FF4D42; }} .down {{ color:#4C8DFF; }} .flat {{ color:#7E8D9E; }}
  p {{ font-size:17px; line-height:1.7; color:#B9C5D2; letter-spacing:-.02em; }}
  li {{ font-size:17px; line-height:1.75; letter-spacing:-.02em; }}
  footer {{ margin-top:44px; font-size:14px; color:#5E6C7C; line-height:1.7; }}
</style></head><body><div class="wrap">
<img src="cards/{slug}.jpg" alt="{date} 시황 카드">
<h2>어젯밤 미국장</h2>
{issues}
<h2>지수</h2>
{quotes}
<h2>오늘 볼 것</h2>
<ul>{watch}</ul>
<footer>자동 생성된 개인용 시황 정리입니다. 투자 판단의 근거로 삼기 위한 자료가 아니며,
어떤 종목의 매수·매도도 권유하지 않습니다.</footer>
</div></body></html>"""


def render_detail_page(data: dict, summary: dict, slug: str) -> str:
    e = html.escape
    issues = "".join(
        f"<p><b>{e(i['title'])}</b><br>{e(i['detail'])}</p>" for i in summary["us_issues"]
    )
    quotes = "".join(
        f'<div class="row"><span>{e(r["label"])}</span>'
        f'<span class="{r["cls"]}"><b>{r["fmt_last"]}</b>  {r["fmt_pct"]}</span></div>'
        for r in _decorate(
            data["us"]["indices"] + data["us"]["macro"] + data["us"]["korea_proxy"]
        )
    )
    watch = "".join(f"<li>{e(w)}</li>" for w in summary["watch"]) or "<li>특이 일정 없음</li>"

    page = DETAIL_TPL.format(
        date=data["date_kr"], slug=slug, issues=issues, quotes=quotes, watch=watch
    )
    docs = Path(cfg.DOCS_DIR)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / f"{slug}.html").write_text(page, encoding="utf-8")
    (docs / "index.html").write_text(page, encoding="utf-8")  # 최신본
    os.makedirs(docs / "cards", exist_ok=True)
    return str(docs / f"{slug}.html")
