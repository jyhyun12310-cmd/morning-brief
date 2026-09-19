"""이슈 카드뉴스 5장(JPEG)과 GitHub Pages 상세 페이지를 만듭니다.

종목 브리핑(render.py)과 완전히 분리돼 있습니다. 템플릿도 issue_card.html 로
따로 쓰고, 같은 계정에 올라가도 피드에서 시리즈가 구분되도록 비주얼을
일부러 반대쪽으로 잡았습니다.

인스타그램은 PNG 를 안 받습니다. 반드시 JPEG 로 저장합니다.
캐러셀은 첫 장 비율에 맞춰 나머지가 잘리므로 5장 모두 1080x1350 으로 통일합니다.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

import config as cfg

log = logging.getLogger(__name__)

SRC = Path(__file__).parent
CARD_COUNT = 5

CARD_LABELS = {
    1: "오늘의 미장 이슈",
    2: "무슨 일이",
    3: "왜 중요한가",
    4: "수혜와 피해",
    5: "한 줄 정리",
}

UP, DOWN, FLAT = "#FF3B30", "#2B4DFF", "#8A817C"


# ══ 포맷터 ══════════════════════════════════════════════

def _cls(pct: float | None) -> str:
    if pct is None:
        return "fl"
    return "up" if pct > 0 else "dn" if pct < 0 else "fl"


def _fmt_pct(pct: float | None) -> str:
    return f"{pct:+.2f}%" if pct is not None else "—"


def _short_name(name: str, limit: int = 20) -> str:
    """스크리너가 주는 영문 회사명은 길어서 카드에서 줄바꿈을 깨뜨립니다."""
    n = (name or "").strip()
    for suf in (" Corporation", " Incorporated", " Inc.", " Inc", " Corp.", " Corp",
                " Company", " Co.", " Ltd.", " Ltd", " plc", " PLC", ", Inc.", ","):
        n = n.replace(suf, "")
    n = " ".join(n.split())
    return n[:limit]


def _spark_points(series: list[float] | None, width: int = 1080, height: int = 150) -> str:
    """표지 배경에 깔리는 지수 흐름선. 값이 모자라면 아예 안 그립니다."""
    s = [v for v in (series or []) if v is not None][-40:]
    if len(s) < 8:
        return ""
    lo, hi = min(s), max(s)
    span = (hi - lo) or 1.0
    pad = height * 0.16
    step = width / (len(s) - 1)
    pts = [
        f"{i * step:.1f},{height - pad - (v - lo) / span * (height - pad * 2):.1f}"
        for i, v in enumerate(s)
    ]
    return " ".join(pts)


# ══ 컨텍스트 조립 ═══════════════════════════════════════

def _cover_stats(data: dict) -> list[dict]:
    """표지 하단 수치 2칸. 그날 이슈와 무관하게 늘 같은 자리에 지수를 둡니다.

    AI 가 고른 숫자를 넣으면 매일 단위가 달라져 카드가 들쭉날쭉해집니다.
    """
    market = data.get("market", {})
    picks: list[dict] = []

    for row in market.get("indices", []):
        if row.get("ticker") in ("^IXIC", "^GSPC") and row.get("pct") is not None:
            picks.append({
                "k": row["label"],
                "v": _fmt_pct(row["pct"]),
                "cls": _cls(row["pct"]),
            })
    picks = picks[:2]

    # 지수를 못 받았을 때만 대체 — 빈 칸을 남기지 않습니다
    if len(picks) < 2:
        fg = data.get("fear_greed") or {}
        if fg.get("score") is not None:
            picks.append({"k": "공포탐욕지수", "v": str(fg["score"]), "cls": "fl"})
    if len(picks) < 2:
        for row in market.get("gauges", []):
            if row.get("ticker") == "^VIX" and row.get("pct") is not None:
                picks.append({"k": "VIX", "v": _fmt_pct(row["pct"]), "cls": _cls(row["pct"])})
                break
    return picks[:2]


def _movers(picked: list[dict], pool: dict[str, dict]) -> list[dict]:
    """AI 가 티커로 고른 수혜·피해주를 실제 시세와 합칩니다.

    등락률을 AI 에게 쓰게 하면 없는 숫자를 만들어냅니다. AI 는 '이유' 한 줄만
    쓰고, 숫자와 이름은 수집한 데이터에서만 가져옵니다. 풀에 없는 티커는
    통째로 버립니다.
    """
    out: list[dict] = []
    for item in picked or []:
        tk = str(item.get("ticker", "")).upper().strip()
        row = pool.get(tk)
        if not row or row.get("pct") is None:
            continue
        out.append({
            "ticker": tk,
            "name": _short_name(row.get("name") or tk),
            "pct": row["pct"],
            "fmt_pct": _fmt_pct(row["pct"]),
            "cls": _cls(row["pct"]),
            "why": (item.get("why") or "").strip()[:22],
        })
        if len(out) == 3:
            break
    return out


def _fill_movers(rows: list[dict], pool_sorted: list[dict], used: set[str]) -> list[dict]:
    """AI 픽이 모자라면 실제 등락 순위로 채웁니다. 칸이 비면 카드가 부실해집니다."""
    for row in pool_sorted:
        if len(rows) >= 3:
            break
        tk = row["ticker"]
        if tk in used:
            continue
        rows.append({
            "ticker": tk,
            "name": _short_name(row.get("name") or tk),
            "pct": row["pct"],
            "fmt_pct": _fmt_pct(row["pct"]),
            "cls": _cls(row["pct"]),
            "why": "",
        })
        used.add(tk)
    return rows


def _decorate_facts(facts: list[dict]) -> list[dict]:
    """숫자 앞의 부호로 색을 정합니다. AI 에게 색을 고르게 하면 틀립니다."""
    out = []
    for f in facts or []:
        num = str(f.get("num", "")).strip()
        cls = "fl"
        if num.startswith("+"):
            cls = "up"
        elif num.startswith("-") or num.startswith("−"):
            cls = "dn"
        out.append({
            "num": num,
            "label": str(f.get("label", ""))[:16],
            "text": str(f.get("text", ""))[:40],
            "cls": cls,
        })
    return out[:3]


# 글자 수 상한. 프롬프트로도 제한하지만 모델이 넘기는 날이 반드시 옵니다.
# 넘친 카드는 아래가 잘린 채 인스타에 올라가므로 여기서 한 번 더 자릅니다.
_LIMITS = {
    "issue_tag": 10, "hook1": 16, "hook2": 17, "cover_sub": 32,
    "p2_headline": 14, "p2_note": 30,
    "p3_headline": 14, "why_text": 82, "punch": 34,
    "p4_headline": 14, "kr_line": 32,
    "p5_headline": 14, "tomorrow": 28,
}


def _clip(text, limit: int) -> str:
    t = str(text or "").strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def build_context(data: dict, summary: dict) -> dict:
    pool = data.get("mover_pool") or {}
    gainers = sorted(
        [r for r in pool.values() if r.get("pct") is not None],
        key=lambda r: r["pct"], reverse=True,
    )
    losers = list(reversed(gainers))

    winners = _movers(summary.get("winners"), pool)
    used = {w["ticker"] for w in winners}
    winners = _fill_movers(winners, gainers, used)

    lose_rows = [m for m in _movers(summary.get("losers"), pool) if m["ticker"] not in used]
    used |= {m["ticker"] for m in lose_rows}
    lose_rows = _fill_movers(lose_rows, losers, used)

    s = dict(summary)
    for key, limit in _LIMITS.items():
        s[key] = _clip(s.get(key), limit)
    s["facts"] = _decorate_facts(summary.get("facts"))
    s["chain"] = [{"step": _clip(c.get("step"), 18)} for c in (summary.get("chain") or [])[:4]]
    s["wrap"] = [{"text": _clip(w.get("text"), 24)} for w in (summary.get("wrap") or [])[:3]]

    idx = next(
        (r for r in data.get("market", {}).get("indices", []) if r.get("ticker") == "^IXIC"),
        None,
    ) or next(iter(data.get("market", {}).get("indices", [])), None)

    return {
        "date_kr": data["date_kr"],
        "weekday_kr": data.get("weekday_kr", ""),
        "s": s,
        "handle": cfg.INSTAGRAM_HANDLE,
        "cover_stats": _cover_stats(data),
        "winners": winners,
        "losers": lose_rows,
        "spark": _spark_points((idx or {}).get("series_60")),
        "spark_color": UP if (idx or {}).get("pct", 0) and idx["pct"] > 0 else DOWN,
    }


# ══ 렌더링 ══════════════════════════════════════════════

def render_cards(data: dict, summary: dict, docs_cards_dir: str, slug: str) -> list[str]:
    env = Environment(loader=FileSystemLoader(SRC), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("issue_card.html")
    ctx = build_context(data, summary)

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
        first = True
        for n in range(1, CARD_COUNT + 1):
            tmp = tmp_dir / f"_issue-{n}.html"
            tmp.write_text(
                tpl.render(card_num=n, card_label=CARD_LABELS[n], **ctx), encoding="utf-8"
            )
            page.goto(tmp.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            if first:
                page.evaluate("document.fonts.ready")  # 웹폰트 대기 — 안 하면 한글이 깨집니다
                page.wait_for_timeout(600)
                first = False
            else:
                page.wait_for_timeout(150)

            # 넘친 카드는 아래가 잘린 채로 올라갑니다. 조용히 지나가지 않게 남깁니다.
            overflow = page.evaluate(
                "() => document.body.scrollHeight - document.body.clientHeight"
            )
            if overflow and overflow > 2:
                log.warning("카드 %d 내용이 %dpx 넘쳤습니다 — 글자 수 한도를 줄이세요", n, overflow)

            out_path = str(out_dir / f"{slug}-{n}.jpg")
            page.screenshot(path=out_path, type="jpeg", quality=92, full_page=False)
            paths.append(out_path)
        browser.close()
    return paths


PAGE_TPL = """<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{date} 미국장 이슈 — {tag}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
  body{{margin:0;background:#FFF3DF;color:#141110;font-family:Pretendard,"Noto Sans KR",sans-serif;font-variant-numeric:tabular-nums}}
  .wrap{{max-width:720px;margin:0 auto;padding:28px 22px 72px}}
  .cards{{display:flex;flex-direction:column;gap:14px}}
  img{{width:100%;border:4px solid #141110;display:block}}
  h1{{font-size:30px;font-weight:900;letter-spacing:-.04em;margin:34px 0 6px;line-height:1.2}}
  .tag{{display:inline-block;padding:7px 15px;background:#FFD400;border:4px solid #141110;
        font-weight:900;font-size:16px;margin-top:26px}}
  h2{{font-size:20px;font-weight:900;margin:38px 0 12px;letter-spacing:-.03em}}
  p{{font-size:17px;line-height:1.75;color:#4A4340}}
  li{{font-size:17px;line-height:1.85}}
  .row{{display:flex;justify-content:space-between;padding:12px 0;border-bottom:3px solid #141110;font-size:17px;font-weight:700}}
  .n{{font-family:'IBM Plex Mono',monospace;font-weight:600}}
  .up{{color:#FF3B30}}.dn{{color:#2B4DFF}}.fl{{color:#8A817C}}
  footer{{margin-top:44px;font-size:13px;color:#8A817C;line-height:1.7}}
</style></head><body><div class="wrap">
<div class="cards">{card_imgs}</div>
<span class="tag">{tag}</span>
<h1>{hook}</h1>
<h2>무슨 일이</h2>
{facts}
<h2>왜 중요한가</h2>
<p>{why}</p>
<ul>{chain}</ul>
<h2>웃은 쪽</h2>
{winners}
<h2>운 쪽</h2>
{losers}
<h2>한 줄 정리</h2>
<ul>{wrap}</ul>
<p>{tomorrow}</p>
<footer>본 콘텐츠는 공개된 시장 데이터를 자동 정리한 투자 참고용 자료입니다.
특정 종목의 매수·매도를 권유하지 않으며, 투자 결과에 대한 책임은 본인에게 있습니다.</footer>
</div></body></html>"""


def render_page(data: dict, summary: dict, slug: str) -> str:
    e = html.escape
    ctx = build_context(data, summary)
    s = ctx["s"]

    card_imgs = "".join(
        f'<img src="cards/{slug}-{n}.jpg" alt="이슈 카드 {n}">' for n in range(1, CARD_COUNT + 1)
    )
    facts = "".join(
        f'<div class="row"><span>{e(f["label"])} · {e(f["text"])}</span>'
        f'<span class="n {f["cls"]}">{e(f["num"])}</span></div>'
        for f in s.get("facts", [])
    )
    chain = "".join(f"<li>{e(c.get('step',''))}</li>" for c in s.get("chain", [])) or "<li>—</li>"

    def _mv_rows(rows):
        return "".join(
            f'<div class="row"><span>{e(m["ticker"])} · {e(m["name"])}'
            + (f' — {e(m["why"])}' if m["why"] else "")
            + f'</span><span class="n {m["cls"]}">{m["fmt_pct"]}</span></div>'
            for m in rows
        ) or '<div class="row"><span>—</span><span class="n">—</span></div>'

    wrap = "".join(f"<li>{e(w.get('text',''))}</li>" for w in s.get("wrap", [])) or "<li>—</li>"

    page = PAGE_TPL.format(
        date=data["date_kr"],
        tag=e(s.get("issue_tag", "미국장 이슈")),
        card_imgs=card_imgs,
        hook=e(f"{s.get('hook1','')} {s.get('hook2','')}".strip()),
        facts=facts,
        why=e(s.get("why_text", "")),
        chain=chain,
        winners=_mv_rows(ctx["winners"]),
        losers=_mv_rows(ctx["losers"]),
        wrap=wrap,
        tomorrow=e(s.get("tomorrow", "")),
    )
    docs = Path(cfg.DOCS_DIR)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / f"{slug}.html").write_text(page, encoding="utf-8")
    (docs / "cards").mkdir(parents=True, exist_ok=True)
    return str(docs / f"{slug}.html")
