"""시장 데이터 + 오늘의 종목 딥다이브 데이터를 모읍니다.

원칙: 어느 한 소스가 죽어도 브리핑 전체가 실패하지 않게 전부 개별로 감쌉니다.
yfinance 의 info 필드는 종목마다 누락이 잦아 모든 접근을 방어적으로 처리합니다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import math
import os
import re
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote as urlquote, urlsplit
from zoneinfo import ZoneInfo

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

def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _public_url(value) -> str | None:
    """Keep a supplied HTTP(S) URL; never manufacture an article URL."""
    if isinstance(value, dict):
        value = value.get("url")
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def _published_time(value) -> str | None:
    """Normalize provider time without substituting the collection time."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat(timespec="seconds")
        except (ValueError, OverflowError, OSError):
            return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            try:
                return parsedate_to_datetime(value).isoformat()
            except (ValueError, TypeError, OverflowError):
                return value.strip() or None  # Preserve an unparsed provider date as supplied.
    return None


def _us_market_date(value) -> str | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return dt.datetime.fromtimestamp(value, dt.timezone.utc).astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        pass
    return None


class _FeedText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _feed_text(value) -> str:
    if not isinstance(value, str):
        return ""
    parser = _FeedText()
    parser.feed(value)
    return " ".join("".join(parser.parts).split())


def _provider_source(ticker: str, section: str, scope: str, retrieved_at: str,
                     market_date: str | None = None) -> dict:
    """Reference Yahoo's provider page for fields actually retrieved through yfinance.

    This is provider provenance, not a claim that a company filing or that HTML
    page was downloaded. Section routes are Yahoo's public quote-page routes.
    """
    routes = {"quotes": "history/", "profile": "profile/", "financials": "financials/", "metrics": "key-statistics/"}
    symbol = urlquote(ticker, safe="")
    return {
        "id": "YF_" + re.sub(r"[^A-Z0-9]", "_", ticker.upper()) + "_" + section.upper(),
        "title": f"Yahoo Finance · {ticker} · {section} (yfinance)",
        "url": f"https://finance.yahoo.com/quote/{symbol}/{routes.get(section, '')}",
        "as_of": f"거래일 {market_date}; 수집 {retrieved_at}" if market_date else f"수집 {retrieved_at}",
        "retrieved_at": retrieved_at,
        "market_date": market_date,
        "evidence_scope": scope,
        "source_type": "market_data_provider",
        "retrieval_method": "Yahoo Finance data via yfinance; linked page is a provider reference, not downloaded article text",
        "is_primary_filing": False,
    }


def _collect_sources(data: dict) -> list[dict]:
    """Collect explicit provenance records; unrelated URLs are not evidence."""
    gathered = {}
    def walk(value):
        if isinstance(value, dict):
            if value.get("id") and value.get("title") and value.get("as_of") and _public_url(value.get("url")) and value.get("evidence_scope"):
                gathered.setdefault(value["id"], value)
            for key, child in value.items():
                if key not in {"series", "series_60", "thumbnails"}:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(data)
    return list(gathered.values())


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
    retrieved_at = _utc_now()
    for t in tickers:
        if t not in close.columns:
            continue
        series = close[t].dropna()
        last, pct = _pct_change(close[t])
        if last is None:
            continue
        last_bar = series.index[-1]
        market_date = last_bar.strftime("%Y-%m-%d") if hasattr(last_bar, "strftime") else None
        out[t] = {
            "last": round(last, 2),
            "pct": round(pct, 2) if pct is not None else None,
            "series": [round(float(v), 4) for v in series.tail(10)],
            "series_60": [round(float(v), 4) for v in series.tail(60)],
            "market_date": market_date,
            "quote_as_of": last_bar.isoformat() if hasattr(last_bar, "isoformat") else str(last_bar),
            "retrieved_at": retrieved_at,
            "quote_basis": "Yahoo daily Close, auto_adjust=False; last available daily bar, not proof that today's session has closed",
            "source": _provider_source(t, "quotes", "daily Close, daily change and price history", retrieved_at, market_date),
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
                "quote_as_of": _published_time(q.get("regularMarketTime")),
                "market_date": _us_market_date(q.get("regularMarketTime")),
                "source": _provider_source(sym, "screener", "Yahoo screener regularMarketPrice, change, market cap and volume", _utc_now()),
            }
    log.info("스크리너 후보 %d개 확보", len(found))
    return found


