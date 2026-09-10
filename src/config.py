"""수집 대상과 전역 설정. 여기만 고치면 브리핑 내용이 바뀝니다."""

import os
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# ── 페이지 2: 시장 맥락 ─────────────────────────────────
HEADLINE_INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
    "^DJI": "다우존스",
    "^RUT": "러셀 2000",
}

CONTEXT_GAUGES = {
    "^VIX": "VIX 변동성",
    "^TNX": "미 국채 10년",
    "DX-Y.NYB": "달러인덱스",
    "CL=F": "WTI 원유",
}

# 섹터 로테이션 — 자금이 어느 업종으로 움직였는지 보여줍니다.
SECTOR_ETFS = {
    "XLK": "기술",
    "SMH": "반도체",
    "XLC": "커뮤니케이션",
    "XLY": "임의소비재",
    "XLF": "금융",
    "XLV": "헬스케어",
    "XLI": "산업재",
    "XLE": "에너지",
    "XLP": "필수소비재",
    "XLU": "유틸리티",
    "XLB": "소재",
    "XLRE": "부동산",
}

# ── 페이지 5: 한국 투자자 참고 ──────────────────────────
KR_CONTEXT = {
    "KRW=X": "원달러 환율",
    "EWY": "MSCI 한국 ETF",
}

# ── 오늘의 종목 선정 ────────────────────────────────────
# 고정 목록이 아니라 매일 Yahoo 스크리너로 전체 시장에서 후보를 새로 뽑습니다.
SCREENS = ["day_gainers", "day_losers", "most_actives"]
SCREEN_COUNT = 100

# 시가총액 하한 — 이보다 작으면 후보에서 제외 (작전주·동전주 방지)
MIN_MARKET_CAP = 3e9      # 30억 달러
# 주가 하한 — 페니스톡 제외
MIN_PRICE = 5.0
# 하루 최소 거래대금
MIN_DOLLAR_VOLUME = 3e7   # 3천만 달러

# 시총 구간별 가중치. 같은 폭으로 움직여도 큰 회사를 우선합니다.
CAP_WEIGHTS = [
    (2e11, 1.30),   # 2000억 달러 이상
    (5e10, 1.18),   # 500억 이상
    (1e10, 1.00),   # 100억 이상
    (0,    0.82),   # 그 미만
]

# 상대거래량 상한 — 이상치가 점수를 지배하지 않도록 자릅니다.
RVOL_CAP = 6.0
RVOL_WEIGHT = 0.45

# 최근 등장한 종목 쿨다운. 같은 종목이 반복되지 않게 감점합니다.
COOLDOWN = [(1, 0.20), (3, 0.45), (7, 0.72), (14, 0.90)]
HISTORY_FILE = "docs/history.json"
HISTORY_KEEP = 40

# 스크리너가 실패했을 때만 쓰는 예비 후보군
FALLBACK_UNIVERSE = [
    "NVDA", "AMD", "AVGO", "MU", "TSM", "INTC", "ARM", "QCOM", "SMCI", "ASML",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NFLX", "ORCL", "CRM", "ADBE",
    "TSLA", "RIVN", "GM", "F", "UBER", "PLTR", "SHOP", "COIN", "HOOD",
    "JPM", "GS", "MS", "BAC", "V", "MA", "BRK-B",
    "LLY", "NVO", "UNH", "PFE", "MRNA", "ABBV", "JNJ",
    "COST", "WMT", "NKE", "SBUX", "DIS", "MCD", "HD",
    "XOM", "CVX", "ENPH", "FSLR", "CAT", "BA", "GE",
]

# 밸류체인 — 관계 자체는 API 로 못 받으므로 주요 종목만 정의해 둡니다.
# 여기 없는 종목은 같은 산업 종목들의 실제 등락률로 대체합니다.
VALUE_CHAIN = {
    "NVDA": [("TSM", "파운드리 위탁생산"), ("MU", "HBM 메모리"), ("SMCI", "AI 서버"),
             ("AVGO", "네트워킹 칩"), ("ARM", "CPU 아키텍처")],
    "AMD":  [("TSM", "파운드리"), ("MU", "메모리"), ("SMCI", "서버")],
    "AVGO": [("TSM", "파운드리"), ("AAPL", "주요 고객사")],
    "TSM":  [("ASML", "노광장비 공급"), ("NVDA", "주요 고객"), ("AAPL", "주요 고객")],
    "ASML": [("TSM", "핵심 고객"), ("INTC", "고객사"), ("MU", "고객사")],
    "MU":   [("NVDA", "HBM 수요처"), ("AAPL", "고객사")],
    "SMCI": [("NVDA", "GPU 공급"), ("AMD", "GPU 공급")],
    "ARM":  [("AAPL", "라이선스 고객"), ("NVDA", "라이선스"), ("QCOM", "라이선스")],
    "AAPL": [("TSM", "칩 위탁생산"), ("QCOM", "모뎀"), ("AVGO", "부품")],
    "MSFT": [("NVDA", "AI 인프라 구매"), ("AMD", "서버 칩")],
    "GOOGL":[("NVDA", "AI 인프라"), ("AVGO", "TPU 공동개발")],
    "AMZN": [("NVDA", "AI 인프라"), ("AVGO", "커스텀 칩")],
    "META": [("NVDA", "AI 인프라"), ("AVGO", "네트워킹")],
    "TSLA": [("NVDA", "자율주행 칩"), ("RIVN", "경쟁사"), ("GM", "경쟁사")],
    "COIN": [("HOOD", "리테일 거래"), ("MSTR", "비트코인 익스포저")],
    "LLY":  [("NVO", "비만치료제 경쟁")],
    "NVO":  [("LLY", "비만치료제 경쟁")],
    "ENPH": [("SEDG", "직접 경쟁"), ("FSLR", "태양광 밸류체인")],
}

# CNN 공포탐욕지수 — 브라우저 UA 를 안 보내면 차단됩니다.
FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
FEAR_GREED_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

NEWS_FEEDS = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://finance.yahoo.com/news/rssindex",
]
NEWS_MAX_ITEMS = 30

CARD_WIDTH = 1080
CARD_HEIGHT = 1350

PAGES_BASE = os.environ.get("PAGES_BASE_URL", "").rstrip("/")
OUT_DIR = "out"
DOCS_DIR = "docs"
