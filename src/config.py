"""수집 대상과 전역 설정. 여기만 고치면 브리핑 내용이 바뀝니다."""

import os
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 카드 상단 지수 스트립에 크게 표시할 4개
HEADLINE_INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
    "^SOX": "필라 반도체",
    "^VIX": "VIX",
}

# ^SOX 가 비면 이걸로 대체
SOX_FALLBACK = "SOXX"

# 하단 매크로 스트립
MACRO = {
    "KRW=X": "원달러",
    "^TNX": "미 10년물",
    "CL=F": "WTI",
    "DX-Y.NYB": "달러인덱스",
}

# 한국장 방향의 가장 강한 선행지표.
# MSCI 한국지수 야간선물은 무료로 못 받아서 뉴욕 상장 한국 ETF 로 대체합니다.
KOREA_PROXY = {
    "EWY": "MSCI 한국 ETF",
}

# 한국 증시와 상관 높은 미국 종목 (요약 재료로만 쓰고 카드에는 안 그림)
WATCHLIST = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "TSLA", "AVGO", "MU", "TSM", "AMD", "INTC",
]

# 뉴스 RSS. API 키가 필요 없는 것만 골랐습니다.
NEWS_FEEDS = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://finance.yahoo.com/news/rssindex",
]
NEWS_MAX_ITEMS = 25

# 카드 크기 — 인스타그램 4:5 비율
CARD_WIDTH = 1080
CARD_HEIGHT = 1350

# GitHub Pages 베이스 URL. 워크플로에서 주입됩니다.
PAGES_BASE = os.environ.get("PAGES_BASE_URL", "").rstrip("/")

OUT_DIR = "out"
DOCS_DIR = "docs"
