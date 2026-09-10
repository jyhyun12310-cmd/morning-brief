"""시장 데이터 + 오늘의 종목 딥다이브 데이터를 모읍니다.

원칙: 어느 한 소스가 죽어도 브리핑 전체가 실패하지 않게 전부 개별로 감쌉니다.
yfinance 의 info 필드는 종목마다 누락이 잦아 모든 접근을 방어적으로 처리합니다.
"""

from __future__ import annotations

import datetime as dt
import logging

import feedparser
import pandas as pd
import requests
import yfinance as yf

import config as cfg

log = logging.getLogger(__name__)

# Yahoo sectorKey → 한국어 표기
SECTOR_KR = {
    "technology": "기술", "financial-services": "금융", "healthcare": "헬스케어",
    "consumer-cyclical": "임의소비재", "consumer-defensive": "필수소비재",
    "communication-services": "커뮤니케이션", "industrials": "산업재",
    "energy": "에너지", "basic-materials": "소재", "utilities": "유틸리티",
    "real-estate": "부동산",
}


# ══ 공통 유틸 ═══════════════════════════════════════════

def _pct_change(closes: pd.Series) -> tuple[float | None, float | None]:
    s = closes.dropna()
    if len(s) < 2:
        return (float(s.iloc[-1]) if len(s) == 1 else None), None
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    if prev == 0:
        return last, None
    return last, (last - prev) / prev * 100


