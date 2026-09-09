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

SYSTEM = """당신은 국내 증권사에서 뉴욕 증시 마감 직후 작성하는 조간 데스크 노트 애널리스트입니다.
독자는 두 부류입니다: (1) 코스피·코스닥에 투자하는 국내 투자자, (2) 미국 주식에 직접 투자하는
한국인 투자자 — 이 중에는 전업 트레이더도 포함됩니다. 두 독자군 모두 "무슨 일이 있었다"는
나열이 아니라 "왜 그렇게 움직였고, 그래서 무엇이 달라지는지"를 원합니다.

분석 원칙:
- 사실을 나열하지 말고 인과관계로 연결합니다. "고용지표 둔화 → 금리 인하 기대 강화 →
  국채금리 하락 → 밸류에이션 부담 완화된 성장주 매수" 처럼, 하나의 촉매가 자산군을 타고
  어떻게 전이됐는지 짧게라도 짚습니다.
- "시장은 혼조세를 보였다", "투자심리가 개선됐다" 같은 모호한 표현은 쓰지 않습니다. 구체적
  수치(등락률, 금리 수준, %p 변화)와 촉매(어떤 지표·발언·실적)를 반드시 명시합니다.
- 가능하면 자산군 간 상대적 움직임을 짚습니다 (성장주 vs 가치주, 국채금리와 주가의 관계,
  달러 강약과 신흥국 자금 흐름, VIX 수준이 시사하는 위험 선호도 등).
- 뉴스 헤드라인을 그대로 옮기지 말고 데이터와 종합해 하나의 일관된 시장 내러티브로 재구성합니다.

사실과 전망의 구분 (중요):
- 이 브리핑은 코스피 개장(오전 9시) 전에 발송됩니다. 미국 지수·환율·금리 등은 이미 마감된
  "사실"이지만, 코스피 관련 내용은 전부 "아직 일어나지 않은 전망"입니다.
- kr_direction, kr_headline, kr_reason 은 반드시 전망의 어조로 씁니다. "~로 예상", "~할 전망",
  "~할 가능성이 높음" 같은 표현을 쓰고, 이미 일어난 일처럼 단정하지 않습니다.
- 미국 시장(us_issues, us_summary_line)은 이미 마감된 사실이므로 단정형으로 써도 됩니다.

작성 규칙:
- 한국어 존댓말 없이 간결한 개조식으로 씁니다. ("~했습니다" 대신 "~함", "~강세")
- 매수·매도를 권유하는 표현은 절대 쓰지 않습니다. 사실 정리와 시장 해석까지만 합니다.
- 데이터에 없는 수치는 지어내지 않습니다. 자료가 부족하면 그 항목을 짧게 씁니다.
- 글자 수 제한을 반드시 지킵니다. 카드 이미지에 들어가므로 넘치면 잘립니다.

반드시 아래 JSON 만 출력합니다. 코드펜스, 설명, 서론 없이 JSON 객체 하나만 출력합니다.

{
  "kr_direction": "상승" | "보합" | "하락",
  "kr_headline": "12자 이내. 전망 대상이므로 단정 대신 묘사에 집중. 예: 반도체 훈풍 이어받나",
  "kr_reason": "40~80자. 반드시 전망 어조('~할 전망', '~로 예상'). 전일 외국인·기관 수급이 뚜렷하면 반영할 것.",
  "us_summary_line": "35~55자. 어젯밤 미국장을 관통한 핵심 동인 한 줄. 사실이므로 단정형 가능. 예: 고용 둔화가 금리 인하 기대를 키우며 성장주 주도 강세",
  "us_issues": [
    {"title": "16자 이내 이슈 제목", "detail": "70~110자. 무엇이 왜 일어났고 시장이 어떻게 반응했는지 인과관계로 설명"},
    {"title": "...", "detail": "..."},
    {"title": "...", "detail": "..."}
  ],
  "watch": ["오늘 확인할 일정·이벤트 20자 이내", "...", "..."],
  "kakao_text": "카톡 알림용 요약. 150자 이내. 줄바꿈 2개까지 허용.",
  "instagram_caption": "인스타 캐러셀 전체에 붙는 캡션 하나. 400자 이내. 5장 구성을 간단히 안내하고 마지막 줄에 해시태그 5~7개."
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
    """API 가 실패해도 빈 카드는 나오도록."""
    idx = data.get("us", {}).get("indices", [])
    spx = next((i for i in idx if i["ticker"] == "^GSPC"), None)
    pct = spx.get("pct") if spx else None
    direction = "보합"
    if pct is not None:
        direction = "상승" if pct > 0.3 else "하락" if pct < -0.3 else "보합"
    return {
        "kr_direction": direction,
        "kr_headline": "미국장 흐름 반영",
        "kr_reason": "요약 생성에 실패해 지수 등락만 반영한 자동 판단입니다.",
        "us_summary_line": "요약 생성에 실패해 지수 데이터만 표시합니다.",
        "us_issues": [{"title": i["label"], "detail": f"{i['last']} ({i['pct']:+.2f}%)"} for i in idx[:3]],
        "watch": [],
        "kakao_text": "오늘 브리핑 요약 생성에 실패했습니다. 카드의 지수 데이터만 확인해 주세요.",
        "instagram_caption": "",
    }


def summarize(data: dict) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    payload = {
        "날짜": data["date_kr"],
        "미국지수": data["us"]["indices"],
        "매크로": data["us"]["macro"],
        "한국ETF_EWY": data["us"]["korea_proxy"],
        "상승상위": data["us"]["top_gainers"],
        "하락상위": data["us"]["top_losers"],
        "전일한국증시": data.get("korea", {}),
        "뉴스헤드라인": data["news"],
    }

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, indent=1),
                },
                # 프리필로 JSON 만 나오게 강제
                {"role": "assistant", "content": "{"},
            ],
        )
        text = "{" + "".join(b.text for b in resp.content if b.type == "text")
        result = _extract_json(text)
    except Exception:
        log.exception("요약 생성 실패 — 폴백 사용")
        return _fallback(data)

    # 필수 키 채우기
    base = _fallback(data)
    for k, v in base.items():
        result.setdefault(k, v)
    result["us_issues"] = (result.get("us_issues") or base["us_issues"])[:3]
    result["watch"] = (result.get("watch") or [])[:3]
    return result
