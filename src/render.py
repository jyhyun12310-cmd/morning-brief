"""5장 카드뉴스(JPEG)와 GitHub Pages 상세 페이지를 만듭니다.

인스타그램은 PNG 를 안 받습니다. 반드시 JPEG 로 저장합니다.
캐러셀은 첫 장 비율에 맞춰 나머지가 잘리므로 5장 모두 1080x1350 로 통일합니다.
"""

from __future__ import annotations

import html
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

import config as cfg

SRC = Path(__file__).parent
CARD_COUNT = 5
UP, DOWN, FLAT, GOLD = "#EF4444", "#3B82F6", "#94A3B8", "#FACC15"

CARD_LABELS = {
    1: "어젯밤 키워드 주식",
    2: "왜 지금 이 종목인가",
    3: "펀더멘털",
    4: "AI 전망",
    5: "요약",
}


# ══ 포맷터 ══════════════════════════════════════════════

def _arrow(pct: float | None) -> str:
    """등락 방향을 기호로. 색맹이어도 방향이 읽히도록 색과 함께 씁니다."""
    if pct is None:
        return ""
    return "\u25b2" if pct > 0 else "\u25bc" if pct < 0 else "\u2015"


def _split_highlight(text: str, keyword: str) -> list[dict]:
    """헤드라인을 [일반, 강조, 일반] 조각으로 나눕니다.

    키워드가 실제로 헤드라인 안에 없으면(모델이 잘못 뽑으면) 강조 없이 통째로 반환합니다.
    """
    text = (text or "").strip()
    keyword = (keyword or "").strip()
    if not text:
        return []
    if not keyword or keyword not in text:
        return [{"t": text, "hl": False}]
    head, _, tail = text.partition(keyword)
    parts = []
    if head:
        parts.append({"t": head, "hl": False})
    parts.append({"t": keyword, "hl": True})
    if tail:
        parts.append({"t": tail, "hl": False})
    return parts


def _cls(pct: float | None) -> str:
    if pct is None:
        return "fl"
    return "up" if pct > 0 else "dn" if pct < 0 else "fl"


def _hex(pct: float | None) -> str:
    return {"up": UP, "dn": DOWN, "fl": FLAT}[_cls(pct)]


def _fmt_num(v: float, ticker: str = "") -> str:
    a = abs(v)
    if ticker in ("^TNX", "^VIX"):
        return f"{v:,.2f}"
    if ticker.startswith("^"):
        return f"{v:,.0f}" if a >= 100 else f"{v:,.2f}"
    if a >= 10000:
        return f"{v:,.0f}"
    if a >= 1000:
        return f"{v:,.1f}"
    if a >= 10:
        return f"{v:,.2f}"
    return f"{v:,.3f}"


def _fmt_cap(v: float | None) -> str:
    """시가총액을 조/억 달러 단위로 축약."""
    if v is None:
        return "—"
    if v >= 1e12:
        return f"{v / 1e12:.2f}T"
    if v >= 1e9:
        return f"{v / 1e9:.0f}B"
    return f"{v / 1e6:.1f}M"


def _fmt_ratio(v: float | None, suffix: str = "") -> str:
    return f"{v:,.1f}{suffix}" if v is not None else "—"


def _spark(series: list[float], width: int = 120, height: int = 26) -> str:
    pts = [float(v) for v in (series or []) if v is not None]
    if len(pts) < 3:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    pad, n = 3, len(pts)
    return " ".join(
        f"{i / (n - 1) * width:.1f},{height - pad - (v - lo) / span * (height - pad * 2):.1f}"
        for i, v in enumerate(pts)
    )


def _cover_glow_chart(series: list[float], width: int = 1080, height: int = 300) -> dict | None:
    """표지 배경에 깔 종목 자체의 60일 추세선. 마지막 점 좌표는 골드 글로우 점을 찍는 데 씁니다."""
    pts_str = _spark(series, width=width, height=height)
    if not pts_str:
        return None
    pts = pts_str.split()
    last_x, last_y = pts[-1].split(",")
    return {"points": pts_str, "last_x": last_x, "last_y": last_y}