def _num(v) -> float | None:
    """yfinance 값이 None/NaN/문자열이어도 안전하게 float 로."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN·무한대
        return None
    return f


def fetch_quotes(tickers: list[str]) -> dict[str, dict]:
    """티커 목록의 종가·등락률·최근 시계열을 한 번에."""
    if not tickers:
        return {}
    try:
        raw = yf.download(
            tickers, period="3mo", interval="1d",
            auto_adjust=False, progress=False, threads=True,
        )
    except Exception:
        log.exception("yfinance 다운로드 실패: %s", tickers)
        return {}
    if raw is None or raw.empty:
        return {}

    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    elif len(tickers) == 1 and len(close.columns) == 1:
        close.columns = [tickers[0]]

    out: dict[str, dict] = {}
    for t in tickers:
        if t not in close.columns:
            continue
        series = close[t].dropna()
        last, pct = _pct_change(close[t])
        if last is None:
            continue
        out[t] = {
            "last": round(last, 2),
            "pct": round(pct, 2) if pct is not None else None,
            "series": [round(float(v), 4) for v in series.tail(10)],
            "series_60": [round(float(v), 4) for v in series.tail(60)],
        }
    return out


# ══ 시장 맥락 ═══════════════════════════════════════════

def _rows(quotes: dict, mapping: dict) -> list[dict]:
    return [
        {"label": name, "ticker": t, **quotes[t]}
        for t, name in mapping.items()
        if t in quotes
    ]


def fetch_market() -> dict:
    idx_q = fetch_quotes(list(cfg.HEADLINE_INDICES))
    gauge_q = fetch_quotes(list(cfg.CONTEXT_GAUGES))
    kr_q = fetch_quotes(list(cfg.KR_CONTEXT))
    return {
        "indices": _rows(idx_q, cfg.HEADLINE_INDICES),
        "gauges": _rows(gauge_q, cfg.CONTEXT_GAUGES),
        "kr_context": _rows(kr_q, cfg.KR_CONTEXT),
    }


def _fg_label(score: float) -> str:
    if score <= 24:
        return "극단적 공포"
    if score <= 44:
        return "공포"
    if score <= 55:
        return "중립"
    if score <= 74:
        return "탐욕"
    return "극단적 탐욕"


def fetch_fear_greed() -> dict:
    """CNN 공포탐욕지수. 비공식 엔드포인트라 실패해도 무시합니다."""
    try:
        r = requests.get(
            cfg.FEAR_GREED_URL,
            headers={"User-Agent": cfg.FEAR_GREED_UA, "Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("공포탐욕지수 응답 %s", r.status_code)
            return {}
        b = r.json().get("fear_and_greed", {})
        score = _num(b.get("score"))
        if score is None:
            return {}
        score = round(score)
        return {
            "score": score,
            "label": _fg_label(score),
            "prev_close": _num(b.get("previous_close")),
            "week_ago": _num(b.get("previous_1_week")),
            "month_ago": _num(b.get("previous_1_month")),
        }
    except Exception:
        log.exception("공포탐욕지수 수집 실패")
        return {}


# ══ 오늘의 종목 선정 ════════════════════════════════════

def screen_universe() -> dict[str, dict]:
    """Yahoo 스크리너로 매일 전체 시장에서 후보를 새로 뽑습니다.

    고정 목록을 쓰지 않으므로 그날 실제로 움직인 종목이 후보가 됩니다.
    스크리너 응답에 시총·거래량·평균거래량이 함께 오므로 추가 조회 없이
    점수를 매길 수 있습니다.
    """
    found: dict[str, dict] = {}
    if not hasattr(yf, "screen"):
        log.warning("yfinance 스크리너 미지원 — 예비 후보군 사용")
        return found

    for name in cfg.SCREENS:
        try:
            resp = yf.screen(name, count=cfg.SCREEN_COUNT)
        except Exception:
            log.warning("스크리너 실패: %s", name)
            continue
        for q in (resp or {}).get("quotes", []):
            sym = q.get("symbol")
            if not sym or sym in found:
                continue
            cap = _num(q.get("marketCap"))
            price = _num(q.get("regularMarketPrice"))
            vol = _num(q.get("regularMarketVolume"))
            avg = _num(q.get("averageDailyVolume3Month"))
            pct = _num(q.get("regularMarketChangePercent"))
            if None in (cap, price, vol, pct):
                continue
            found[sym] = {
                "ticker": sym,
                "name": q.get("shortName") or q.get("longName") or sym,
                "last": round(price, 2),
                "pct": round(pct, 2),
                "market_cap": cap,
                "volume": vol,
                "avg_volume": avg,
                "rvol": round(vol / avg, 2) if avg else None,
            }
    log.info("스크리너 후보 %d개 확보", len(found))
    return found


def _passes_filter(c: dict) -> bool:
    """작전주·페니스톡·거래 부진 종목을 걸러냅니다."""
    if c["market_cap"] < cfg.MIN_MARKET_CAP:
        return False
    if c["last"] < cfg.MIN_PRICE:
        return False
    if c["last"] * c["volume"] < cfg.MIN_DOLLAR_VOLUME:
        return False
    return True


def _cap_weight(cap: float) -> float:
    for floor, w in cfg.CAP_WEIGHTS:
        if cap >= floor:
            return w
    return cfg.CAP_WEIGHTS[-1][1]


def _cooldown_mult(ticker: str, history: list[dict], today: str) -> float:
    """최근에 다룬 종목일수록 강하게 감점해 매번 같은 이름이 나오지 않게 합니다."""
    try:
        today_d = dt.datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return 1.0
    for h in history:
        if h.get("ticker") != ticker:
            continue
        try:
            days = (today_d - dt.datetime.strptime(h["date"], "%Y-%m-%d").date()).days
        except (ValueError, KeyError):
            continue
        for limit, mult in cfg.COOLDOWN:
            if days <= limit:
                return mult
    return 1.0


def score_candidates(cands: dict[str, dict], news: list[dict],
                     history: list[dict], today: str) -> list[dict]:
    """복합 점수로 후보를 정렬합니다.

    등락률만 보면 변동성 큰 같은 종목이 반복되므로, 평소 대비 거래량이
    얼마나 터졌는지(RVOL)를 함께 봅니다. 뉴스에 언급됐는지, 최근에 다뤘는지도 반영.
    """
    blob = " ".join(n.get("title", "") for n in news).upper()
    scored = []
    for c in cands.values():
        if not _passes_filter(c):
            continue
        move = abs(c["pct"]) ** 0.7
        rvol = min(c.get("rvol") or 1.0, cfg.RVOL_CAP)
        vol_boost = 1 + (rvol - 1) * cfg.RVOL_WEIGHT
        cap_w = _cap_weight(c["market_cap"])

        news_hit = c["ticker"] in blob
        if not news_hit:
            head = c["name"].upper().split()[0] if c["name"] else ""
            news_hit = len(head) >= 4 and head in blob
        news_mult = 1.5 if news_hit else 1.0

        cool = _cooldown_mult(c["ticker"], history, today)
        score = move * vol_boost * cap_w * news_mult * cool
        scored.append({**c, "score": round(score, 3), "news_hit": news_hit,
                       "cooldown": cool})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def fetch_sector_rotation() -> list[dict]:
    """섹터 ETF 등락률. 자금이 어느 업종으로 돌았는지 보여줍니다."""
    q = fetch_quotes(list(cfg.SECTOR_ETFS))
    rows = [
        {"label": name, "ticker": t, "pct": q[t]["pct"], "last": q[t]["last"]}
        for t, name in cfg.SECTOR_ETFS.items()
        if t in q and q[t].get("pct") is not None
    ]
    rows.sort(key=lambda x: x["pct"], reverse=True)
    return rows


def fetch_industry_peers(ticker: str, industry_key: str) -> list[str]:
    """같은 산업의 상위 기업을 Yahoo 산업 분류에서 동적으로 가져옵니다."""
    if not industry_key or not hasattr(yf, "Industry"):
        return []
    try:
        top = yf.Industry(industry_key).top_companies
        if top is None or top.empty:
            return []
        return [s for s in top.index.tolist() if s != ticker][:5]
    except Exception:
        log.warning("산업 피어 조회 실패: %s", industry_key)
        return []


def _levels(series_60: list[float], last: float) -> dict:
    """최근 60거래일 종가로 지지·저항선과 이동평균을 계산합니다."""
    pts = [float(v) for v in (series_60 or []) if v is not None]
    if len(pts) < 20:
        return {}
    hi, lo = max(pts), min(pts)
    ma20 = sum(pts[-20:]) / 20
    ma50 = sum(pts[-50:]) / 50 if len(pts) >= 50 else None

    # 현재가 위쪽에서 가장 가까운 고점 = 저항, 아래쪽 저점 = 지지
    above = [p for p in pts if p > last]
    below = [p for p in pts if p < last]
    return {
        "high_60": round(hi, 2),
        "low_60": round(lo, 2),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2) if ma50 else None,
        "resistance": round(min(above), 2) if above else round(hi, 2),
        "support": round(max(below), 2) if below else round(lo, 2),
        "pos_pct": round((last - lo) / (hi - lo) * 100, 1) if hi > lo else None,
    }


def _rsi(series: list[float], period: int = 14) -> float | None:
    """14일 RSI. 70 이상 과매수, 30 이하 과매도로 봅니다."""
    pts = [float(v) for v in (series or []) if v is not None]
    if len(pts) < period + 1:
        return None
    deltas = [pts[i] - pts[i - 1] for i in range(1, len(pts))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _smart_money(info: dict) -> dict:
    """기관 보유율·공매도 비중·숏커버 소요일. 스마트머니 포지셔닝을 보여줍니다."""
    return {
        "inst_pct": _num(info.get("heldPercentInstitutions")),
        "short_pct": _num(info.get("shortPercentOfFloat")),
        "short_ratio": _num(info.get("shortRatio")),
        "beta": _num(info.get("beta")),
    }


def _rec_distribution(tk: yf.Ticker) -> dict:
    """애널리스트 매수/보유/매도 분포. 목표주가 평균 하나보다 훨씬 많은 정보를 줍니다."""
    try:
        df = tk.recommendations
        if df is None or df.empty:
            return {}
        row = df[df["period"] == "0m"]
        row = row.iloc[0] if not row.empty else df.iloc[0]
        out = {
            "strong_buy": int(row.get("strongBuy", 0) or 0),
            "buy": int(row.get("buy", 0) or 0),
            "hold": int(row.get("hold", 0) or 0),
            "sell": int(row.get("sell", 0) or 0),
            "strong_sell": int(row.get("strongSell", 0) or 0),
        }
        out["total"] = sum(out.values())
        return out if out["total"] > 0 else {}
    except Exception:
        log.warning("추천 분포 없음")
        return {}


def _earnings(tk: yf.Ticker) -> dict:
    """직전 실적의 컨센서스 대비 Beat/Miss."""
    try:
        df = tk.earnings_dates
        if df is None or df.empty:
            return {}
        past = df[df["Reported EPS"].notna()]
        if past.empty:
            return {}
        row = past.iloc[0]
        est, act = _num(row.get("EPS Estimate")), _num(row.get("Reported EPS"))
        if est is None or act is None:
            return {}
        surprise = _num(row.get("Surprise(%)"))
        if surprise is None and est:
            surprise = (act - est) / abs(est) * 100
        return {
            "date": past.index[0].strftime("%Y.%m.%d"),
            "eps_est": round(est, 2),
            "eps_act": round(act, 2),
            "surprise": round(surprise, 1) if surprise is not None else None,
            "beat": act >= est,
        }
    except Exception:
        log.warning("실적 데이터 없음")
        return {}


def _revenue_history(tk: yf.Ticker) -> list[dict]:
    """최근 분기별 매출 추이 (최대 5분기, 오래된 순)."""
    try:
        df = tk.quarterly_income_stmt
        if df is None or df.empty or "Total Revenue" not in df.index:
            return []
        row = df.loc["Total Revenue"].dropna()
        out = []
        for period, val in list(row.items())[:5]:
            v = _num(val)
            if v is None:
                continue
            out.append({"period": period.strftime("%y.%m"), "value": v})
        return list(reversed(out))
    except Exception:
        log.warning("매출 추이 없음")
        return []


def _analyst_actions(tk: yf.Ticker) -> list[dict]:
    """최근 증권사 투자의견 변경 (실제 IB 이름 포함)."""
    try:
        df = tk.upgrades_downgrades
        if df is None or df.empty:
            return []
        recent = df.head(4)
        out = []
        for gdate, r in recent.iterrows():
            action = str(r.get("Action", "")).lower()
            out.append({
                "firm": str(r.get("Firm", ""))[:28],
                "from": str(r.get("FromGrade", "") or "—")[:18],
                "to": str(r.get("ToGrade", ""))[:18],
                "dir": "up" if action in ("up", "init") else "down" if action == "down" else "flat",
                "date": gdate.strftime("%m.%d") if hasattr(gdate, "strftime") else "",
            })
        return out
    except Exception:
        log.warning("투자의견 변경 이력 없음")
        return []


def fetch_focus(ticker: str, quote: dict, cand: dict) -> dict:
    """오늘의 종목 딥다이브. 개별 필드가 없어도 있는 것만 채웁니다."""
    focus: dict = {"ticker": ticker, **quote}
    focus["rvol"] = cand.get("rvol")
    focus["volume"] = cand.get("volume")

    try:
        tk = yf.Ticker(ticker)
    except Exception:
        log.exception("Ticker 생성 실패: %s", ticker)
        return focus

    info = {}
    try:
        info = tk.info or {}
    except Exception:
        log.warning("info 조회 실패: %s", ticker)

    focus["name"] = info.get("shortName") or info.get("longName") or cand.get("name") or ticker
    focus["sector_kr"] = SECTOR_KR.get(info.get("sectorKey", ""), info.get("sector", ""))
    focus["industry"] = info.get("industry", "")
    focus["industry_key"] = info.get("industryKey", "")
    focus["market_cap"] = _num(info.get("marketCap")) or cand.get("market_cap")

    focus["valuation"] = {
        "per": _num(info.get("trailingPE")),
        "forward_per": _num(info.get("forwardPE")),
        "pbr": _num(info.get("priceToBook")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        "fcf": _num(info.get("freeCashflow")),
        "margin": _num(info.get("profitMargins")),
    }
    focus["growth"] = {
        "revenue": _num(info.get("revenueGrowth")),
        "earnings": _num(info.get("earningsGrowth")),
    }

    tgt = _num(info.get("targetMeanPrice"))
    last = focus.get("last")
    focus["analyst"] = {
        "target_mean": tgt,
        "target_high": _num(info.get("targetHighPrice")),
        "target_low": _num(info.get("targetLowPrice")),
        "count": _num(info.get("numberOfAnalystOpinions")),
        "rec": info.get("recommendationKey", ""),
        "upside": round((tgt - last) / last * 100, 1) if tgt and last else None,
    }

    focus["earnings"] = _earnings(tk)
    focus["revenue_history"] = _revenue_history(tk)
    focus["actions"] = _analyst_actions(tk)
    focus["rec_dist"] = _rec_distribution(tk)
    focus["smart_money"] = _smart_money(info)
    levels = _levels(quote.get("series_60"), quote.get("last", 0))
    levels["rsi"] = _rsi(quote.get("series_60"))
    if levels.get("ma20") and levels.get("ma50"):
        levels["cross"] = "golden" if levels["ma20"] > levels["ma50"] else "death"
    focus["levels"] = levels

    w52_hi, w52_lo = _num(info.get("fiftyTwoWeekHigh")), _num(info.get("fiftyTwoWeekLow"))
    focus["w52"] = {"high": w52_hi, "low": w52_lo}
    if w52_hi and w52_lo and w52_hi > w52_lo and last:
        focus["w52"]["pos"] = round((last - w52_lo) / (w52_hi - w52_lo) * 100, 1)

    focus["peer_tickers"] = fetch_industry_peers(ticker, focus["industry_key"])
    return focus


def fetch_peers(tickers: list[str], quotes: dict) -> list[dict]:
    """경쟁사 비교표용. 이미 받은 시세에 PER·시총만 덧붙입니다."""
    out = []
    for t in tickers:
        row = {"ticker": t, **quotes.get(t, {})}
        try:
            info = yf.Ticker(t).info or {}
            row["name"] = info.get("shortName") or t
            row["per"] = _num(info.get("trailingPE"))
            row["market_cap"] = _num(info.get("marketCap"))
        except Exception:
            log.warning("피어 info 실패: %s", t)
        if row.get("last") is not None:
            out.append(row)
    return out


def fetch_chain(ticker: str, quotes: dict) -> list[dict]:
    """밸류체인 관련주의 실제 당일 등락률.

    관계 설명은 config 의 정의를, 숫자는 실제 시세를 씁니다.
    """
    out = []
    for t, rel in cfg.VALUE_CHAIN.get(ticker, []):
        q = quotes.get(t)
        if not q or q.get("pct") is None:
            continue
        out.append({"ticker": t, "relation": rel, "last": q["last"], "pct": q["pct"]})
    return out[:4]


# ══ 뉴스 · 한국 ═════════════════════════════════════════

def fetch_news() -> list[dict]:
    items: list[dict] = []
    for url in cfg.NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            log.warning("RSS 실패: %s", url)
            continue
        for entry in feed.entries[:14]:
            items.append({
                "title": getattr(entry, "title", "").strip(),
                "summary": getattr(entry, "summary", "")[:300].strip(),
            })
    seen, uniq = set(), []
    for it in items:
        k = it["title"].lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq[: cfg.NEWS_MAX_ITEMS]


def fetch_korea() -> dict:
    result: dict = {}
    try:
        from pykrx import stock
    except Exception:
        log.warning("pykrx 미설치 — 한국 데이터 건너뜀")
        return result
    try:
        today = dt.datetime.now(cfg.KST).strftime("%Y%m%d")
        biz = stock.get_nearest_business_day_in_a_week(date=today, prev=True)
        result["date"] = biz
        for name, code in (("코스피", "1001"), ("코스닥", "2001")):
            df = stock.get_index_ohlcv(
                (dt.datetime.strptime(biz, "%Y%m%d") - dt.timedelta(days=10)).strftime("%Y%m%d"),
                biz, code,
            )
            if df is None or df.empty:
                continue
            last, pct = _pct_change(df["종가"])
            result[name] = {"last": round(last, 2), "pct": round(pct, 2) if pct else None}
    except Exception:
        log.exception("한국 데이터 수집 실패")
    return result


# ══ 오케스트레이션 ══════════════════════════════════════

def collect_all(history: list[dict] | None = None) -> dict:
    now = dt.datetime.now(cfg.KST)
    today = now.strftime("%Y-%m-%d")
    history = history or []
    news = fetch_news()

    # 1) 매일 전체 시장에서 후보를 새로 뽑습니다
    cands = screen_universe()
    if len(cands) < 12:  # 스크리너가 죽었을 때만 예비 후보군
        log.warning("후보 부족 — 예비 후보군으로 보완")
        fb = fetch_quotes(cfg.FALLBACK_UNIVERSE)
        for t, v in fb.items():
            if t not in cands and v.get("pct") is not None:
                cands[t] = {"ticker": t, "name": t, "last": v["last"], "pct": v["pct"],
                            "market_cap": cfg.MIN_MARKET_CAP, "volume": cfg.MIN_DOLLAR_VOLUME,
                            "avg_volume": None, "rvol": None}

    # 2) 복합 점수로 정렬
    ranked = score_candidates(cands, news, history, today)
    if not ranked:
        log.error("선정 가능한 후보가 없습니다")
        return {"generated_at": now.isoformat(), "date_kr": now.strftime("%Y.%m.%d"),
                "weekday_kr": "월화수목금토일"[now.weekday()], "market": fetch_market(),
                "fear_greed": {}, "focus": {}, "news": news, "korea": fetch_korea(),
                "sector_rotation": [], "ranked": []}

    top = ranked[0]
    log.info("오늘의 종목: %s (점수 %.2f, 등락 %+.2f%%, RVOL %s, 뉴스 %s)",
             top["ticker"], top["score"], top["pct"], top.get("rvol"), top["news_hit"])

    # 3) 주인공 + 밸류체인 + 피어 시세를 한 번에
    chain_pairs = cfg.VALUE_CHAIN.get(top["ticker"], [])
    focus_q = fetch_quotes([top["ticker"]])
    quote = focus_q.get(top["ticker"], {"last": top["last"], "pct": top["pct"],
                                        "series": [], "series_60": []})
    # peer_tickers 는 industry 조회가 필요해 focus 안에서 채워지므로,
    # fetch_focus 가 끝난 뒤에 그 결과로 경쟁사 시세를 조회합니다.
    focus = fetch_focus(top["ticker"], quote, top)

    related = {t for t, _ in chain_pairs} | set(focus.get("peer_tickers", []))
    rel_q = fetch_quotes(sorted(related)) if related else {}

    peer_rows = fetch_peers(focus.get("peer_tickers", [])[:5], rel_q)
    focus["_peer_raw"] = peer_rows
    focus["peers"] = peer_rows
    peer_pers = [p["per"] for p in peer_rows if p.get("per")]
    focus["peer_avg_per"] = round(sum(peer_pers) / len(peer_pers), 1) if peer_pers else None
    if chain_pairs:
        focus["chain"] = [
            {"ticker": t, "relation": rel, "last": rel_q[t]["last"], "pct": rel_q[t]["pct"]}
            for t, rel in chain_pairs
            if t in rel_q and rel_q[t].get("pct") is not None
        ][:4]
        focus["chain_kind"] = "밸류체인"
    else:
        # 관계 정의가 없으면 같은 산업 종목들의 실제 등락으로 대체합니다
        focus["chain"] = [
            {"ticker": t, "relation": focus.get("industry", "동일 산업"),
             "last": rel_q[t]["last"], "pct": rel_q[t]["pct"]}
            for t in focus.get("peer_tickers", [])
            if t in rel_q and rel_q[t].get("pct") is not None
        ][:4]
        focus["chain_kind"] = "동일 산업 흐름"

    movers = sorted(
        [c for c in ranked if c.get("pct") is not None], key=lambda x: x["pct"]
    )

    return {
        "generated_at": now.isoformat(),
        "date_kr": now.strftime("%Y.%m.%d"),
        "date_slug": today,
        "weekday_kr": "월화수목금토일"[now.weekday()],
        "market": fetch_market(),
        "sector_rotation": fetch_sector_rotation(),
        "fear_greed": fetch_fear_greed(),
        "focus": focus,
        "runners_up": ranked[1:5],
        "top_gainers": list(reversed(movers[-4:])),
        "top_losers": movers[:4],
        "news": news,
        "korea": fetch_korea(),
    }
