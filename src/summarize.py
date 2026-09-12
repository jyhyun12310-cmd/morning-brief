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
- 내부자매매 데이터가 있으면 언급합니다. 임원의 자사주 매수는 강한 긍정 신호,
  매도 우위는 주의 신호로 읽되 "매도는 세금·개인사정일 수도 있다"는 단서를 달 만큼
  과잉해석하지 않습니다.
- 재무건전성(부채비율·유동비율)이 있으면 금리 환경과 엮어 해석합니다. 부채비율이
  높은데 금리가 오르는 국면이면 리스크로, 유동비율이 튼튼하면 안정성 근거로.
- 실현변동성과 VIX 비교 데이터가 있으면 "이 종목이 시장보다 몇 배 흔들리는지"를
  리스크 평가에 반영합니다.
- 업종평균PER 이 있으면 종목 PER 과 직접 비교해 "업종 대비 몇 % 프리미엄/디스카운트"
  형태로 씁니다.
- 애널리스트 추천분포가 있으면 목표주가 평균만 말하지 말고 매수/보유/매도 의견이
  얼마나 쏠려 있는지도 언급합니다.
- 향후 전개는 조건부로 씁니다. "~하면 ~할 수 있음" 형태로 근거와 함께.
- 매수·매도를 권유하지 않습니다. 판단 재료를 제공하는 데서 멈춥니다.
- "추격 매수보다는 조정 시 진입" 같은 매매 전략도 권유에 해당하니 쓰지 않습니다.
  대신 "RSI 70대는 통상 단기 조정이 뒤따르는 경우가 많은 구간" 처럼 일반적인
  패턴을 설명하는 데서 멈추고, 판단은 독자 몫으로 남깁니다.
- points(급등락 원인)는 결과 지표가 아니라 사업적 원인만 씁니다. 거래량 증가나
  밸류에이션 자체는 '왜 올랐는지'의 결과이지 원인이 아니므로 절대 쓰지 않습니다.
  대신 실제 사업 동인을 씁니다: 신제품·수주잔고(backlog)·사업부별 매출 비중 변화·
  마진 개선·컨센서스 대비 서프라이즈 크기·경영진 가이던스 등.
- 밸류체인은 나열만 하지 말고 인과 메커니즘을 짚습니다. "이 종목의 무엇이 늘면
  저 종목의 무엇이 자극받는지" 구체적 경로를 한 문장에 담습니다.

톤:
- 한국어 개조식. 존댓말 없이 ("~했습니다" 대신 "~함", "~기록")
- 과장된 찌라시 표현 금지. 숫자와 사실로 후킹합니다.
- 글자 수 제한을 반드시 지킵니다. 카드에 들어가므로 넘치면 잘립니다.
- **분량 하한은 권장이 아니라 요구사항입니다.** 하한에 미달하면 카드에 빈 공간이
  생겨 완성도가 떨어집니다. 할 말이 부족하면 제공된 데이터에서 근거 수치를
  하나 더 끌어와 문장을 보강하세요.
- 빈 문자열이나 "데이터 없음" 같은 응답을 쓰지 않습니다. 특정 지표가 없으면 그
  종목의 다른 데이터(등락률, 거래량, 업종 흐름, 지수 대비 상대 성과, 52주 위치)로
  대체해 반드시 의미 있는 문장을 채웁니다.
- 한 항목당 하나의 메시지만 담되, 근거 수치는 함께 적어 내용을 촘촘하게 채웁니다.
- 아래 JSON 스키마의 설명 문구("~자 이내", "1문장" 같은 안내)는 형식 안내일 뿐입니다.
  그 문구 자체를 절대 값으로 넣지 않습니다. 예를 들어 "사건 요약 1문장"이라고
  써있으면 실제 사건을 요약한 문장을 새로 쓰는 것이지, "사건 요약 1문장"이라는
  글자를 그대로 넣는 게 아닙니다.