def _passes_filter(c: dict) -> bool:
    """작전주·페니스톡·거래 부진 종목과 이상치를 걸러냅니다."""
    if c["market_cap"] < cfg.MIN_MARKET_CAP:
        return False
    if c["last"] < cfg.MIN_PRICE:
        return False
    if c["last"] * c["volume"] < cfg.MIN_DOLLAR_VOLUME:
        return False
    if abs(c["pct"]) > cfg.MAX_ABS_PCT:
        return False
    return True


# 회사명에서 떼어낼 법인격 표기. "Oracle Corporation" -> "ORACLE"
_CORP_SUFFIXES = (
    " CORPORATION", " CORP", " INCORPORATED", " INC", " COMPANY", " CO",
    " LIMITED", " LTD", " PLC", " HOLDINGS", " HOLDING", " GROUP",
    " TECHNOLOGIES", " TECHNOLOGY", " SYSTEMS", " CLASS A", " CLASS B",
    " & CO", ".COM", ",",
)


def _company_key(name: str) -> str:
    """뉴스 헤드라인과 대조할 회사명 핵심부를 뽑습니다.

    헤드라인은 티커가 아니라 회사명으로 쓰이는 경우가 대부분이라
    ("Oracle surges..." 처럼), 티커만 찾으면 뉴스를 놓칩니다.
    """
    key = (name or "").upper().strip()
    for suf in _CORP_SUFFIXES:
        key = key.replace(suf, " ")
    key = re.sub(r"[^A-Z0-9 ]+", " ", key)   # 남은 구두점 제거
    key = " ".join(key.split())
    return key[:18].strip()


def _has_news(c: dict, blob: str) -> bool:
    """티커 또는 회사명이 헤드라인에 등장하는지.

    헤드라인 쪽도 같은 방식으로 구두점을 지워서 비교하므로
    "AT&T" 와 "ATT" 처럼 표기가 달라도 잡힙니다.
    """
    tk = c["ticker"]
    # 티커는 짧아서 우연히 다른 단어에 섞일 수 있으므로 단어 경계로 확인
    if len(tk) >= 3 and re.search(rf"\b{re.escape(tk)}\b", blob):
        return True

    key = _company_key(c.get("name", ""))
    if not key:
        return False
    flat_blob = re.sub(r"[^A-Z0-9 ]+", "", blob.upper())
    flat_key = key.replace(" ", "")
    if len(flat_key) >= 4 and flat_key in flat_blob.replace(" ", ""):
        return True
    # 두 단어 이상이면 첫 단어만으로도 (예: "ADVANCED MICRO DEV" -> "ADVANCED")
    head = key.split(" ")[0]
    return len(head) >= 5 and head in flat_blob


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
        # 등락률은 로그로 눌러 큰 변동이 점수를 독식하지 않게 합니다.
        # 제곱근 계열(**0.7)로는 -15% 종목이 -5% 종목의 2배 이상을 가져가
        # 뉴스·시총 가중치가 뒤집히지 못했습니다.
        move = math.log1p(abs(c["pct"]))
        rvol = min(c.get("rvol") or 1.0, cfg.RVOL_CAP)
        vol_boost = 1 + (rvol - 1) * cfg.RVOL_WEIGHT
        cap_w = _cap_weight(c["market_cap"])

        news_hit = _has_news(c, blob)
        news_mult = cfg.NEWS_MULT if news_hit else 1.0

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
        {"label": name, "ticker": t, "pct": q[t]["pct"], "last": q[t]["last"],
         "market_date": q[t].get("market_date"), "source": q[t].get("source")}
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
    """직전 실적 상세 + 최근 4분기 서프라이즈 패턴 + 다음 발표일.

    yfinance 의 earnings_dates 는 과거(발표됨)와 미래(예정) 행이 섞여 있어,
    Reported EPS 유무로 구분합니다.
    """
    try:
        df = tk.earnings_dates
        if df is None or df.empty:
            return {}
        df = df.sort_index(ascending=False)  # 최신이 위로

        reported = df[df["Reported EPS"].notna()]
        upcoming = df[df["Reported EPS"].isna()]
        out: dict = {}

        if not reported.empty:
            row = reported.iloc[0]
            est, act = _num(row.get("EPS Estimate")), _num(row.get("Reported EPS"))
            if est is not None and act is not None:
                surprise = _num(row.get("Surprise(%)"))
                if surprise is None and est:
                    surprise = (act - est) / abs(est) * 100
                out.update({
                    "date": reported.index[0].strftime("%Y.%m.%d"),
                    "eps_est": round(est, 2),
                    "eps_act": round(act, 2),
                    "surprise": round(surprise, 1) if surprise is not None else None,
                    "beat": act >= est,
                    "accounting_basis": "Yahoo provider EPS; GAAP versus adjusted basis not specified",
                    "period_note": "date is the earnings announcement date, not the reported quarter end",
                    "surprise_comparable": bool(est > 0 and act >= 0),
                    "surprise_note": "EPS crossing zero or non-positive estimates must be explained in amounts, not a beat percentage",
                })

            # 최근 4분기 beat/miss 패턴 (오래된 → 최신 순으로 뒤집어서 저장)
            history = []
            for _, r in reported.head(4).iloc[::-1].iterrows():
                e, a = _num(r.get("EPS Estimate")), _num(r.get("Reported EPS"))
                if e is not None and a is not None:
                    history.append(bool(a >= e))
            out["history"] = history
            streak = 0
            for beat in reversed(history):
                if beat:
                    streak += 1
                else:
                    break
            out["streak"] = streak

        if not upcoming.empty:
            out["next_date"] = upcoming.index.min().strftime("%Y.%m.%d")

        return out
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
            out.append({"period": period.strftime("%y.%m"), "value": v,
                        "period_end": period.strftime("%Y-%m-%d"),
                        "period_type": "quarterly", "provider_field": "Total Revenue"})
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


