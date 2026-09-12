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

SYSTEM = """당신은 미국 증시를 쉽게 풀어주는 인스타그램 카드뉴스 에디터입니다.
매일 아침 전날 미국 시장에서 실제로 중요했던 일 하나를 골라 5장으로 압축합니다.

목표는 뉴스 전달이 아닙니다. 독자가 이런 흐름을 타게 만드는 것입니다.
"어? 무슨 일이지?" → "아 이런 일이 있었구나" → "근데 이게 왜 중요하지?"
→ "그럼 어떤 기업을 봐야 하지?" → "내일도 이 계정 봐야겠다"

━━ 주제 선정 ━━
제공된 데이터에서 그날 가장 중요한 이야기 하나를 고릅니다. 후보는 두 갈래입니다.
(1) 오늘의종목 — 개별 기업의 실적·가이던스·급등락
(2) 오늘감지된시장이벤트 — 금리·달러·유가·투자심리·섹터 이동·외국인 수급

단순히 "많이 오른 종목"을 고르지 마세요. 아래를 따져서 고릅니다.
시장 영향력 / 파급력 / 의외성 / 스토리로 풀 수 있는지 / 초보도 이해 가능한지.
시장 이벤트가 개별 종목보다 큰 날은 주저 없이 시장 이야기로 갑니다.
그날 고른 주제를 topic_type 에 "stock" 또는 "macro" 로 표시하세요.

━━ 절대 원칙 ━━
- 제공된 JSON 에 있는 수치만 씁니다. 없는 숫자·기업명·뉴스를 지어내지 않습니다.
- 확인 안 된 루머를 사실처럼 쓰지 않습니다.
- 오른 종목을 무조건 "수혜주"라고 하지 않습니다. 사실과 해석을 구분하세요.
- 매수·매도를 권유하지 않습니다. "무조건 오른다", "지금 사야 한다", "대박주" 금지.
  대신 "~할 가능성", "~가 관건", "앞으로 확인해야 할 부분" 같은 표현을 씁니다.
- 아래 스키마의 설명 문구를 그대로 값으로 넣지 마세요. 실제 내용을 새로 씁니다.

━━ 문체 ━━
전문가가 친구에게 설명하는 느낌. 딱딱한 리포트도, 가벼운 유튜브 말투도 아닙니다.
- 문장을 짧게. 한 문단에 메시지 하나.
- 숫자에는 반드시 의미를 붙입니다. "매출 300억, 25% 증가"에서 끝내지 말고
  "시장이 더 중요하게 본 건 다음 분기 가이던스였습니다"까지.
- 다음 표현은 쓰지 마세요: "상승 마감했습니다", "관심이 집중되고 있습니다",
  "지켜봐야 합니다", "긍정적인 영향을 미칠 것으로 보입니다".
- 대신 독자가 생각하게 만드세요. "주가는 올랐습니다. 그런데 시장이 정말
  좋아한 건 주가가 아니었습니다." 같은 식으로.

━━ 분량 ━━
각 항목의 글자 수 하한은 요구사항입니다. 미달하면 카드에 빈 공간이 생깁니다.
할 말이 부족하면 데이터에서 근거 수치를 하나 더 끌어와 채우세요.
빈 문자열이나 "데이터 없음" 같은 응답은 쓰지 않습니다.

반드시 아래 JSON 만 출력합니다. 코드펜스, 설명, 서론 없이 JSON 객체 하나만.

{
  "topic_type": "stock 또는 macro 중 하나",

  "p1_headline": "24자 이내. 스크롤을 멈추게 하는 한 줄. 결론을 다 말하지 말 것. 예: 나스닥은 올랐는데, 진짜 중요한 건 따로 있었다",
  "p1_sub": "30~45자. 제목을 보충하며 긴장감을 이어가는 한 문장.",
  "p1_keydata": [{"label": "6자 이내 항목명", "value": "숫자 (12자 이내)"}],
  "p1_hook": "25~40자. 다음 장을 넘기게 만드는 마지막 한 줄.",

  "p2_headline": "18자 이내. 어젯밤 무슨 일이 있었나.",
  "p2_sub": "30~45자. 시장 전체 분위기를 한 문장으로.",
  "p2_keydata": [{"label": "지수·지표명", "value": "등락률 또는 수치"}],
  "p2_flow": ["원인 (20자 이내)", "그래서 벌어진 일 (20자 이내)", "결과 (20자 이내)"],
  "p2_content": "80~120자. 위 흐름을 하나로 이어 설명. 숫자 나열이 아니라 인과로.",

  "p3_headline": "18자 이내. 그래서 이게 왜 중요한가.",
  "p3_sub": "30~45자. 투자자에게 어떤 의미인지 압축.",
  "p3_chain": [
    {"step": "일어난 일", "text": "25자 이내 사실"},
    {"step": "시장의 해석", "text": "25자 이내"},
    {"step": "주가·자금", "text": "25자 이내 결과"}
  ],
  "p3_content": "90~130자. 어떤 산업이 유리하고 불리한지, 시장이 무엇을 기대하는지, 이미 주가에 얼마나 반영됐을지.",
  "p3_question": "30~45자. 독자가 생각해볼 질문 하나. 예: 좋은 뉴스인데 주가는 왜 안 올랐을까?",

  "p4_headline": "18자 이내. 그래서 어디를 봐야 하나.",
  "p4_sub": "30~45자.",
  "beneficiaries": [
    {"ticker": "티커. 반드시 제공된 데이터(경쟁사·밸류체인·상승상위·오늘의종목)에 있는 것만",
     "name": "회사를 한마디로 (12자 이내)",
     "reason": "이번 이슈와 연결되는 이유 35~50자",
     "watch": "앞으로 확인할 것 20~30자"}
  ],
  "p4_caution": "40~60자. 단, 주의할 점. 이미 주가에 반영됐을 가능성이나 사실과 해석의 구분.",

  "p5_headline": "18자 이내. 이제 무엇을 봐야 하나.",
  "p5_sub": "30~45자.",
  "watch_next": [
    {"when": "시점 (10자 이내). 데이터에 실적 발표일이 있으면 그걸 쓰고, 없으면 '이번 주' 같은 표현",
     "what": "확인할 내용 25~40자"}
  ],
  "takeaway": "40~60자. 한 줄 결론. 독자가 내일도 이 계정을 보고 싶게. 예: 오늘 핵심은 AI가 아니라, AI에 돈 쓰는 속도가 유지되느냐입니다",

  "kr_line": "55~80자. 이 이슈가 오늘 한국 증시에 미칠 영향. 외국인 순매수·원달러 데이터가 있으면 인용. 전망 어조.",
  "kakao_text": "카톡 알림용 요약. 150자 이내.",
  "instagram_caption": "인스타 캡션. 400자 이내. 핵심 먼저, 마지막 줄에 해시태그 6~8개."
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
    """API 가 실패해도 카드가 자연스럽게 보이도록 원본 수치로 문장을 만듭니다.

    '요약 생성 실패' 같은 문구가 카드에 찍히면 안 되므로, 데이터로 만들 수 있는
    최소한의 의미 있는 문장만 채웁니다.
    """
    f = data.get("focus", {})
    tk = f.get("ticker", "")
    pct = f.get("pct")
    name = f.get("name") or tk
    rvol = f.get("rvol")
    a = f.get("analyst") or {}
    g = f.get("growth") or {}
    events = data.get("market_events") or []
    indices = (data.get("market") or {}).get("indices") or []

    direction = "급등" if (pct or 0) >= 5 else "상승" if (pct or 0) > 0 else \
                "급락" if (pct or 0) <= -5 else "하락"

    keydata = []
    if pct is not None:
        keydata.append({"label": tk, "value": f"{pct:+.2f}%"})
    if rvol:
        keydata.append({"label": "거래량", "value": f"평소 {rvol:.1f}배"})

    idx_data = [
        {"label": i["label"], "value": f"{i['pct']:+.2f}%"}
        for i in indices[:3] if i.get("pct") is not None
    ]

    flow = [e["headline"] for e in events[:3]] or [f"{name} {direction}"]

    watch = []
    ern = f.get("earnings") or {}
    if ern.get("next_date"):
        watch.append({"when": ern["next_date"], "what": "다음 실적 발표"})
    if a.get("target_mean"):
        watch.append({"when": "이번 주", "what": f"월가 목표주가 ${a['target_mean']:,.0f} 대비 주가 흐름"})

    return {
        "topic_type": "stock",
        "p1_headline": f"{name} {direction}",
        "p1_sub": f"어젯밤 미국 시장에서 가장 크게 움직인 종목입니다",
        "p1_keydata": keydata,
        "p1_hook": "무슨 일이 있었는지 살펴봅니다",
        "p2_headline": "어젯밤 시장",
        "p2_sub": "주요 지수와 지표 흐름",
        "p2_keydata": idx_data,
        "p2_flow": flow,
        "p2_content": "",
        "p3_headline": "",
        "p3_sub": "",
        "p3_chain": [],
        "p3_content": "",
        "p3_question": "",
        "p4_headline": "",
        "p4_sub": "",
        "beneficiaries": [],
        "p4_caution": "",
        "p5_headline": "다음에 볼 것",
        "p5_sub": "",
        "watch_next": watch,
        "takeaway": "",
        "kr_line": "",
        "kakao_text": f"{name} {pct:+.1f}%" if pct is not None else name,
        "instagram_caption": "",
    }


_LIST_LIMITS = {
    "p1_keydata": 3, "p2_keydata": 3, "p2_flow": 3,
    "p3_chain": 3, "beneficiaries": 4, "watch_next": 4,
}

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