def _decorate(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        pct = r.get("pct")
        out.append({
            **r,
            "cls": _cls(pct),
            "hex": _hex(pct),
            "fmt_last": _fmt_num(r["last"], r.get("ticker", "")),
            "fmt_pct": f"{pct:+.2f}%" if pct is not None else "—",
            "arrow": _arrow(pct),
            "spark": _spark(r.get("series")),
        })
    return out


# ══ 페이지별 가공 ═══════════════════════════════════════

def _focus_ctx(focus: dict) -> dict:
    """주인공 종목의 표시용 값. 티커 길이에 따라 마크 폰트 크기를 조절합니다."""
    if not focus:
        return {"ticker": "", "name": "", "fmt_pct": "—", "fmt_last": "—",
                "cls": "fl", "hex": FLAT, "mark_size": 40, "earnings": {}}
    pct = focus.get("pct")
    tk = focus.get("ticker", "")
    mark = {1: 62, 2: 58, 3: 50, 4: 40, 5: 33}.get(len(tk), 30)

    e = _earnings_read(focus.get("earnings") or {})

    return {
        **focus,
        "cls": _cls(pct),
        "hex": _hex(pct),
        "fmt_pct": f"{pct:+.2f}%" if pct is not None else "—",
        "arrow": _arrow(pct),
        "fmt_last": _fmt_num(focus.get("last", 0)),
        "mark_size": mark,
        "earnings": e,
    }


def _p1_chips(data: dict) -> list[dict]:
    """표지 하단 4칸: 주요 지수 2 + VIX + 공포탐욕지수."""
    chips = []
    for i in data.get("market", {}).get("indices", [])[:2]:
        if i.get("pct") is None:
            continue
        chips.append({"label": i["label"], "val": f"{i['pct']:+.2f}%", "cls": _cls(i["pct"])})
    for g in data.get("market", {}).get("gauges", []):
        if g["ticker"] == "^VIX" and g.get("pct") is not None:
            chips.append({"label": "VIX", "val": _fmt_num(g["last"], "^VIX"), "cls": _cls(g["pct"])})
            break
    fg = data.get("fear_greed", {})
    if fg.get("score") is not None:
        chips.append({"label": "공포탐욕", "val": f"{fg['score']} {fg['label']}", "cls": "fl"})
    return chips[:4]


def _val_cells(focus: dict) -> list[dict]:
    """밸류에이션 지표. 값이 없는 건 빼고, 있는 것 위주로 최대 6칸 채웁니다."""
    v = focus.get("valuation") or {}
    g = focus.get("growth") or {}
    cands = [
        ("PER", _fmt_ratio(v.get("per"))),
        ("선행 PER", _fmt_ratio(v.get("forward_per"))),
        ("PBR", _fmt_ratio(v.get("pbr"))),
        ("EV/EBITDA", _fmt_ratio(v.get("ev_ebitda"))),
        ("영업이익률", f"{v['margin'] * 100:.1f}%" if v.get("margin") is not None else "—"),
        ("매출성장", f"{g['revenue'] * 100:+.1f}%" if g.get("revenue") is not None else "—"),
        ("FCF", _fmt_cap(v.get("fcf"))),
    ]
    return [{"k": k, "v": val} for k, val in cands if val != "—"][:6]


def _rev_bars(focus: dict) -> list[dict]:
    """분기 매출 막대. 최소값도 보이도록 하한 22%를 둡니다."""
    hist = focus.get("revenue_history") or []
    vals = [h["value"] for h in hist if h.get("value")]
    if len(vals) < 2:
        return []
    hi = max(vals)
    return [
        {"period": h["period"], "h": round(22 + (h["value"] / hi) * 78, 1)}
        for h in hist if h.get("value")
    ]


def _peers(focus: dict) -> list[dict]:
    """경쟁사 비교표. 주인공을 맨 위에 두고 하이라이트합니다."""
    rows = []
    me = {
        "ticker": focus.get("ticker", ""),
        "pct": focus.get("pct"),
        "per": (focus.get("valuation") or {}).get("per"),
        "market_cap": focus.get("market_cap"),
        "is_me": True,
    }
    if me["ticker"]:
        rows.append(me)
    for p in (focus.get("peers") or [])[:4]:
        rows.append({**p, "is_me": False})
    return [
        {
            **r,
            "cls": _cls(r.get("pct")),
            "fmt_pct": f"{r['pct']:+.2f}%" if r.get("pct") is not None else "—",
            "fmt_per": _fmt_ratio(r.get("per")),
            "fmt_cap": _fmt_cap(r.get("market_cap")),
        }
        for r in rows
    ]


def _target(focus: dict) -> dict | None:
    """목표주가 게이지. 최저~최고 구간에서 현재가 위치를 표시합니다."""
    a = focus.get("analyst") or {}
    lo, hi, mean = a.get("target_low"), a.get("target_high"), a.get("target_mean")
    cur = focus.get("last")
    if not (lo and hi and mean and cur) or hi <= lo:
        return None
    pin = (cur - lo) / (hi - lo) * 100
    fill = (mean - lo) / (hi - lo) * 100
    cnt = a.get("count")
    return {
        "mean": f"{mean:,.0f}" if mean >= 100 else f"{mean:,.1f}",
        "low": f"{lo:,.0f}" if lo >= 100 else f"{lo:,.1f}",
        "high": f"{hi:,.0f}" if hi >= 100 else f"{hi:,.1f}",
        "cur": f"{cur:,.0f}" if cur >= 100 else f"{cur:,.1f}",
        "upside": f"{a['upside']:+.1f}" if a.get("upside") is not None else "",
        "count": int(cnt) if cnt else None,
        "pin": round(max(0, min(100, pin)), 1),
        "fill": round(max(0, min(100, fill)), 1),
    }


def _actions(focus: dict) -> list[dict]:
    # outlook_note 가 P4에 새로 추가되면서 공간이 빠듯해져 2개로 줄입니다.
    # 어차피 rec_dist(추천분포)가 전체 그림을 이미 보여주므로 최신 변경만으로 충분합니다.
    return [
        {**a, "cls": "up" if a["dir"] == "up" else "dn" if a["dir"] == "down" else "fl"}
        for a in (focus.get("actions") or [])[:2]
    ]


def _chain(focus: dict) -> list[dict]:
    return [
        {**c, "cls": _cls(c.get("pct")), "arrow": _arrow(c.get("pct")),
         "fmt_pct": f"{c['pct']:+.2f}%" if c.get("pct") is not None else "—"}
        for c in (focus.get("chain") or [])
    ]


def _sector_rotation(rows: list[dict]) -> list[dict]:
    """섹터 ETF 등락을 좌우 발산 바로. 최대 절대값을 기준으로 폭을 맞춥니다."""
    if not rows:
        return []
    peak = max(abs(r["pct"]) for r in rows) or 1.0
    return [
        {
            "label": r["label"],
            "cls": _cls(r["pct"]),
            "fmt_pct": f"{r['pct']:+.2f}%",
            "arrow": _arrow(r["pct"]),
            "bar": round(min(abs(r["pct"]) / peak, 1.0) * 50, 1),
        }
        for r in rows
    ]


def _rvol_badge(focus: dict) -> dict | None:
    """상대거래량. 평소 대비 몇 배가 터졌는지 — 그날 뉴스가 있었다는 신호."""
    rv = focus.get("rvol")
    if not rv:
        return None
    if rv >= 3:
        tone, txt = "hot", "거래량 폭증"
    elif rv >= 1.8:
        tone, txt = "warm", "거래량 급증"
    elif rv >= 1.2:
        tone, txt = "warm", "거래량 증가"
    else:
        tone, txt = "calm", "평소 수준"
    return {"val": f"{rv:.1f}x", "txt": txt, "tone": tone}


def _pct100(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


def _rsi_read(rsi: float | None) -> dict | None:
    """RSI 수치를 색·해석과 함께.

    과매수·과매도는 '상승/하락'이 아니라 '주의 신호'이므로 up/dn(빨강/파랑) 대신
    hl(골드) 톤을 씁니다. 색이 매수 신호처럼 오독되는 걸 막기 위함입니다.
    """
    if rsi is None:
        return None
    if rsi >= 70:
        tone, txt = "hl", "과매수"
    elif rsi <= 30:
        tone, txt = "hl", "과매도"
    else:
        tone, txt = "fl", "중립"
    return {"val": f"{rsi:.0f}", "txt": txt, "tone": tone, "pct": round(min(rsi, 100), 1)}


def _earnings_read(e: dict) -> dict:
    """실적 히스토리를 카드용으로. dots 는 과거→최신 순 점 4개."""
    if not e:
        return {}
    out = dict(e)
    if e.get("surprise") is not None:
        out["fmt_surprise"] = f"{e['surprise']:+.1f}%"
    hist = e.get("history") or []
    out["dots"] = [{"beat": b} for b in hist]
    if e.get("streak"):
        out["streak_txt"] = f"{e['streak']}분기 연속 서프라이즈"
    return out


def _cross_read(cross: str | None) -> dict | None:
    if not cross:
        return None
    if cross == "golden":
        return {"txt": "골든크로스", "sub": "20일선이 50일선 위", "tone": "up"}
    return {"txt": "데드크로스", "sub": "20일선이 50일선 아래", "tone": "dn"}


def _smart_money_cells(sm: dict) -> list[dict]:
    """기관 보유율·공매도·베타. 값이 있는 것만 표시합니다."""
    if not sm:
        return []
    cells = []
    if sm.get("inst_pct") is not None:
        cells.append({"k": "기관 보유율", "v": _pct100(sm["inst_pct"])})
    if sm.get("short_pct") is not None:
        cells.append({"k": "공매도 비중", "v": _pct100(sm["short_pct"])})
    if sm.get("short_ratio") is not None:
        cells.append({"k": "숏커버 소요일", "v": f"{sm['short_ratio']:.1f}일"})
    if sm.get("beta") is not None:
        cells.append({"k": "베타", "v": f"{sm['beta']:.2f}"})
    return cells


def _rec_bars(dist: dict) -> list[dict]:
    """애널리스트 매수/보유/매도 분포를 막대 폭으로. 목표주가 하나보다 훨씬 많은 정보를 줍니다."""
    if not dist or not dist.get("total"):
        return []
    total = dist["total"]
    order = [
        ("강력매수", dist.get("strong_buy", 0), "up"),
        ("매수", dist.get("buy", 0), "up"),
        ("보유", dist.get("hold", 0), "fl"),
        ("매도", dist.get("sell", 0), "dn"),
        ("강력매도", dist.get("strong_sell", 0), "dn"),
    ]
    return [
        {"label": lbl, "n": n, "pct": round(n / total * 100, 1), "cls": cls}
        for lbl, n, cls in order if n > 0
    ]


def _insider_read(ins: dict) -> dict | None:
    """내부자 매매를 카드용 문구로. 매수 우위/매도 우위를 톤으로 구분합니다."""
    if not ins:
        return None
    net = ins.get("net_shares", 0)
    tone = "up" if net > 0 else "dn" if net < 0 else "fl"
    txt = f"최근 매수 {ins['buy_count']}건 · 매도 {ins['sell_count']}건"
    tb = ins.get("top_buy")
    highlight = None
    if tb and tb.get("value"):
        highlight = f"{tb['position'] or tb['name']} ${_fmt_cap(tb['value'])} 매수"
    return {"txt": txt, "tone": tone, "highlight": highlight}


def _vol_compare(hist_vol: float | None, vix_pct: float | None, vix_last: float | None) -> dict | None:
    """종목 자체 변동성과 VIX(시장 변동성)를 나란히. 몇 배 더 흔들리는지 보여줍니다."""
    if hist_vol is None or vix_last is None:
        return None
    ratio = round(hist_vol / vix_last, 1) if vix_last else None
    return {
        "stock": f"{hist_vol:.0f}%",
        "market": f"{vix_last:.0f}%",
        "ratio": ratio,
        "tone": "up" if ratio and ratio >= 1.5 else "fl",
    }


def _fin_health_cells(fh: dict) -> list[dict]:
    """부채비율·유동비율. 값이 있는 것만 표시합니다."""
    if not fh:
        return []
    cells = []
    if fh.get("debt_equity") is not None:
        cells.append({"k": "부채비율", "v": f"{fh['debt_equity']:.0f}%"})
    if fh.get("current_ratio") is not None:
        cells.append({"k": "유동비율", "v": f"{fh['current_ratio']:.1f}배"})
    if fh.get("quick_ratio") is not None:
        cells.append({"k": "당좌비율", "v": f"{fh['quick_ratio']:.1f}배"})
    return cells


def _template_context(data: dict, summary: dict) -> dict:
    focus = data.get("focus", {})
    market = data.get("market", {})
    return {
        "date_kr": data["date_kr"],
        "weekday_kr": data["weekday_kr"],
        "s": summary,
        "f": _focus_ctx(focus),
        "p1_chips": _p1_chips(data),
        "hook_parts": _split_highlight(
            summary.get("hook_headline", ""), summary.get("hook_highlight", "")
        ),
        "glow_chart": _cover_glow_chart(focus.get("series_60") or focus.get("series")),
        "indices": _decorate(market.get("indices", [])),
        "gauges": _decorate(market.get("gauges", [])),
        "val_cells": _val_cells(focus),
        "rev_bars": _rev_bars(focus),
        "peers": _peers(focus),
        "tgt": _target(focus),
        "actions": _actions(focus),
        "chain": _chain(focus),
        "chain_kind": focus.get("chain_kind", "밸류체인"),
        "sectors": _sector_rotation(data.get("sector_rotation", [])),
        "rvol": _rvol_badge(focus),
        "w52": focus.get("w52") or {},
        "rsi": _rsi_read((focus.get("levels") or {}).get("rsi")),
        "cross": _cross_read((focus.get("levels") or {}).get("cross")),
        "smart_cells": _smart_money_cells(focus.get("smart_money") or {}),
        "rec_bars": _rec_bars(focus.get("rec_dist") or {}),
        "peer_avg_per": focus.get("peer_avg_per"),
        "insider": _insider_read(focus.get("insider") or {}),
        "inst_top": focus.get("inst_top") or [],
        "vol_compare": _vol_compare(
            (focus.get("levels") or {}).get("hist_vol"),
            None,
            next((g["last"] for g in data.get("market", {}).get("gauges", [])
                  if g["ticker"] == "^VIX"), None),
        ),
        "fin_cells": _fin_health_cells(focus.get("financial_health") or {}),
        "runners": [
            {**r, "cls": _cls(r.get("pct")),
             "fmt_pct": f"{r['pct']:+.2f}%" if r.get("pct") is not None else "—"}
            for r in (data.get("runners_up") or [])[:3]
        ],
    }


# ══ 렌더링 ══════════════════════════════════════════════

def render_cards(data: dict, summary: dict, docs_cards_dir: str, slug: str) -> list[str]:
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
        first = True
        for n in range(1, CARD_COUNT + 1):
            tmp = tmp_dir / f"_card-{n}.html"
            tmp.write_text(tpl.render(card_num=n, card_label=CARD_LABELS[n], **ctx), encoding="utf-8")
            page.goto(tmp.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            if first:
                page.evaluate("document.fonts.ready")  # 웹폰트 대기 — 안 하면 한글이 깨집니다
                page.wait_for_timeout(600)
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
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{date} {ticker} 브리핑</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
  body{{margin:0;background:#05070D;color:#F2F6FC;font-family:Pretendard,"Noto Sans KR",sans-serif;font-variant-numeric:tabular-nums}}
  .wrap{{max-width:720px;margin:0 auto;padding:28px 22px 72px}}
  .cards{{display:flex;flex-direction:column;gap:14px}}
  img{{width:100%;border-radius:14px;display:block}}
  h2{{font-size:20px;font-weight:800;margin:40px 0 14px;letter-spacing:-.03em}}
  .row{{display:flex;justify-content:space-between;padding:13px 0;border-bottom:1px solid #1C2840;font-size:17px}}
  .n{{font-family:'IBM Plex Mono',monospace;font-weight:600}}
  .up{{color:#FF4D3D}}.dn{{color:#3D8BFF}}.fl{{color:#94A3BC}}
  p{{font-size:17px;line-height:1.75;color:#94A3BC}}
  li{{font-size:17px;line-height:1.8}}
  footer{{margin-top:44px;font-size:13px;color:#5A6B87;line-height:1.7}}
</style></head><body><div class="wrap">
<div class="cards">{card_imgs}</div>
<h2>{headline}</h2>
<p>{macro_line}</p>
{facts}
<h2>펀더멘털</h2>
{val_rows}
<p>{fundamental_note}</p>
<h2>밸류체인</h2>
{chain_rows}
<p>{chain_note}</p>
<h2>월가 시각</h2>
<p>{wallst_note}</p>
<h2>리스크</h2>
<ul>{risks}</ul>
<h2>3줄 요약</h2>
<ul>{summary3}</ul>
<footer>본 콘텐츠는 공개된 시장 데이터를 자동 정리한 투자 참고용 자료입니다.
특정 종목의 매수·매도를 권유하지 않으며, 투자 결과에 대한 책임은 본인에게 있습니다.</footer>
</div></body></html>"""


def render_detail_page(data: dict, summary: dict, slug: str) -> str:
    e = html.escape
    focus = data.get("focus", {})
    ctx = _template_context(data, summary)

    card_imgs = "".join(
        f'<img src="cards/{slug}-{n}.jpg" alt="브리핑 {n}">' for n in range(1, CARD_COUNT + 1)
    )
    facts = "".join(f"<p>{e(t)}</p>" for t in summary.get("facts", []))
    val_rows = "".join(
        f'<div class="row"><span>{e(c["k"])}</span><span class="n">{e(c["v"])}</span></div>'
        for c in ctx["val_cells"]
    )
    chain_rows = "".join(
        f'<div class="row"><span>{e(c["ticker"])} · {e(c["relation"])}</span>'
        f'<span class="n {c["cls"]}">{c["fmt_pct"]}</span></div>'
        for c in ctx["chain"]
    )
    risks = "".join(f"<li>{e(r)}</li>" for r in summary.get("risks", [])) or "<li>—</li>"
    summary3 = "".join(f"<li>{e(t)}</li>" for t in summary.get("summary3", [])) or "<li>—</li>"

    page = DETAIL_TPL.format(
        date=data["date_kr"],
        ticker=e(focus.get("ticker", "")),
        card_imgs=card_imgs,
        headline=e(summary.get("hook_headline", "")),
        macro_line=e(summary.get("macro_line", "")),
        facts=facts,
        val_rows=val_rows,
        fundamental_note=e(summary.get("fundamental_note", "")),
        chain_rows=chain_rows,
        chain_note=e(summary.get("chain_note", "")),
        wallst_note=e(summary.get("wallst_note", "")),
        risks=risks,
        summary3=summary3,
    )
    docs = Path(cfg.DOCS_DIR)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / f"{slug}.html").write_text(page, encoding="utf-8")
    (docs / "index.html").write_text(page, encoding="utf-8")
    (docs / "cards").mkdir(parents=True, exist_ok=True)
    return str(docs / f"{slug}.html")