def _insider_activity(tk: yf.Ticker) -> dict:
    """최근 내부자 매매. 임원의 자사주 매수는 가장 직접적인 스마트머니 신호입니다.

    'Transaction' 텍스트가 종목마다 조금씩 달라("Sale", "Sale (Sell)" 등) 부분
    문자열 매칭으로 판정합니다.
    """
    try:
        df = tk.insider_transactions
        if df is None or df.empty:
            return {}
        recent = df.head(10)
        buys, sells = [], []
        for _, r in recent.iterrows():
            txt = str(r.get("Transaction", "")).lower()
            shares = _num(r.get("Shares"))
            if shares is None:
                continue
            entry = {
                "name": str(r.get("Insider", ""))[:22],
                "position": str(r.get("Position", ""))[:20],
                "shares": shares,
                "value": _num(r.get("Value")),
            }
            if "sale" in txt or "sell" in txt:
                sells.append(entry)
            elif "purchase" in txt or "buy" in txt:
                buys.append(entry)

        if not buys and not sells:
            return {}

        top_buy = max(buys, key=lambda x: x.get("value") or 0) if buys else None
        return {
            "buy_count": len(buys),
            "sell_count": len(sells),
            "net_shares": sum(b["shares"] for b in buys) - sum(s["shares"] for s in sells),
            "top_buy": top_buy,
        }
    except Exception:
        log.warning("내부자 매매 데이터 없음")
        return {}


def _institutional_top(tk: yf.Ticker) -> list[dict]:
    """상위 기관 보유자 3곳. 합계 비율보다 구체적인 근거가 됩니다."""
    try:
        df = tk.institutional_holders
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.head(3).iterrows():
            pct = _num(r.get("pctHeld"))
            name = r.get("Holder")
            if pct is None or not name:
                continue
            out.append({"name": str(name)[:22], "pct": pct})
        return out
    except Exception:
        log.warning("기관 보유자 데이터 없음")
        return []


