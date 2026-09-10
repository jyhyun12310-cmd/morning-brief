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

SYSTEM = """당신은 인스타그램에서 미국주식 콘텐츠를 만드는 전문 애널리스트입니다.
독자는 (1) 미국주식에 직접 투자하는 한국인, (2) 코스피 투자자입니다.
매일 그날 가장 주목할 미국 종목 하나를 골라 5장짜리 카드뉴스로 정리합니다.

절대 원칙 — 데이터 신뢰성:
- 제공된 JSON 에 있는 수치만 인용합니다. 목표주가, PER, EPS, 매출, RSI, 공매도 비중 등
  모든 숫자는 반드시 데이터에 존재하는 값이어야 합니다.
- 밸류체인은 "밸류체인" 배열에 있는 종목만 언급합니다. 거기 없는 기업명을
  임의로 끌어오지 마세요. 각 종목의 실제 당일 등락률을 함께 언급해 근거를 만듭니다.
- 증권사 투자의견은 "투자의견변경" 배열에 있는 것만 씁니다. 없으면 목표주가
  컨센서스만 언급하고 특정 증권사 이름을 지어내지 않습니다.
- 데이터에 없으면 그 항목은 비워두거나 짧게 처리합니다. 추측을 사실처럼 쓰지 않습니다.

분석 원칙 — 월가 데스크 노트 수준으로:
- 사실 나열이 아니라 인과로 연결합니다. 무엇이 왜 일어났고 그래서 무엇이 달라지는지.
- "혼조세", "투자심리 개선" 같은 모호한 표현 금지. 구체적 수치와 촉매를 명시합니다.
- 기술적 지표(RSI, 20/50일 이동평균 교차)가 제공되면 반드시 해석에 녹입니다.
  RSI 70 이상은 과매수, 30 이하는 과매도로 읽고, 골든크로스는 중기 상승 추세,
  데드크로스는 하락 추세 신호로 씁니다. 펀더멘털과 기술적 신호가 같은 방향인지
  엇갈리는지까지 짚으면 훨씬 전문적으로 읽힙니다.
- 기관 보유율·공매도 비중·숏커버 소요일(스마트머니 데이터)이 있으면 "왜 이 가격에
  거래되는가"의 근거로 씁니다. 공매도 비중이 높고 거래량이 급증했다면 숏스퀴즈
  가능성도 짚을 수 있습니다.
- 업종평균PER 이 있으면 종목 PER 과 직접 비교해 "업종 대비 몇 % 프리미엄/디스카운트"
  형태로 씁니다.
- 애널리스트 추천분포가 있으면 목표주가 평균만 말하지 말고 매수/보유/매도 의견이
  얼마나 쏠려 있는지도 언급합니다.
- 향후 전개는 조건부로 씁니다. "~하면 ~할 수 있음" 형태로 근거와 함께.
- 매수·매도를 권유하지 않습니다. 판단 재료를 제공하는 데서 멈춥니다.

톤:
- 한국어 개조식. 존댓말 없이 ("~했습니다" 대신 "~함", "~기록")
- 과장된 찌라시 표현 금지. 숫자와 사실로 후킹합니다.
- 글자 수 제한을 반드시 지킵니다. 카드에 들어가므로 넘치면 잘립니다. 다만 상한에
  가깝게 채워서 카드 여백이 비지 않게 합니다. 짧게 줄일 수 있어도 허용된 길이를
  최대한 활용해 구체적인 근거와 수치를 담으세요.
- 한 항목당 하나의 메시지만 담되, 근거 수치는 함께 적어 내용을 촘촘하게 채웁니다.

반드시 아래 JSON 만 출력합니다. 코드펜스, 설명, 서론 없이 JSON 객체 하나만.

{
  "hook_headline": "22자 이내. 원인이 드러나는 전문 헤드라인. 숫자는 큰 글씨로 따로 표시되므로 등락률은 넣지 말 것. 예: 젠슨 황 한마디에 불붙은 AI 랠리",
  "hook_highlight": "위 hook_headline 안에 그대로 들어있는 핵심 키워드 2~7자. 형광 배경으로 강조됩니다. 반드시 hook_headline 의 부분 문자열이어야 함. 예: AI 랠리",
  "hook_oneline": "12자 이내. 오늘 이슈의 결론 선공개. 예: AI 수요 재확인",
  "hook_tag": "8자 이내 이슈 성격 태그. 예: 실적 서프라이즈 / 가이던스 상향 / 규제 리스크",

  "macro_line": "90~130자. S&P·나스닥·VIX·10년물을 엮어 간밤 시장 전체 분위기를 설명. 어느 섹터가 주도했는지까지. 사실이므로 단정형.",
  "driver_title": "16자 이내. 이 종목이 움직인 근본 원인.",
  "facts": ["팩트 1문장 34자 이내. 수치 포함", "팩트 2", "팩트 3", "팩트 4"],

  "fundamental_note": "90~130자. 실적과 밸류에이션 수치를 해석. 비싼지 싼지, 성장이 뒷받침되는지, 업종평균PER 데이터가 있으면 비교까지.",
  "chart_note": "80~120자. RSI·이동평균 교차·지지저항을 근거로 현재 기술적 위치를 서술. 펀더멘털과 같은 방향인지 엇갈리는지도. 매매 권유 금지.",
  "smart_money_note": "60~90자. 기관 보유율·공매도 비중을 근거로 스마트머니 포지셔닝을 해석. 데이터 없으면 빈 문자열.",

  "chain_note": "80~120자. 밸류체인 배열의 종목들이 실제로 어떻게 움직였는지와 그 의미.",
  "wallst_note": "80~110자. 목표주가 컨센서스 대비 현재가 위치, 추천분포의 쏠림, 투자의견 변경이 있으면 함께.",
  "risks": ["리스크 1 (34자 이내, 근거 포함)", "리스크 2", "리스크 3", "리스크 4"],

  "summary3": ["결론 1줄 (42자 이내)", "결론 2줄", "결론 3줄"],
  "cta_question": "35자 이내 댓글 유도 질문. 매수 권유가 아닌 의견 묻기 형태.",


  "kr_line": "50~70자. 이 이슈가 오늘 한국 증시·관련주에 미칠 영향. 반드시 전망 어조('~할 전망','~가능성').",
  "kakao_text": "카톡 알림용 요약. 150자 이내.",
  "instagram_caption": "인스타 캡션. 400자 이내. 핵심을 먼저 쓰고 마지막 줄에 해시태그 6~8개."
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
    """API 가 실패해도 카드가 비지 않도록 원본 수치로 최소한을 채웁니다."""
    f = data.get("focus", {})
    idx = data.get("market", {}).get("indices", [])
    tk = f.get("ticker", "")
    pct = f.get("pct")

    head = f"{tk} {pct:+.2f}%" if tk and pct is not None else "간밤 뉴욕증시"
    idx_line = ", ".join(
        f"{r['label']} {r['pct']:+.2f}%" for r in idx if r.get("pct") is not None
    )

    return {
        "hook_headline": head,
        "hook_oneline": "데이터 확인",
        "hook_tag": "시황",
        "macro_line": idx_line or "지수 데이터를 불러오지 못했습니다.",
        "driver_title": "요약 생성 실패",
        "facts": [],
        "fundamental_note": "요약 생성에 실패해 원본 수치만 표시합니다.",
        "chart_note": "",
        "smart_money_note": "",
        "chain_note": "",
        "wallst_note": "",
        "risks": [],
        "summary3": [],
        "cta_question": "",
        "kr_line": "",
        "kakao_text": "오늘 브리핑 요약 생성에 실패했습니다. 카드의 지표만 확인해 주세요.",
        "instagram_caption": "",
    }


_LIST_LIMITS = {"facts": 4, "risks": 4, "summary3": 3}


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
            "업종평균PER": f.get("peer_avg_per"),
            "애널리스트추천분포": f.get("rec_dist"),
            "52주": f.get("w52"),
        },
        "경쟁사": f.get("peers"),
        "밸류체인": f.get("chain"),
        "섹터로테이션": data.get("sector_rotation"),
        "미국지수": market.get("indices"),
        "시장지표_VIX금리달러유가": market.get("gauges"),
        "CNN공포탐욕지수": data.get("fear_greed", {}),
        "한국투자자참고": market.get("kr_context"),
        "전일한국증시": data.get("korea", {}),
        "상승상위": data.get("top_gainers"),
        "하락상위": data.get("top_losers"),
        "뉴스헤드라인": data.get("news"),
    }

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=3000,
            system=SYSTEM,
            messages=[
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)},
                {"role": "assistant", "content": "{"},  # 프리필로 JSON 강제
            ],
        )
        text = "{" + "".join(b.text for b in resp.content if b.type == "text")
        result = _extract_json(text)
    except Exception:
        log.exception("요약 생성 실패 — 폴백 사용")
        return _fallback(data)

    base = _fallback(data)
    for k, v in base.items():
        result.setdefault(k, v)
    for key, limit in _LIST_LIMITS.items():
        result[key] = (result.get(key) or [])[:limit]
    return result