- summary3 는 카드 전체를 안 봐도 이 3줄만으로 이해되게 씁니다. 각 줄은
  서로 다른 각도(사건 → 숫자 → 결론)를 담당하며, 앞서 쓴 다른 필드의 핵심을
  재료로 삼되 문장은 새로 씁니다. 전문용어를 최소화하고, 고등학생이 한 번
  읽으면 바로 이해할 정도로 쉬운 말을 씁니다. (예: "선행 PER" 같은 용어를
  써야 한다면 "내년 이익 대비 주가가 싸다/비싸다" 식으로 풀어서 설명)

반드시 아래 JSON 만 출력합니다. 코드펜스, 설명, 서론 없이 JSON 객체 하나만.

{
  "headline_theme": "20~28자. 이 종목이 움직인 핵심 테마를 명확한 키워드로 담아 궁금증을 유발하는 문장. 등락률·종목명은 화면에 이미 크게 나오므로 안 넣어도 됨. 예: AI 서버 실적이 증명한 반전 / 단순 PC 회사가 아니었다",

  "company_desc": "45~65자. 이 회사가 정확히 무엇을 하는 곳인지 쉬운 말로. 제공된 영문 소개(사업요약)와 업종 정보를 근거로 삼되, 직역하지 말고 한국 독자가 바로 이해할 문장으로 새로 씁니다. 예: 클라우드 인프라와 데이터베이스를 기업에 공급하는 소프트웨어 회사",

  "points": [
    {"title": "8~14자. 사업적 원인(제품·수주잔고·마진·가이던스 등). 거래량·밸류에이션 금지", "detail": "수치 하나 (18자 이내)"},
    {"title": "위와 동일 형식", "detail": "..."},
    {"title": "위와 동일 형식", "detail": "..."}
  ],
  "points_summary": "40~60자. 위 3가지 이유를 한 문장으로 엮은 요약. 예: AI 서버 수주 폭증과 고마진 사업 비중 확대가 겹치며 가이던스 상향으로 이어짐",
  "macro_line": "시장 전체 흐름과 이 종목의 움직임이 뚜렷하게 대비될 때만 50~80자로 채웁니다. 예: 시장 전체가 하락한 날 이 종목만 급등, 또는 시장은 잠잠한데 이 종목만 반응. 특별한 대비가 없으면 반드시 빈 문자열(\"\")로 둡니다 — 관련 없는 지수 나열은 절대 금지.",

  "fundamental_note": "90~130자. 밸류에이션 수치 나열이 아니라 '그래서 비싼지 싼지'를 촌철살인으로 답합니다. 업종평균PER 대비 몇 % 차이인지, 그게 진짜 저평가인지 업종 특성상 원래 그런 수준인지까지. 예: 빅테크보다 낮지만 하드웨어 제조사 특성상 원래 낮게 거래되는 편이라 극단적 저평가로 보긴 어려움",
  "chart_note": "80~120자. RSI·이동평균 수치를 나열하지 말고 그 의미를 해석합니다. 예: RSI 70대는 통상 단기 조정이 뒤따르는 경우가 많은 구간이라 변동성 확대에 대비할 필요. 매매 전략 제시는 금지, 패턴 설명까지만.",
  "smart_money_note": "60~90자. 기관 보유율·공매도 비중을 근거로 스마트머니 포지셔닝을 해석. 데이터 없으면 빈 문자열.",

  "outlook_note": "90~130자. AI 종합 전망. 펀더멘털·기술적 신호·밸류체인·목표주가를 근거로 앞으로 전개 가능성을 조건부로 종합. '~하면 ~할 수 있음' 형태. 단정하지 않되 근거는 구체적으로.",
  "chain_note": "80~110자. 밸류체인 종목을 나열만 하지 말고 인과 메커니즘을 짚습니다. 예: AI 서버 출하량이 늘면 서버에 들어가는 네트워크 장비·메모리 수요가 함께 늘어나는 구조라 관련주도 동반 반응",
  "wallst_note": "80~110자. 목표주가 컨센서스 대비 현재가 위치를 해석. 현재가·목표가 차이가 좁으면 애널리스트 목표가 추가 상향 여지를, 차이가 크면 남은 상승여력이나 시장의 회의적 시각을 짚습니다. 추천분포 쏠림도 함께.",
  "risks": ["리스크 1 (34자 이내, 근거 포함)", "리스크 2", "리스크 3"],

  "signature_insight": "35~50자. 숫자 재탕이 아닌 통찰 한 문장. '그래서 이게 왜 중요한지'에 대한 소신 있는 해석. 매수·매도 권유는 아니되 뻔한 말은 지양. 예: 사람들이 Dell을 PC 회사로만 보는 사이, 사업의 무게중심은 이미 AI 인프라로 넘어갔다",

  "summary3": [
    "핵심 모멘텀 1문장 (42자 이내) - 이 종목을 움직인 근본 동력",
    "리스크·기술적 신호 1문장 (42자 이내) - 주의해서 볼 지표",
    "확인할 것 1문장 (42자 이내) - 앞으로 어떤 지표·이벤트를 지켜봐야 하는지. '보유/매수/매도' 같은 행동 지시가 아니라 '무엇을 확인하며 판단할지'만 제시"
  ],
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
    """API 가 실패해도 카드가 자연스럽게 보이도록 원본 수치로 문장을 만듭니다.

    '요약 생성 실패' 같은 문구가 카드에 그대로 찍히면 안 되므로,
    데이터로 만들 수 있는 최소한의 의미 있는 문장만 채웁니다.
    """
    f = data.get("focus", {})
    tk = f.get("ticker", "")
    pct = f.get("pct")
    name = f.get("name") or tk
    industry = f.get("industry", "")
    rvol = f.get("rvol")
    lv = f.get("levels") or {}
    v = f.get("valuation") or {}
    g = f.get("growth") or {}
    a = f.get("analyst") or {}

    direction = "급등" if (pct or 0) >= 5 else "상승" if (pct or 0) > 0 else \
                "급락" if (pct or 0) <= -5 else "하락"

    points = []
    if rvol:
        points.append({"title": "거래량 급증", "detail": f"평소 대비 {rvol:.1f}배"})
    if g.get("revenue") is not None:
        points.append({"title": "매출 성장", "detail": f"{g['revenue'] * 100:+.0f}%"})
    if v.get("forward_per"):
        points.append({"title": "밸류에이션", "detail": f"선행 PER {v['forward_per']:.0f}배"})

    summary3 = []
    if pct is not None:
        summary3.append(f"{name} 주가가 하루 만에 {abs(pct):.1f}% {direction}함")
    if rvol:
        summary3.append(f"거래량이 평소의 {rvol:.1f}배로 늘며 관심이 집중됨")
    if a.get("target_mean") and a.get("upside") is not None:
        summary3.append(f"월가 목표주가 평균은 현재가 대비 {a['upside']:+.0f}% 수준")

    return {
        "headline_theme": "",
        "company_desc": industry or f"{tk} 관련 기업",
        "points": points,
        "points_summary": f"{name} {direction}의 배경을 데이터로 정리했습니다",
        "macro_line": "",
        "fundamental_note": " · ".join(p["detail"] for p in points) if points else "",
        "chart_note": (
            f"RSI {lv['rsi']:.0f} 수준" if lv.get("rsi") is not None else ""
        ),
        "smart_money_note": "",
        "outlook_note": "",
        "chain_note": "",
        "wallst_note": "",
        "risks": [],
        "signature_insight": "",
        "summary3": summary3,
        "cta_question": "여러분은 이 종목을 어떻게 보시나요?",
        "kr_line": "",
        "kakao_text": f"{name} {pct:+.1f}%" if pct is not None else name,
        "instagram_caption": "",
    }


_LIST_LIMITS = {"points": 3, "risks": 3, "summary3": 3}

# LLM 에게 보낼 때 빼는 필드. 60일 종가 배열 같은 건 모델이 읽어도 의미를 못 뽑는데
# 토큰만 1만 자 넘게 잡아먹어, 정작 출력할 여력을 줄입니다.
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