def _hist_volatility(series: list[float]) -> float | None:
    """60일 종가로 연율화 실현변동성(%)을 계산. VIX(내재변동성)와 비교하는 용도."""
    pts = [float(v) for v in (series or []) if v is not None]
    if len(pts) < 20:
        return None
    rets = [pts[i] / pts[i - 1] - 1 for i in range(1, len(pts)) if pts[i - 1]]
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    daily_sd = var ** 0.5
    return round(daily_sd * (252 ** 0.5) * 100, 1)


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
    # 회사 소개 문단 — 이미 받아오던 info 안에 있던 필드입니다.
    # 원문은 길고 영어라 그대로 안 쓰고, 요약 단계에서 AI 가 1~2문장으로 축약합니다.
    focus["business_summary"] = info.get("longBusinessSummary") or ""
    focus["currency"] = info.get("currency")
    focus["financial_currency"] = info.get("financialCurrency")
    focus["financial_period_end"] = _published_time(info.get("mostRecentQuarter"))
    focus["financial_period_note"] = "mostRecentQuarter is provider metadata; individual fields may use TTM, annual or forward periods"
    retrieved_at = _utc_now()
    focus["sources"] = []
    if info:
        focus["sources"].append(_provider_source(ticker, "metrics",
            "Ticker.info supplied valuation, growth, analyst targets, holdings and financial ratios; not primary filings", retrieved_at))
    if focus["business_summary"]:
        focus["sources"].append(_provider_source(ticker, "profile",
            "Ticker.info longBusinessSummary, sector and industry; provider company description", retrieved_at))
    focus["provenance"] = {
        "retrieved_at": retrieved_at,
        "provider": "Yahoo Finance via yfinance",
        "profile_basis": "provider company description; primary filing not downloaded",
        "valuation.margin": "profitMargins: net profit margin, not operating margin",
        "valuation.per": "trailingPE: provider trailing P/E",
        "valuation.forward_per": "forwardPE: provider forward P/E based on estimates",
        "growth.revenue": "revenueGrowth: provider-reported growth; exact period must be checked against statement period metadata",
        "growth.earnings": "earningsGrowth: provider-reported growth; exact accounting basis not supplied",
        "analyst": "provider consensus; analyst coverage date and individual methodology not supplied",
    }

    focus["valuation"] = {
        "per": _num(info.get("trailingPE")),
        "forward_per": _num(info.get("forwardPE")),
        "pbr": _num(info.get("priceToBook")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        "ev_sales": _num(info.get("enterpriseToRevenue")),
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
    if focus["revenue_history"]:
        financial_source = _provider_source(ticker, "financials",
            "Ticker.quarterly_income_stmt Total Revenue by exact period_end; provider financial statement data, not primary filing", retrieved_at)
        focus["sources"].append(financial_source)
        focus["revenue_source"] = financial_source["title"] + " | " + financial_source["url"]
        for row in focus["revenue_history"]:
            row["currency"] = focus["financial_currency"]
            row["source_id"] = financial_source["id"]
    if focus["earnings"]:
        earnings_source = _provider_source(ticker, "earnings",
            "Ticker.earnings_dates: provider EPS estimate/reported EPS and announcement dates; GAAP/adjusted basis unspecified", retrieved_at)
        focus["sources"].append(earnings_source)
        focus["earnings"]["source_id"] = earnings_source["id"]
    focus["actions"] = _analyst_actions(tk)
    focus["rec_dist"] = _rec_distribution(tk)
    focus["smart_money"] = _smart_money(info)
    focus["insider"] = _insider_activity(tk)
    focus["inst_top"] = _institutional_top(tk)
    focus["financial_health"] = {
        "debt_equity": _num(info.get("debtToEquity")),
        "current_ratio": _num(info.get("currentRatio")),
        "quick_ratio": _num(info.get("quickRatio")),
    }

    levels = _levels(quote.get("series_60"), quote.get("last", 0))
    levels["rsi"] = _rsi(quote.get("series_60"))
    levels["hist_vol"] = _hist_volatility(quote.get("series_60"))
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
    """경쟁사 비교표용. 이미 받은 시세에 밸류에이션 지표를 덧붙입니다.

    스펙상 비교표에 Forward P/E · EV/Sales · 투자의견이 들어가므로 함께 받아옵니다.
    """
    out = []
    for t in tickers:
        row = {"ticker": t, **quotes.get(t, {})}
        try:
            info = yf.Ticker(t).info or {}
            row["name"] = info.get("shortName") or t
            row["per"] = _num(info.get("trailingPE"))
            row["fwd_per"] = _num(info.get("forwardPE"))
            row["ev_sales"] = _num(info.get("enterpriseToRevenue"))
            row["rec"] = info.get("recommendationKey", "")
            row["market_cap"] = _num(info.get("marketCap"))
            row["metrics_source"] = _provider_source(t, "metrics", "Ticker.info peer valuation and analyst recommendation fields", _utc_now())
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

def _news_thumbnails(raw: dict, title: str, publisher: str, article_url: str | None) -> list[dict]:
    """Return supplied image metadata only; downloading/rights checks belong downstream."""
    candidates = []
    thumbnail = raw.get("thumbnail") or {}
    if isinstance(thumbnail, dict):
        candidates.extend(thumbnail.get("resolutions") or [])
        if thumbnail.get("originalUrl"):
            candidates.append({"url": thumbnail["originalUrl"], "width": thumbnail.get("originalWidth"),
                               "height": thumbnail.get("originalHeight")})
    elif isinstance(thumbnail, str):
        candidates.append({"url": thumbnail})
    for key in ("media_thumbnail", "media_content"):
        for item in raw.get(key) or []:
            if isinstance(item, dict) and (key == "media_thumbnail" or str(item.get("type", "")).startswith("image/") or item.get("medium") == "image"):
                candidates.append(item)
    for item in raw.get("links") or []:
        if isinstance(item, dict) and item.get("rel") == "enclosure" and str(item.get("type", "")).startswith("image/"):
            candidates.append({**item, "url": item.get("href")})
    out, seen = [], set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = _public_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "width": _num(item.get("width")), "height": _num(item.get("height")),
                    "caption": _feed_text(item.get("caption")) or title,
                    "caption_basis": "supplied image caption" if item.get("caption") else "article headline, not an independently verified image description",
                    "publisher": publisher, "article_url": article_url,
                    "license": "not supplied by news metadata"})
    return sorted(out, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)


