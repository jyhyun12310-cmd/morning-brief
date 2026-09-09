"""5장짜리 카드뉴스(JPEG)와 GitHub Pages 상세 페이지를 만듭니다.

인스타그램은 PNG 를 안 받습니다. 반드시 JPEG 로 저장합니다.
카러셀은 이미지 2~10장을 지원하며, 첫 장의 가로세로 비율에 맞춰 나머지가
잘리므로 5장 모두 1080x1350 로 통일합니다.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

import config as cfg

SRC = Path(__file__).parent
CARD_COUNT = 5


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


# pykrx 수급 딕셔너리 키 → 카드에 표시할 라벨 (기관합계는 "기관"으로 축약)
_FLOW_LABELS = (("외국인", "외국인"), ("기관합계", "기관"), ("개인", "개인"))


def _decorate_flow(flow: dict) -> list[dict]:
    """외국인·기관·개인 순매수(억원)를 카드용으로 가공."""
    out = []
    for key, label in _FLOW_LABELS:
        if key not in flow:
            continue
        v = flow[key]
        out.append({"label": label, "cls": _cls(v), "fmt": f"{v:+,}억"})
    return out


def _korea_indices(korea: dict) -> list[dict]:
    """collect.fetch_korea() 결과에서 코스피·코스닥만 뽑아 지수 스트립 포맷으로."""
    rows = [{"label": k, **korea[k]} for k in ("코스피", "코스닥") if k in korea]
    return _decorate(rows)


def _template_context(data: dict, summary: dict) -> dict:
    """5장 모두가 공유하는 렌더링 컨텍스트를 한 번만 계산합니다."""
    korea = data.get("korea", {})
    return {
        "date_kr": data["date_kr"],
        "weekday_kr": data["weekday_kr"],
        "s": summary,
        "dir_class": {"상승": "up", "하락": "down"}.get(summary["kr_direction"], "flat"),
        "indices": _decorate(data["us"]["indices"]),
        "macro": _decorate(data["us"]["macro"]),
        "korea_idx": _korea_indices(korea),
        "korea_flow": _decorate_flow(korea.get("수급", {})),
        "movers_up": _decorate(data["us"]["top_gainers"][:2]),
        "movers_down": _decorate(data["us"]["top_losers"][:2]),
    }


def render_cards(data: dict, summary: dict, docs_cards_dir: str, slug: str) -> list[str]:
    """카드 1~5 를 렌더링해 JPEG 5장의 경로 리스트를 반환합니다."""
    env = Environment(loader=FileSystemLoader(SRC), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("card.html")
    ctx = _template_context(data, summary)

    out_dir = Path(docs_cards_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(cfg.OUT_DIR)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--font-render-hinting=none"])
        page = browser.new_page(
            viewport={"width": cfg.CARD_WIDTH, "height": cfg.CARD_HEIGHT},
            device_scale_factor=1,
        )
        # 폰트는 첫 페이지에서만 기다리면 이후 goto 에서도 캐시되어 재사용됩니다
        first = True
        for n in range(1, CARD_COUNT + 1):
            page_html = tpl.render(card_num=n, **ctx)
            tmp = tmp_dir / f"_card-{n}.html"
            tmp.write_text(page_html, encoding="utf-8")

            page.goto(tmp.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            if first:
                page.evaluate("document.fonts.ready")  # 웹폰트 로딩 대기 — 안 하면 한글이 깨집니다
                page.wait_for_timeout(500)
                first = False
            else:
                page.wait_for_timeout(150)

            out_path = str(out_dir / f"{slug}-{n}.jpg")
            page.screenshot(path=out_path, type="jpeg", quality=92, full_page=False)
            paths.append(out_path)

        browser.close()

    return paths


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
  .cards {{ display:flex; flex-direction:column; gap:14px; }}
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
<div class="cards">{card_imgs}</div>
<h2>어젯밤 미국장</h2>
{issues}
<h2>지수</h2>
{quotes}
{korea_section}
{movers_section}
<h2>오늘 볼 것</h2>
<ul>{watch}</ul>
<footer>자동 생성된 개인용 시황 정리입니다. 투자 판단의 근거로 삼기 위한 자료가 아니며,
어떤 종목의 매수·매도도 권유하지 않습니다.</footer>
</div></body></html>"""


def render_detail_page(data: dict, summary: dict, slug: str) -> str:
    e = html.escape
    korea = data.get("korea", {})

    card_imgs = "".join(
        f'<img src="cards/{slug}-{n}.jpg" alt="{e(data["date_kr"])} 시황 카드 {n}">'
        for n in range(1, CARD_COUNT + 1)
    )

    issues = "".join(
        f"<p><b>{e(i['title'])}</b><br>{e(i['detail'])}</p>" for i in summary["us_issues"]
    )
    quotes = "".join(
        f'<div class="row"><span>{e(r["label"])}</span>'
        f'<span class="{r["cls"]}"><b>{r["fmt_last"]}</b>  {r["fmt_pct"]}</span></div>'
        for r in _decorate(data["us"]["indices"] + data["us"]["macro"])
    )

    korea_rows = _korea_indices(korea)
    flow_rows = _decorate_flow(korea.get("수급", {}))
    korea_section = ""
    if korea_rows or flow_rows:
        idx_html = "".join(
            f'<div class="row"><span>{e(r["label"])}</span>'
            f'<span class="{r["cls"]}"><b>{r["fmt_last"]}</b>  {r["fmt_pct"]}</span></div>'
            for r in korea_rows
        )
        flow_html = "".join(
            f'<div class="row"><span>{e(r["label"])} 순매수</span>'
            f'<span class="{r["cls"]}"><b>{r["fmt"]}</b></span></div>'
            for r in flow_rows
        )
        korea_section = f"<h2>전일 국내증시</h2>{idx_html}{flow_html}"

    up = _decorate(data["us"]["top_gainers"][:3])
    down = _decorate(data["us"]["top_losers"][:3])
    movers_section = ""
    if up or down:
        rows = "".join(
            f'<div class="row"><span>{e(r["ticker"])}</span>'
            f'<span class="{r["cls"]}"><b>{r["fmt_pct"]}</b></span></div>'
            for r in up + down
        )
        movers_section = f"<h2>특징주</h2>{rows}"

    watch = "".join(f"<li>{e(w)}</li>" for w in summary["watch"]) or "<li>특이 일정 없음</li>"

    page = DETAIL_TPL.format(
        date=data["date_kr"],
        slug=slug,
        card_imgs=card_imgs,
        issues=issues,
        quotes=quotes,
        korea_section=korea_section,
        movers_section=movers_section,
        watch=watch,
    )
    docs = Path(cfg.DOCS_DIR)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / f"{slug}.html").write_text(page, encoding="utf-8")
    (docs / "index.html").write_text(page, encoding="utf-8")  # 최신본
    return str(docs / f"{slug}.html")
