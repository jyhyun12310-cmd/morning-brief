"""수집한 원자료를 Claude 에게 넘겨 고정 스키마 JSON 으로 받아옵니다.

스키마를 고정해야 매일 같은 레이아웃으로 렌더링됩니다.
"""

from __future__ import annotations

import json
import logging
import os
import re

from anthropic import Anthropic

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

# 요구하는 출력 분량이 한국어 1,800자 남짓이고 한국어는 글자당 1.5~2토큰이라
# 3,000토큰으로는 JSON 이 중간에서 잘려 파싱에 실패합니다. 넉넉히 잡습니다.
MAX_TOKENS = 8000

SYSTEM = """당신은 개인투자자용 미니 리서치 리포트를 만드는 금융 에디터입니다.
매일 시장에서 주목받는 '오늘의 특징주' 하나를 골라 7장으로 정리합니다.

목표는 "주식 초보도 읽기 쉽지만, 금융 전문가가 봐도 허술하지 않은" 콘텐츠입니다.

━━ 가장 중요: 문장 길이 ━━
모바일에서 읽는 콘텐츠입니다. 카드 한 줄에 약 38자가 들어갑니다.
각 설명 문장은 반드시 한 줄 안에 끝나도록 씁니다.

길면 글자를 줄이지 말고 문장을 짧게 다시 쓰세요.
  나쁜 예: "이번 실적 발표를 통해 시장에서는 향후 성장 가능성에 대한 기대감이 더욱 확대되고 있습니다"
  좋은 예: "실적이 개선되며 시장 기대가 커졌습니다"

한 항목에 두 문장 이상 넣지 않습니다. 쉼표로 길게 잇지 않습니다.
정보를 줄이는 것이 곧 전문적인 디자인입니다.

━━ 절대 원칙 ━━
- 제공된 JSON 에 있는 수치만 씁니다. 없는 숫자·기업명·뉴스를 지어내지 않습니다.
- 사실(Fact)과 시장의 기대(Expectation)를 명확히 구분합니다. 기대를 사실처럼
  쓰지 마세요. 기대는 "~할 것으로 기대", "~가능성" 어조로.
- 매수·매도를 권유하지 않습니다. "무조건", "확정", "폭등", "대박", "지금 안 사면
  늦는다", "목표가 XXX" 전부 금지.
- 좋은 이야기만 쓰지 않습니다. 리스크도 제시하되 공포를 조성하지 않습니다.
- 스키마의 설명 문구를 그대로 값으로 넣지 마세요. 실제 내용을 새로 씁니다.

━━ 초보자 배려 ━━
전문 용어는 괄호로 짧게 풉니다. EPS = 주당순이익 / PER = 이익 대비 주가 수준.
다만 내용의 깊이는 낮추지 않습니다.

━━ 문장 리듬 (매우 중요) ━━
기계가 찍어낸 듯한 글이 되지 않게 합니다. 다음을 지키세요.

1. 어미를 반복하지 마세요. 한 페이지 안에서 "~습니다"가 연달아 나오면 안 됩니다.
   나쁜 예: "예상을 넘었습니다 / 신호로 읽혔습니다 / 늘었습니다"
   좋은 예: "예상을 훌쩍 넘었다 / 시장은 이걸 진짜 수요로 읽었다 / 거래량은 평소의 두 배"
   명사로 끝내거나, 반말 서술형("~다")을 섞거나, 숫자로 끝내는 식으로 변주하세요.

2. 같은 페이지의 항목끼리 문장 구조를 다르게 하세요. 전부 "주어 + 동사 + 습니다"로
   맞추지 말고, 어떤 건 짧게 끊고 어떤 건 숫자를 앞에 두는 식으로.

3. 사람이 말하듯 씁니다. "~로 인해", "~에 따라", "~하는 모습을 보였다" 같은
   보고서 투를 피하고 일상어로 씁니다.
   나쁜 예: "실적 개선에 따라 투자 심리가 개선되는 모습"
   좋은 예: "실적이 좋아지자 분위기가 바뀌었다"

4. 뻔한 문구를 쓰지 마세요. "주목받고 있습니다", "관심이 집중", "기대감이 확대",
   "~할 것으로 전망됩니다" 같은 표현은 전부 금지.

5. 같은 단어를 한 페이지에서 두 번 이상 반복하지 마세요.

반드시 아래 JSON 만 출력합니다. 코드펜스, 설명, 서론 없이 JSON 객체 하나만.

{
  "hook1": "14~20자. 표지 첫 줄. 예: 주가는 올랐는데,",
  "hook2": "16~24자. 표지 둘째 줄. 궁금증을 완성. 예: 진짜 이유는 따로 있다",
  "spotlight": "급등 또는 급락의 핵심 이유 한 줄. 24자 이내. 예: AI 서버 수주가 실적으로 확인됐다",

  "p2_headline": "14자 이내. 예: 오늘 시장을 움직인 것들",
  "p2_accent": "p2_headline 안에 그대로 있는 2~5자 핵심 단어",
  "p2_reading": "거시 지표들이 이 종목에 어떤 영향을 줬는지 한 줄. 34자 이내. 예: 금리 상승에도 실적이 버텨준 하루",

  "p3_headline": "14자 이내. 예: 실적의 질을 따져보면",
  "p3_accent": "p3_headline 안의 2~5자 핵심 단어",
  "p3_reading": "실적 숫자의 의미 한 줄. 34자 이내. 예: 매출만 는 게 아니라 남는 돈도 늘었다",

  "p4_headline": "14자 이내. 예: 지금 주가는 비싼가",
  "p4_accent": "p4_headline 안의 2~5자 핵심 단어",
  "p4_premium": "경쟁사 대비 이 종목이 가진 프리미엄 또는 디스카운트 요인 한 줄. 36자 이내. 예: 서버 점유율 1위라는 점이 배수에 반영돼 있다",

  "p5_headline": "14자 이내. 예: 사는 쪽과 파는 쪽",
  "p5_accent": "p5_headline 안의 2~5자 핵심 단어",
  "p5_bull": [
    {"title": "상승 동력 제목 10자 이내", "text": "근거 한 줄. 26자 이내"}
  ],
  "p5_bear": [
    {"title": "리스크 제목 10자 이내", "text": "근거 한 줄. 26자 이내"}
  ],

  "p6_headline": "14자 이내. 예: 스마트머니는 어디에",
  "p6_accent": "p6_headline 안의 2~5자 핵심 단어",
  "p6_reading": "기관 수급과 목표주가가 말해주는 것 한 줄. 36자 이내.",

  "p7_line": "오늘 주목한 이유 한 줄. 34자 이내. 투자 권유가 아닌 객관적 표현으로.",

  "kr_line": "한국 증시 영향 한 줄. 36자 이내. 외국인 순매수·환율 데이터가 있으면 인용. 전망 어조.",
  "kakao_text": "카톡 알림용 요약. 150자 이내.",
  "instagram_caption": "인스타 캡션 본문만. 150~250자. 해시태그·팔로우 유도·종목명은 코드가 붙이므로 넣지 마세요. 무슨 일이 있었고 왜 중요한지 3~4문장으로."
}"""


