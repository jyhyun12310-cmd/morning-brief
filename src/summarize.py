"""수집한 원자료를 Claude 에게 넘겨 고정 스키마 JSON 으로 받아옵니다.

스키마를 고정해야 매일 같은 레이아웃으로 렌더링됩니다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from anthropic import Anthropic

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

# 요구하는 출력 분량이 한국어 1,800자 남짓이고 한국어는 글자당 1.5~2토큰이라
# 3,000토큰으로는 JSON 이 중간에서 잘려 파싱에 실패합니다. 넉넉히 잡습니다.
MAX_TOKENS = 8000

SYSTEM = (Path(__file__).parent / "photo_editorial_prompt.txt").read_text(encoding="utf-8")


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
    """AI 가 실패해도 카드가 충분히 채워지도록, 데이터로 만들 수 있는 문장을 최대한 만듭니다.

    실제로 AI 실패 시 폴백이 얇아서 위험 칸이 비고 마지막 장이 텅 빈 채
    발송된 적이 있습니다. 그래서 각 장마다 수치에서 끌어낼 수 있는 설명을
    빠짐없이 채우고, 특히 위험 요인은 어떤 경우에도 비우지 않습니다.
    """
    f = data.get("focus", {})
    tk = f.get("ticker", "")
    pct = f.get("pct")
    name = f.get("name") or tk
    rvol = f.get("rvol")
    v = f.get("valuation") or {}
    g = f.get("growth") or {}
    e = f.get("earnings") or {}
    a = f.get("analyst") or {}
    lv = f.get("levels") or {}
    sm = f.get("smart_money") or {}
    w52 = f.get("w52") or {}
    industry = f.get("industry", "")
    try:
        from render import _industry_kr
        ind_kr = _industry_kr(industry)
    except Exception:
        ind_kr = industry
    is_reit = "reit" in industry.lower()

    up = (pct or 0) >= 0
    mv = "올랐" if up else "내렸"
    pct_txt = f"{abs(pct):.1f}%" if pct is not None else ""

    # ── 표지
    surprise = e.get("surprise")
    rev = g.get("revenue")

    # 원인을 자료로 확정할 수 없으므로 "왜 빠졌을까"처럼 인과를 묻는 제목은
    # 쓰지 않습니다. 답할 수 있는 질문으로 범위를 좁혀야 마지막 장에서 실제로
    # 답을 낼 수 있습니다.
    if surprise is not None and surprise > 0 and not up:
        title = "실적은 넘겼는데 주가는 내렸습니다"
    elif surprise is not None and surprise < 0 and up:
        title = "실적은 밑돌았는데 주가는 올랐습니다"
    elif rev is not None and rev < 0 and up:
        title = "매출은 줄었는데 주가는 올랐습니다"
    elif rvol and rvol >= 2:
        title = f"거래량이 평소의 {rvol:.1f}배로 뛰었습니다"
    else:
        title = f"{tk}, 이번 분기에서 볼 것은"

    sub = f"하루 만에 {pct_txt} {mv}습니다"
    if rvol and rvol >= 1.5:
        sub += f". 거래량은 평소의 {rvol:.1f}배"

    # ── 2장: 무엇이 움직였나
    p2_secs = []
    if e.get("date") and e.get("eps_act") is not None:
        p2_secs.append({"h": "최근 발표",
                        "t": f"{e['date']} 분기 실적. 주당순이익 ${e['eps_act']}."})
    if e.get("eps_est") is not None and e.get("eps_act") is not None:
        diff = "웃돌았" if e.get("beat") else "밑돌았"
        p2_secs.append({"h": "예상과의 차이",
                        "t": f"예상 ${e['eps_est']} 대비 {abs(surprise or 0):.0f}% {diff}네요. 같은 기준인지는 원자료 확인이 필요합니다."})
    p2_secs.append({"h": "확인된 것과 해석",
                    "t": "다만 오늘 움직임의 직접 원인은 자료로 확인되지 않습니다."})

    # 질문("무엇이 움직였나")에 실제로 답하는 문장. 등락률 반복은 답이 아닙니다.
    if surprise is not None and e.get("date"):
        p2_a = f"{e['date']} 실적이 예상과 달랐습니다"
    elif rvol and rvol >= 1.8:
        p2_a = f"거래량이 평소의 {rvol:.1f}배. 주체까진 알 수 없습니다"
    else:
        p2_a = "딱 하나로 꼽을 원인은 자료에서 확인되지 않습니다"

    # ── 3장: 어떻게 돈을 버나
    p3_flow = []
    if is_reit:
        p3_flow = [{"step": "제품·서비스", "text": "건물 임대"},
                   {"step": "고객", "text": "입주 기업"},
                   {"step": "돈이 되는 변수", "text": "공실률·임대료"}]
        p3_a = "부동산을 임대하고 운영하는 사업입니다"
        p3_secs = [{"h": "회계가 만드는 착시",
                    "t": "감가상각은 원가를 기간에 나누는 회계 처리예요. 건물 시세가 떨어졌다는 뜻이 아닙니다."},
                   {"h": "그래서 함께 보는 것",
                    "t": "그래서 감가상각 등을 조정한 FFO를 함께 봅니다. 임대료 입금액과는 다른 개념이에요."}]
    else:
        p3_a = f"{ind_kr} 쪽에서 수익을 내는 회사입니다" if ind_kr else f"{name}가 돈을 버는 구조를 봅니다"
        p3_secs = []
        if ind_kr:
            p3_secs.append({"h": "무슨 일을 하나",
                            "t": f"{ind_kr} 업종. 수요와 가격이 바뀌면 실적도 따라 움직입니다."})
        if v.get("margin") is not None:
            mg = v["margin"] * 100
            if mg < 0:
                read = "아직 버는 것보다 쓰는 게 많습니다"
            elif mg < 10:
                read = "얇은 편이라 매출이 흔들리면 이익은 크게 움직여요"
            elif mg < 25:
                read = "무난한 수준. 매출이 늘면 이익도 따라옵니다"
            else:
                read = "두툼한 편. 가격을 지킬 힘이 있다는 신호죠"
            p3_secs.append({"h": "남는 돈",
                            "t": f"매출 100원 중 {mg:.1f}원이 남습니다. {read}."})
        if g.get("revenue") is not None and v.get("margin") is not None:
            rv2 = g["revenue"] * 100
            p3_secs.append({"h": "지금 상태",
                            "t": f"매출은 1년 전보다 {abs(rv2):.0f}% {'늘었' if rv2 > 0 else '줄었'}고, "
                                 f"마진은 {v['margin']*100:.1f}%. 둘을 같이 봐야 합니다."})
        if not p3_secs:
            p3_secs.append({"h": "확인된 것",
                            "t": "세부 자료가 아직 부족합니다. 다음 공시에서 확인할 부분이에요."})

    # ── 4장: 실적
    p4_secs = []
    if rev is not None:
        verb = "늘었" if rev > 0 else "줄었"
        p4_secs.append({"h": "매출 변화",
                        "t": f"1년 전 같은 분기보다 {abs(rev*100):.0f}% {verb}습니다."})
    hist = e.get("history") or []
    if len(hist) >= 3:
        beats = sum(1 for h in hist if h)
        p4_secs.append({"h": "과거 기록",
                        "t": f"최근 {len(hist)}분기 중 {beats}번 예상을 넘었어요. 다음 분기 확률은 아닙니다."})
    if e.get("next_date"):
        p4_secs.append({"h": "다음 확인",
                        "t": f"다음 실적 {e['next_date']} 예정. 확정 여부는 회사 공지로 확인하세요."})

    if rev is not None and surprise is not None:
        if surprise > 0 and rev < 0:
            p4_a = "예상은 넘겼지만 매출은 줄었습니다"
        elif surprise > 0:
            p4_a = "예상도 넘겼고 매출도 늘었습니다"
        else:
            p4_a = "이번엔 예상에 못 미쳤습니다"
    else:
        p4_a = "확인되는 실적 숫자만 모아봤습니다"

    # ── 5장: 주가 여유
    p5_secs = []
    if w52.get("pos") is not None:
        p5_secs.append({"h": "1년 가격 범위",
                        "t": f"저 ${w52.get('low', 0):.0f} ~ 고 ${w52.get('high', 0):.0f} 사이 {w52['pos']:.0f}% 지점. 위치가 싸다는 뜻은 아닙니다."})
    if a.get("target_mean") and a.get("count"):
        p5_secs.append({"h": "애널리스트 목표가",
                        "t": f"{a['count']}명 평균 ${a['target_mean']:,.1f}. 전망을 모은 참고치일 뿐이에요."})
    if is_reit:
        p5_secs.append({"h": "평가 기준의 한계",
                        "t": "PER만으론 왜곡이 생깁니다. 주가/주당FFO와 배당수익률을 함께 보세요."})
    elif v.get("forward_per"):
        p5_secs.append({"h": "평가의 한계",
                        "t": f"선행 PER {v['forward_per']:.1f}배. 어떤 이익 추정을 썼는지에 따라 달라집니다."})

    # ── 6장: 틀릴 수 있는 이유 (위험 칸은 절대 비우지 않습니다)
    bull, bear = [], []
    if e.get("beat"):
        bull.append({"fact": "직전 분기 예상 상회", "check": "다음 분기 EPS 추정치 변화"})
    if rev is not None and rev > 0.05:
        bull.append({"fact": f"매출 {rev*100:+.0f}% 성장", "check": "성장률 유지 여부"})

    if rev is not None and rev < 0:
        bear.append({"fact": f"매출 {rev*100:+.0f}% 감소", "check": "다음 분기 매출 반등 여부"})
    if rvol and rvol >= 1.8:
        bear.append({"fact": f"거래량 {rvol:.1f}배로 급증", "check": "며칠간 거래량이 이어지는지"})
    if sm.get("short_pct") is not None and sm["short_pct"] >= 0.05:
        # 기준일·분모를 밝히지 않은 채 위험 등급으로 바꾸지 않습니다.
        bear.append({"fact": f"공매도 잔고 비중 {sm['short_pct']*100:.1f}% (집계 기준일 확인 필요)",
                     "check": "다음 집계일의 잔고 증감"})
    if is_reit:
        bear.append({"fact": "금리에 민감한 리츠 구조", "check": "미 국채 10년물 금리 방향"})
    if not bear:
        # 어떤 데이터도 없을 때의 최후 보루. 빈 칸으로 내보내지 않습니다.
        bear.append({"fact": "단일 분기 데이터에 기댄 해석", "check": "다음 분기 실적으로 재확인"})
    if not bull:
        bull.append({"fact": "추가 확인이 필요한 상태", "check": "다음 실적 발표 내용"})

    # ── 7장: 기억할 것
    facts = []
    if pct is not None:
        facts.append(f"주가 {pct:+.1f}%, 거래량 {rvol:.1f}배" if rvol else f"주가 {pct:+.1f}%")
    if surprise is not None:
        facts.append(f"EPS 예상 대비 {surprise:+.0f}%")
    if rev is not None:
        facts.append(f"매출 전년 대비 {rev*100:+.0f}%")

    checks = []
    if e.get("next_date"):
        checks.append(f"{e['next_date']} 다음 실적 발표 (예정)")
    if is_reit:
        checks.append("공실률과 임대료 갱신율")
        checks.append("미 국채 10년물 금리")
    else:
        if rev is not None:
            checks.append("다음 분기 매출이 반등하는지" if rev < 0 else "매출 성장률이 둔화되는지")
        if a.get("target_mean"):
            checks.append("애널리스트 목표가 조정 방향")

    # 표지에서 던진 질문에 마지막 장이 실제로 답하게 합니다.
    if surprise is not None and surprise > 0 and not up:
        conclusion = ("예상을 넘긴 건 맞지만, 주가가 내린 직접 원인은 지금 자료로 "
                      "확인되지 않습니다. 실적의 질과 다음 전망부터 확인하는 게 순서예요")
    elif rev is not None and rev < 0:
        conclusion = ("한 분기 예상 상회보다, 매출이 줄어든 흐름이 이어지는지가 "
                      "판단의 기준입니다")
    elif rev is not None and rev > 0 and surprise is not None and surprise > 0:
        conclusion = ("예상도 넘기고 매출도 늘었습니다. 다만 이 속도가 유지되는지는 "
                      "다음 분기에 갈립니다")
    else:
        conclusion = ("지금 자료로는 방향을 단정하기 어렵습니다. 아래 지표부터 "
                      "확인하는 게 순서예요")

    return {
        "cover_title": title, "cover_sub": sub, "conclusion": conclusion,
        "cover_qs": ["무엇이 주가를 움직였을까", "이 회사는 어떻게 돈을 벌까", "기대가 틀릴 수 있는 이유는"],
        "p2_q": "무엇이 주가를 움직였을까", "p2_a": p2_a, "p2_secs": p2_secs,
        "p3_q": "이 회사는 어떻게 돈을 벌까", "p3_a": p3_a, "p3_flow": p3_flow, "p3_secs": p3_secs,
        "p4_q": "실적은 이어질 수 있을까", "p4_a": p4_a, "p4_secs": p4_secs,
        "p5_q": "주가에도 여유가 있을까", "p5_a": "지금 가격에 담긴 기대를 짚어봅니다", "p5_secs": p5_secs,
        "p6_q": "어떤 조건이면 해석이 달라질까", "p6_a": "조건과 확인 지표를 함께 봅니다",
        "p6_bull": bull, "p6_bear": bear,
        "p7_oneline": p3_a,
        "p7_facts": facts,
        "p7_keep": "다음 분기에도 실적이 예상을 넘어설 때",
        "p7_review": "매출 감소가 이어지거나 회사 전망이 낮아질 때",
        "p7_checks": checks,
        "kr_line": "",
        "kakao_text": f"{name} {pct:+.1f}%" if pct is not None else name,
        "instagram_caption": "",
    }


_LIST_LIMITS = {
    "cover_qs": 3, "p2_secs": 3, "p3_flow": 3, "p3_secs": 2, "p4_secs": 3,
    "p5_secs": 3, "p6_bull": 2, "p6_bear": 2, "p7_facts": 3, "p7_checks": 3,
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

    # setdefault 는 키가 있으면 값이 빈 문자열이어도 그대로 둡니다.
    # AI 가 필드를 빈 값으로 돌려주면 카드가 비어버리므로, 실제로 내용이
    # 있는지까지 보고 채웁니다.
    filled, empty = 0, []
    for k, v in base.items():
        cur = result.get(k)
        if cur is None or (isinstance(cur, str) and not cur.strip()) or \
           (isinstance(cur, list) and not cur):
            if v:
                result[k] = v
            empty.append(k)
        else:
            filled += 1

    for key, limit in _LIST_LIMITS.items():
        result[key] = (result.get(key) or [])[:limit]

    # 몇 개나 AI 가 실제로 채웠는지 남깁니다. 이 숫자가 낮으면 프롬프트나
    # 모델 응답에 문제가 있다는 뜻이라, 로그만 봐도 바로 알 수 있습니다.
    total = len(base)
    log.info("요약 필드 %d/%d 채움", filled, total)
    if filled < total * 0.5:
        log.warning("AI 응답이 절반 이상 비었습니다. 비어 있던 필드: %s",
                    ", ".join(empty[:12]))

    return result