def _news_source(item: dict) -> dict | None:
    url = _public_url(item.get("url"))
    if not url:
        return None
    return {"id": "NEWS_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12],
            "title": item["title"], "url": url,
            "as_of": item.get("published_at") or ("발표일 미제공; 수집 " + item["retrieved_at"]),
            "retrieved_at": item["retrieved_at"], "publisher": item.get("publisher", ""),
            "evidence_scope": item["content_scope"], "source_type": "news_metadata_or_feed_text",
            "is_full_article": False}


def _dedupe_news(items: list[dict], limit: int | None = None) -> list[dict]:
    out, seen = [], set()
    for item in items:
        key = item.get("url") or item.get("title", "").casefold()
        if key and item.get("title") and key not in seen:
            seen.add(key)
            out.append(item)
    return out[:limit] if limit is not None else out


def fetch_news() -> list[dict]:
    """Preserve the RSS evidence and its real links instead of title-only records."""
    items: list[dict] = []
    for url in cfg.NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            log.warning("RSS 실패: %s", url)
            continue
        feed_info = getattr(feed, "feed", {}) or {}
        retrieved_at = _utc_now()
        for entry in (getattr(feed, "entries", []) or [])[:14]:
            try:
                title = _feed_text(entry.get("title", ""))
                summary = _feed_text(entry.get("summary", ""))
                parts = [_feed_text(part.get("value", "")) for part in (entry.get("content") or []) if isinstance(part, dict)]
                content = "\n\n".join(part for part in parts if part)
                article_url = _public_url(entry.get("link"))
                if not article_url:
                    article_url = next((_public_url(link.get("href")) for link in entry.get("links", [])
                                        if isinstance(link, dict) and link.get("rel", "alternate") == "alternate"
                                        and _public_url(link.get("href"))), None)
                entry_source = entry.get("source") or {}
                publisher = str(entry_source.get("title") or feed_info.get("title") or urlsplit(url).hostname or "")
                item = {"title": title, "summary": summary, "body": content or summary,
                        "content_scope": "RSS content/synopsis only; linked article full text not fetched",
                        "url": article_url, "article_url": article_url, "feed_url": url,
                        "publisher": publisher, "published_at": _published_time(entry.get("published")),
                        "updated_at": _published_time(entry.get("updated")), "retrieved_at": retrieved_at,
                        "body_format": "plain_text_from_rss", "is_full_article": False}
                item["thumbnails"] = _news_thumbnails(entry, title, publisher, article_url)
                item["source"] = _news_source(item)
                items.append(item)
            except Exception:
                log.warning("RSS 개별 항목 해석 실패: %s", url)
    return _dedupe_news(items, cfg.NEWS_MAX_ITEMS)


def fetch_ticker_news(ticker: str, count: int = 12) -> list[dict]:
    """Normalize both nested content and legacy Yahoo news shapes without scraping pages.

    Official method: Ticker.get_news(count=10, tab='news'). Older installed
    yfinance versions may expose only the news property or a no-argument method.
    """
    try:
        tk = yf.Ticker(ticker)
        getter = getattr(tk, "get_news", None)
        if callable(getter):
            try:
                rows = getter(count=count, tab="news")
            except TypeError:
                rows = getter()
        else:
            rows = tk.news
        if not isinstance(rows, list):
            return []
    except Exception:
        log.warning("종목 뉴스 조회 실패: %s — RSS 및 확인된 재무자료로 계속", ticker)
        return []
    retrieved_at, normalized = _utc_now(), []
    for row in rows[:count]:
        if not isinstance(row, dict):
            continue
        try:
            content = row.get("content") if isinstance(row.get("content"), dict) else row
            title = _feed_text(content.get("title") or row.get("title"))
            url = (_public_url(content.get("canonicalUrl")) or _public_url(content.get("clickThroughUrl"))
                   or _public_url(content.get("link")) or _public_url(row.get("link")))
            provider = content.get("provider") or {}
            publisher = str(provider.get("displayName") if isinstance(provider, dict) else provider)
            publisher = publisher if publisher and publisher != "None" else str(content.get("publisher") or row.get("publisher") or "Yahoo Finance news feed")
            summary = _feed_text(content.get("summary") or content.get("description") or row.get("summary"))
            item = {"title": title, "summary": summary, "body": summary,
                    "url": url, "article_url": url, "feed_url": None, "publisher": publisher,
                    "published_at": _published_time(content.get("pubDate") or content.get("providerPublishTime") or row.get("providerPublishTime")),
                    "retrieved_at": retrieved_at, "content_scope": "Yahoo supplied headline/synopsis only; linked article full text not fetched",
                    "is_full_article": False, "body_format": "provider_synopsis",
                    "requested_ticker": ticker, "related_tickers": content.get("relatedTickers") or row.get("relatedTickers") or [],
                    "relevance_note": "returned by ticker news endpoint; relevance must be checked against title/synopsis"}
            item["thumbnails"] = _news_thumbnails(content, title, publisher, url)
            item["source"] = _news_source(item)
            normalized.append(item)
        except Exception:
            log.warning("종목 뉴스 개별 항목 해석 실패: %s", ticker)
    return _dedupe_news(normalized, count)