def _extract_json(text: str) -> dict:
    """모델이 코드펜스를 붙였을 경우까지 방어적으로 파싱."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(text[start : end + 1])


def _fallback(data: dict) -> dict:
    """API 가 실패해도 카드가 자연스럽게 보이도록 원본 수치로 채웁니다.

    데이터 기반 요소(차트·표·게이지)는 AI 와 무관하게 항상 렌더되므로,
    여기서는 문장만 최소한으로 채우고 나머지는 빈 문자열로 둡니다.
    """
    f = data.get("focus", {})
    tk = f.get("ticker", "")
    pct = f.get("pct")
    name = f.get("name") or tk
    rvol = f.get("rvol")
    v = f.get("valuation") or {}
    g = f.get("growth") or {}
    ern = f.get("earnings") or {}
    peer_per = f.get("peer_avg_per")

    direction = "급등" if (pct or 0) >= 5 else "상승" if (pct or 0) > 0 else \
                "급락" if (pct or 0) <= -5 else "하락"

    spot = ""
    if ern.get("surprise") is not None:
        spot = f"실적이 예상보다 {ern['surprise']:+.0f}% 나왔다"
    elif rvol:
        spot = f"거래량이 평소의 {rvol:.1f}배로 늘었다"

    p3 = ""
    if g.get("revenue") is not None:
        p3 = f"매출은 1년 전보다 {g['revenue']*100:+.0f}% 늘었다"

    p4 = ""
    if v.get("forward_per") and peer_per:
        diff = (v["forward_per"] - peer_per) / peer_per * 100
        p4 = f"선행 PER은 업종 평균 대비 {diff:+.0f}% 수준"

    bull, bear = [], []
    if g.get("revenue") is not None and g["revenue"] > 0.1:
        bull.append({"title": "매출 성장", "text": f"전년 대비 {g['revenue']*100:+.0f}%"})
    if ern.get("beat"):
        bull.append({"title": "실적 서프라이즈", "text": "시장 예상을 웃돈 분기"})
    if rvol and rvol >= 1.5:
        bear.append({"title": "단기 변동성", "text": f"거래량 {rvol:.1f}배로 급증"})
    if v.get("forward_per") and peer_per and v["forward_per"] > peer_per:
        bear.append({"title": "밸류 부담", "text": "업종 평균보다 높은 배수"})

    return {
        "hook1": "오늘 시장이", "hook2": "이 종목에 주목했다",
        "spotlight": spot,
        "p2_headline": "오늘 시장을 움직인 것들", "p2_accent": "움직인", "p2_reading": "",
        "p3_headline": "실적의 질을 따져보면", "p3_accent": "실적", "p3_reading": p3,
        "p4_headline": "지금 주가는 비싼가", "p4_accent": "비싼가", "p4_premium": p4,
        "p5_headline": "사는 쪽과 파는 쪽", "p5_accent": "사는 쪽",
        "p5_bull": bull, "p5_bear": bear,
        "p6_headline": "스마트머니는 어디에", "p6_accent": "스마트머니", "p6_reading": "",
        "p7_line": "", "kr_line": "",
        "kakao_text": f"{name} {pct:+.1f}%" if pct is not None else name,
        "instagram_caption": "",
    }


_LIST_LIMITS = {"p5_bull": 3, "p5_bear": 3}

_DROP_FIELDS = ("series", "series_60", "_peer_raw", "spark")


def _slim(rows):
    """시세 행에서 시계열 배열을 떼어냅니다."""
    if not rows:
        return rows
    if isinstance(rows, dict):
        return {k: v for k, v in rows.items() if k not in _DROP_FIELDS}
    return [{k: v for k, v in r.items() if k not in _DROP_FIELDS} for r in rows]


def summarize(data: dict) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    f = data.get("focus", {})
    market = data.get("market", {})
    payload = {
        "날짜": data["date_kr"],
        "오늘의종목": {
            "티커": f.get("ticker"),
            "종목명": f.get("name"),
            "섹터": f.get("sector_kr"),
            "산업": f.get("industry"),
            "사업요약_영문원문": f.get("business_summary", ""),
            "현재가": f.get("last"),
            "등락률": f.get("pct"),
            "시가총액": f.get("market_cap"),
            "밸류에이션": f.get("valuation"),
            "성장률": f.get("growth"),
            "직전실적": f.get("earnings"),
            "분기매출추이": f.get("revenue_history"),
            "목표주가": f.get("analyst"),
            "투자의견변경": f.get("actions"),
            "기술적수준": f.get("levels"),
            "스마트머니_기관공매도베타": f.get("smart_money"),
            "내부자매매": f.get("insider"),
            "주요기관보유자": f.get("inst_top"),
            "재무건전성_부채유동성": f.get("financial_health"),
            "업종평균PER": f.get("peer_avg_per"),
            "애널리스트추천분포": f.get("rec_dist"),
            "52주": f.get("w52"),
        },
        "경쟁사": _slim(f.get("peers")),
        "밸류체인": _slim(f.get("chain")),
        "섹터로테이션": _slim(data.get("sector_rotation")),
        "오늘감지된시장이벤트": data.get("market_events"),
        "미국지수": _slim(market.get("indices")),
        "시장지표_VIX금리달러유가": _slim(market.get("gauges")),
        "CNN공포탐욕지수": data.get("fear_greed", {}),
        "한국투자자참고": _slim(market.get("kr_context")),
        "전일한국증시": data.get("korea", {}),
        "상승상위": _slim(data.get("top_gainers")),
        "하락상위": _slim(data.get("top_losers")),
        "뉴스헤드라인": (data.get("news") or [])[:20],
    }

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "assistant", "content": "{"},  # 프리필로 JSON 강제
            ],
        )
        text = "{" + "".join(b.text for b in resp.content if b.type == "text")

        if getattr(resp, "stop_reason", None) == "max_tokens":
            log.error(
                "응답이 max_tokens(%d)에 걸려 잘렸습니다. 한도를 올리거나 "
                "요구 분량을 줄여야 합니다.", MAX_TOKENS
            )

        result = _extract_json(text)
    except Exception as e:
        # 실패해도 원인을 모르면 매번 추측만 하게 되므로, 다음 확인 때 바로
        # 보이도록 out/error.txt 에 그대로 남깁니다.
        log.exception("요약 생성 실패 — 폴백 사용")
        try:
            import pathlib
            import traceback
            pathlib.Path("out").mkdir(exist_ok=True)
            pathlib.Path("out/error.txt").write_text(
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}", encoding="utf-8"
            )
        except Exception:
            pass
        return _fallback(data)

    base = _fallback(data)
    for k, v in base.items():
        result.setdefault(k, v)
    for key, limit in _LIST_LIMITS.items():
        result[key] = (result.get(key) or [])[:limit]
    return result
