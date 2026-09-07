"""전일 미국장 + 매크로 + 한국 수급 데이터를 모읍니다.

원칙: 어느 한 소스가 죽어도 브리핑 전체가 실패하지 않게 전부 개별로 감쌉니다.
"""

from __future__ import annotations

import datetime as dt
import logging

import feedparser
import pandas as pd
import yfinance as yf

import config as cfg

log = logging.getLogger(__name__)


def _pct_change(closes: pd.Series) -> tuple[float | None, float | None]:
    """마지막 종가와 전일 대비 등락률(%)."""
    s = closes.dropna()
    if len(s) < 2:
        return (float(s.iloc[-1]) if len(s) == 1 else None), None
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    if prev == 0:
        return last, None
    return last, (last - prev) / prev * 100


def fetch_quotes(tickers: list[str]) -> dict[str, dict]:
    """티커 목록의 종가와 등락률을 한 번에 받아옵니다."""
    if not tickers:
        return {}
    try:
        raw = yf.download(
            tickers,
            period="10d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception:
        log.exception("yfinance 다운로드 실패: %s", tickers)
        return {}

    if raw is None or raw.empty:
        return {}

    # yfinance 버전에 따라 티커 1개일 때 Series 로도, 단일 컬럼 DataFrame 으로도 옵니다
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    elif len(tickers) == 1 and len(close.columns) == 1:
        close.columns = [tickers[0]]

    out: dict[str, dict] = {}
    for t in tickers:
        if t not in close.columns:
            continue
        last, pct = _pct_change(close[t])
        if last is None:
            continue
        out[t] = {"last": round(last, 2), "pct": round(pct, 2) if pct is not None else None}
    return out


def fetch_us_market() -> dict:
    """지수 · 매크로 · 한국 프록시 · 관심종목."""
    index_tickers = list(cfg.HEADLINE_INDICES)
    quotes = fetch_quotes(index_tickers + [cfg.SOX_FALLBACK])

    # ^SOX 가 비면 SOXX ETF 로 대체
    if "^SOX" not in quotes and cfg.SOX_FALLBACK in quotes:
        quotes["^SOX"] = quotes[cfg.SOX_FALLBACK]

    indices = [
        {"label": name, "ticker": t, **quotes[t]}
        for t, name in cfg.HEADLINE_INDICES.items()
        if t in quotes
    ]

    macro_q = fetch_quotes(list(cfg.MACRO))
    macro = [
        {"label": name, "ticker": t, **macro_q[t]}
        for t, name in cfg.MACRO.items()
        if t in macro_q
    ]

    proxy_q = fetch_quotes(list(cfg.KOREA_PROXY))
    proxy = [
        {"label": name, "ticker": t, **proxy_q[t]}
        for t, name in cfg.KOREA_PROXY.items()
        if t in proxy_q
    ]

    watch_q = fetch_quotes(cfg.WATCHLIST)
    movers = sorted(
        [{"ticker": t, **v} for t, v in watch_q.items() if v.get("pct") is not None],
        key=lambda x: x["pct"],
    )

    return {
        "indices": indices,
        "macro": macro,
        "korea_proxy": proxy,
        "top_gainers": list(reversed(movers[-5:])),
        "top_losers": movers[:5],
    }


def fetch_news() -> list[dict]:
    """RSS 헤드라인. 기사 원문은 안 가져오고 제목·요약만 씁니다."""
    items: list[dict] = []
    for url in cfg.NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            log.warning("RSS 실패: %s", url)
            continue
        for entry in feed.entries[:12]:
            items.append(
                {
                    "title": getattr(entry, "title", "").strip(),
                    "summary": getattr(entry, "summary", "")[:300].strip(),
                    "source": feed.feed.get("title", ""),
                }
            )
    # 제목 중복 제거
    seen, uniq = set(), []
    for it in items:
        key = it["title"].lower()
        if key and key not in seen:
            seen.add(key)
            uniq.append(it)
    return uniq[: cfg.NEWS_MAX_ITEMS]


def fetch_korea() -> dict:
    """전일 코스피·코스닥 종가와 투자자별 수급."""
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
                biz,
                code,
            )
            if df is None or df.empty:
                continue
            last, pct = _pct_change(df["종가"])
            result[name] = {"last": round(last, 2), "pct": round(pct, 2) if pct else None}

        flow = stock.get_market_trading_value_by_investor(biz, biz, "KOSPI")
        if flow is not None and not flow.empty and "순매수" in flow.columns:
            result["수급"] = {
                k: int(flow.loc[k, "순매수"] / 1e8)  # 억원
                for k in ("외국인", "기관합계", "개인")
                if k in flow.index
            }
    except Exception:
        log.exception("한국 데이터 수집 실패")
    return result


def collect_all() -> dict:
    now = dt.datetime.now(cfg.KST)
    return {
        "generated_at": now.isoformat(),
        "date_kr": now.strftime("%Y.%m.%d"),
        "weekday_kr": "월화수목금토일"[now.weekday()],
        "us": fetch_us_market(),
        "news": fetch_news(),
        "korea": fetch_korea(),
    }