def fetch_korea() -> dict:
    result: dict = {}
    if not os.environ.get("KRX_ID") or not os.environ.get("KRX_PW"):
        log.info("KRX 인증 정보 미설정 — 선택 항목인 한국 지수·수급 수집 생략")
        return result
    try:
        from pykrx import stock
    except Exception:
        log.warning("pykrx 미설치 — 한국 데이터 건너뜀")
        return result

    # 영업일 확정을 먼저 합니다. 이게 실패하면 이후 조회가 전부 의미 없습니다.
    try:
        today = dt.datetime.now(cfg.KST).strftime("%Y%m%d")
        biz = stock.get_nearest_business_day_in_a_week(date=today, prev=True)
        result["date"] = biz
    except Exception:
        log.exception("한국 영업일 조회 실패")
        return result

    try:
        start = (dt.datetime.strptime(biz, "%Y%m%d") - dt.timedelta(days=10)).strftime("%Y%m%d")
        for name, code in (("코스피", "1001"), ("코스닥", "2001")):
            df = stock.get_index_ohlcv(start, biz, code)
            if df is None or df.empty:
                continue
            last, pct = _pct_change(df["종가"])
            result[name] = {"last": round(last, 2), "pct": round(pct, 2) if pct else None}
    except Exception:
        log.exception("한국 지수 수집 실패")

    # 투자자별 순매수 — 외국인이 사는지 파는지가 국내 증시 스토리의 핵심입니다.
    try:
        flow = stock.get_market_trading_value_by_investor(biz, biz, "KOSPI")
        if flow is not None and not flow.empty and "순매수" in flow.columns:
            picks = {}
            for label, key in (("외국인", "외국인합계"), ("기관", "기관합계"), ("개인", "개인")):
                if key in flow.index:
                    val = _num(flow.loc[key, "순매수"])
                    if val is not None:
                        picks[label] = round(val / 1e8)  # 억원 단위
            if picks:
                result["수급"] = picks
    except Exception:
        log.warning("한국 투자자별 수급 수집 실패")

    return result


# ══ 오케스트레이션 ══════════════════════════════════════

def _josa_ro(word: str) -> str:
    """'로' / '으로' 를 받침에 맞춰 고릅니다. (ㄹ 받침은 '로')"""
    if not word:
        return "로"
    last = word[-1]
    if not ("가" <= last <= "힣"):
        return "로"
    jong = (ord(last) - 0xAC00) % 28
    return "로" if jong in (0, 8) else "으로"


def detect_market_events(market: dict, fear_greed: dict, sectors: list[dict],
                         korea: dict) -> list[dict]:
    """그날 시장에서 실제로 벌어진 '이야깃거리'를 조건에 맞을 때만 뽑아냅니다.

    AI 에게 "재미있게 써줘"라고 맡기면 매일 뻔한 소리가 나오므로, 실제 수치가
    특정 조건을 넘었을 때만 해당 스토리를 만들어 넘깁니다. 조건에 안 걸리면
    그날은 그 이야기를 안 합니다.
    """
    events: list[dict] = []
    gauges = {g["ticker"]: g for g in market.get("gauges", [])}
    indices = {i["ticker"]: i for i in market.get("indices", [])}

    # 1) 금리 급변 — 10년물이 하루 2% 이상 움직이면 주식시장 전체에 파급됩니다
    tnx = gauges.get("^TNX")
    if tnx and tnx.get("pct") is not None and abs(tnx["pct"]) >= 2.0:
        up = tnx["pct"] > 0
        events.append({
            "kind": "금리",
            "headline": f"미 10년물 국채금리 {tnx['last']:.2f}%",
            "value": f"{tnx['pct']:+.2f}%",
            "context": (
                "금리가 오르면 미래 이익을 당겨쓰는 성장주·기술주가 먼저 눌립니다"
                if up else
                "금리가 내리면 성장주 밸류에이션 부담이 줄어 기술주에 우호적입니다"
            ),
            "tone": "dn" if up else "up",
        })

    # 2) 공포탐욕 급변 — 일주일 전 대비 15포인트 이상 이동
    fg = fear_greed or {}
    if fg.get("score") is not None and fg.get("week_ago") is not None:
        delta = fg["score"] - fg["week_ago"]
        if abs(delta) >= 15:
            events.append({
                "kind": "투자심리",
                "headline": f"공포탐욕지수 {fg['score']} ({fg['label']})",
                "value": f"1주 전 대비 {delta:+.0f}",
                "context": (
                    "시장 심리가 빠르게 탐욕으로 기울면 단기 과열 신호로 읽힙니다"
                    if delta > 0 else
                    "심리가 급격히 얼어붙을 때는 통상 반등 재료에도 시장이 둔감해집니다"
                ),
                "tone": "hl",
            })

    # 3) 달러 강세/약세 — 한국 투자자에게 직접 영향
    dxy = gauges.get("DX-Y.NYB")
    if dxy and dxy.get("pct") is not None and abs(dxy["pct"]) >= 0.5:
        strong = dxy["pct"] > 0
        events.append({
            "kind": "달러",
            "headline": f"달러인덱스 {dxy['last']:.1f}",
            "value": f"{dxy['pct']:+.2f}%",
            "context": (
                "달러가 강해지면 원화 환산 수익은 늘지만 신흥국 증시엔 자금 유출 압력"
                if strong else
                "달러 약세는 외국인 자금이 한국 같은 신흥국으로 흘러들 여건을 만듭니다"
            ),
            "tone": "dn" if strong else "up",
        })

    # 4) 유가 급변 — 물가·운송비로 이어지는 연결고리
    oil = gauges.get("CL=F")
    if oil and oil.get("pct") is not None and abs(oil["pct"]) >= 2.5:
        up = oil["pct"] > 0
        events.append({
            "kind": "유가",
            "headline": f"WTI 원유 ${oil['last']:.1f}",
            "value": f"{oil['pct']:+.2f}%",
            "context": (
                "유가 상승은 항공·운송 비용을 밀어올리고 물가 부담으로 되돌아옵니다"
                if up else
                "유가 하락은 물가 압력을 낮춰 중앙은행의 금리 인하 여지를 넓힙니다"
            ),
            "tone": "dn" if up else "up",
        })

    # 5) 섹터 쏠림 — 1등과 꼴찌 격차가 2.5%p 이상이면 자금이 확실히 이동한 날
    if len(sectors) >= 2:
        top, bottom = sectors[0], sectors[-1]
        gap = top["pct"] - bottom["pct"]
        if gap >= 2.5:
            events.append({
                "kind": "섹터",
                "headline": f"{top['label']} vs {bottom['label']}",
                "value": f"{gap:.1f}%p 격차",
                "context": f"돈이 {bottom['label']}에서 빠져나와 "
                           f"{top['label']}{_josa_ro(top['label'])} 몰린 하루",
                "tone": "hl",
            })

    # 6) VIX 급등 — 공포가 실제로 커진 날
    vix = gauges.get("^VIX")
    if vix and vix.get("pct") is not None and vix["pct"] >= 10:
        events.append({
            "kind": "변동성",
            "headline": f"VIX {vix['last']:.1f}",
            "value": f"{vix['pct']:+.1f}%",
            "context": "VIX 급등은 기관이 하락 보험을 사들이고 있다는 뜻입니다",
            "tone": "dn",
        })

    # 7) 외국인 수급 — 한국 증시 방향을 좌우하는 주체
    flow = (korea or {}).get("수급") or {}
    foreign = flow.get("외국인")
    if foreign is not None and abs(foreign) >= 3000:
        buying = foreign > 0
        events.append({
            "kind": "국내수급",
            "headline": "코스피 외국인",
            "value": f"{foreign:+,}억원",
            "context": (
                "외국인이 대규모로 사들이면 지수 상승 탄력이 붙는 경우가 많습니다"
                if buying else
                "외국인 매도가 이어지면 지수 반등이 나와도 힘이 실리기 어렵습니다"
            ),
            "tone": "up" if buying else "dn",
        })

    return events


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
                            "avg_volume": None, "rvol": None, "market_date": v.get("market_date"),
                            "quote_as_of": v.get("quote_as_of"), "source": v.get("source")}

    # 2) 복합 점수로 정렬
    ranked = score_candidates(cands, news, history, today)
    if not ranked:
        log.error("선정 가능한 후보가 없습니다")
        result = {"generated_at": now.isoformat(), "date_kr": now.strftime("%Y.%m.%d"),
                "weekday_kr": "월화수목금토일"[now.weekday()], "market": fetch_market(),
                "fear_greed": {}, "focus": {}, "news": news, "korea": fetch_korea(),
                "sector_rotation": [], "ranked": []}
        result["sources"] = _collect_sources(result)
        return result

    top = ranked[0]
    log.info("오늘의 종목: %s (점수 %.2f, 등락 %+.2f%%, RVOL %s, 뉴스 %s)",
             top["ticker"], top["score"], top["pct"], top.get("rvol"), top["news_hit"])

    # 3) 주인공 + 밸류체인 + 피어 시세를 한 번에
    chain_pairs = cfg.VALUE_CHAIN.get(top["ticker"], [])
    focus_q = fetch_quotes([top["ticker"]])
    quote = focus_q.get(top["ticker"], {"last": top["last"], "pct": top["pct"],
                                        "series": [], "series_60": [], "market_date": top.get("market_date"),
                                        "quote_as_of": top.get("quote_as_of"), "source": top.get("source"),
                                        "quote_basis": "Yahoo screener regularMarketPrice; historical quote download unavailable"})
    # peer_tickers 는 industry 조회가 필요해 focus 안에서 채워지므로,
    # fetch_focus 가 끝난 뒤에 그 결과로 경쟁사 시세를 조회합니다.
    focus = fetch_focus(top["ticker"], quote, top)
    focus_news = _dedupe_news(fetch_ticker_news(top["ticker"]) + [
        item for item in news if _has_news(top, item.get("title", "").upper())])
    news = _dedupe_news(focus_news + news)

    related = {t for t, _ in chain_pairs} | set(focus.get("peer_tickers", []))
    rel_q = fetch_quotes(sorted(related)) if related else {}

    peer_rows = fetch_peers(focus.get("peer_tickers", [])[:5], rel_q)
    focus["peers"] = peer_rows
    peer_pers = [p["per"] for p in peer_rows if p.get("per")]
    focus["peer_avg_per"] = round(sum(peer_pers) / len(peer_pers), 1) if peer_pers else None
    if chain_pairs:
        focus["chain"] = [
            {"ticker": t, "relation": rel, "last": rel_q[t]["last"], "pct": rel_q[t]["pct"],
             "market_date": rel_q[t].get("market_date"), "source": rel_q[t].get("source")}
            for t, rel in chain_pairs
            if t in rel_q and rel_q[t].get("pct") is not None
        ][:4]
        focus["chain_kind"] = "밸류체인"
    else:
        # 관계 정의가 없으면 같은 산업 종목들의 실제 등락으로 대체합니다
        focus["chain"] = [
            {"ticker": t, "relation": focus.get("industry", "동일 산업"),
             "last": rel_q[t]["last"], "pct": rel_q[t]["pct"],
             "market_date": rel_q[t].get("market_date"), "source": rel_q[t].get("source")}
            for t in focus.get("peer_tickers", [])
            if t in rel_q and rel_q[t].get("pct") is not None
        ][:4]
        focus["chain_kind"] = "동일 산업 흐름"

    movers = sorted(
        [c for c in ranked if c.get("pct") is not None], key=lambda x: x["pct"]
    )

    market_data = fetch_market()
    sectors = fetch_sector_rotation()
    fg = fetch_fear_greed()
    korea = fetch_korea()
    events = detect_market_events(market_data, fg, sectors, korea)
    log.info("감지된 시장 이벤트 %d개: %s", len(events), [e["kind"] for e in events])

    result = {
        "generated_at": now.isoformat(),
        "date_kr": now.strftime("%Y.%m.%d"),
        "date_slug": today,
        "weekday_kr": "월화수목금토일"[now.weekday()],
        "market": market_data,
        "sector_rotation": sectors,
        "fear_greed": fg,
        "market_events": events,
        "focus": focus,
        "runners_up": ranked[1:5],
        "top_gainers": list(reversed(movers[-4:])),
        "top_losers": movers[:4],
        "news": news,
        "focus_news": focus_news,
        "image_candidates": [{**image, "requested_ticker": top["ticker"]}
                             for item in focus_news for image in item.get("thumbnails", [])],
        "market_date": focus.get("market_date"),
        "date_note": "date_kr is the collection/publication date; market_date is the last available quote's trading date",
        "korea": korea,
    }
    result["sources"] = _collect_sources(result)
    return result
