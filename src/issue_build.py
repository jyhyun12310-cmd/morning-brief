"""이슈 카드뉴스 1단계: 수집 → 이슈 선정 → 요약 → 카드 5장·상세페이지 생성.

종목 브리핑(build.py)과 같은 계정에 올라가지만 완전히 별개의 게시물입니다.
"어제 미국장에서 제일 시끄러웠던 일 하나"를 골라 가볍게 풉니다.

발송은 하지 않습니다. out/state.json 을 남기면 기존 publish.py 가 그대로
읽어서 인스타·카톡으로 보냅니다 (형식이 같습니다).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic

import collect
import config as cfg
import issue_render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("issue")

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
MAX_TOKENS = 6000

# 수혜·피해주 후보로 AI 에게 보여줄 종목 수. 너무 많으면 엉뚱한 종목을 고릅니다.
MOVER_SHOW = 12

# 이슈 시리즈 전용 해시태그. 종목 시리즈와 겹치되 이슈 색을 더합니다.
ISSUE_TAGS = [
    "#미국주식", "#미국증시", "#미장", "#해외주식",
    "#경제뉴스", "#증시이슈", "#주식공부", "#서학개미",
    "#투자공부", "#오늘의증시",
]

CAPTION_FOOTER = """어젯밤 미국장에서 제일 시끄러웠던 일 하나.
매일 아침, 5장으로 가볍게 정리합니다.

내일도 받아보려면 @{handle} 팔로우
친구한테 설명할 일 있으면 저장해두세요."""

CAPTION_DISCLAIMER = "본 게시물은 공개된 시장 데이터를 정리한 투자 참고용 자료이며, 특정 종목의 매수·매도를 권유하지 않습니다."


# ══ 프롬프트 ════════════════════════════════════════════

SYSTEM = """당신은 미국 증시를 친구에게 설명해주는 사람입니다.
어제 미국장에서 가장 화제가 된 이슈 하나를 골라 카드뉴스 5장으로 정리합니다.

읽는 사람은 주식을 아주 잘 알지는 않습니다. 대신 궁금해합니다.
"그래서 이게 나랑 무슨 상관인데?"에 답해주는 것이 목표입니다.

━━ 이슈 고르기 ━━
제공된 데이터에서 딱 하나만 고릅니다. 고르는 순서는 이렇습니다.
1. 감지된시장이벤트 배열에 뭔가 있으면 그 중 파급력이 큰 것
2. 없으면 뉴스헤드라인에서 여러 번 등장하거나 시장 전체에 영향을 주는 주제
3. 그것도 없으면 지수·섹터 움직임 중 가장 뚜렷한 것
종목 하나의 개별 실적은 고르지 마세요. 그건 다른 시리즈에서 다룹니다.

━━ 말투 (이 시리즈의 핵심) ━━
딱딱한 리포트 말투를 버립니다. 친구한테 카톡으로 설명하듯 씁니다.

- 구어체를 씁니다. "~다", "~더라", "~인 셈", "~했음", 명사로 끝내기를 섞으세요.
- 같은 어미가 연달아 나오면 안 됩니다. 특히 "~습니다"를 반복하지 마세요.
- 비유를 하나쯤 넣으세요. 어려운 개념일수록 일상의 것에 빗댑니다.
  예: "금리는 시장의 중력이다. 무거워지면 높이 날던 것부터 떨어진다"
- 가벼운 드립은 환영입니다. 다만 한 장에 하나면 충분합니다. 억지로 웃기지 마세요.
- 금지: "주목받고 있습니다", "기대감이 확대", "~할 것으로 전망됩니다",
  "관심이 집중되고 있습니다" 같은 기사 상투어 전부.
- 금지: 이모지. (카드 이미지에서 깨집니다. 캡션에도 넣지 마세요.)

━━ 절대 원칙 ━━
- 제공된 JSON 에 있는 수치만 씁니다. 없는 숫자·기업명·뉴스를 지어내지 않습니다.
- 등락률을 직접 쓰지 마세요. winners/losers 는 티커와 이유만 씁니다. 숫자는 코드가 붙입니다.
- 사실과 해석을 섞지 마세요. 해석은 "~로 읽힌다", "~라는 뜻" 같은 어조로.
- 매수·매도를 권유하지 않습니다. "무조건", "확정", "지금 안 사면 늦는다", "폭등" 전부 금지.
- 공포를 팔지 않습니다. 재미는 표현에서 내고, 사실은 담백하게.

━━ 길이 (매우 중요) ━━
모바일 카드입니다. 한 줄에 약 20자가 들어갑니다.
각 항목의 글자 수 제한을 반드시 지키세요. 넘치면 카드 아래가 잘려나갑니다.
길어지면 단어를 빼지 말고 문장을 통째로 짧게 다시 쓰세요.

반드시 아래 JSON 만 출력합니다. 코드펜스·설명·서론 없이 JSON 객체 하나만.

{
  "issue_tag": "표지 스티커에 들어갈 이슈 이름. 4~9자. 예: 금리가 또 / AI 거품론 / 연준의 고민",
  "hook1": "표지 첫 줄. 8~14자. 상황을 던집니다. 예: 나스닥이 하루 만에",
  "hook2": "표지 둘째 줄. 8~15자. 형광펜이 쳐지는 자리. 예: 2% 넘게 빠진 이유",
  "cover_sub": "표지 보조 한 줄. 28자 이내. 예: 원인은 실적이 아니라 금리였다",

  "p2_headline": "2장 제목. 11자 이내. 예: 무슨 일이 있었냐면",
  "facts": [
    {"num": "숫자 하나. 7자 이내. 등락률이면 부호를 붙입니다. 예: +2.4% / 4.35% / 68",
     "label": "그 숫자가 뭔지. 9자 이내. 예: 미 10년물 금리",
     "text": "한 줄 설명. 22자 이내. 예: 올해 들어 가장 높은 수준"}
  ],
  "p2_note": "2장 맨 아래 한 줄 요약. 26자 이내. 셋을 꿰는 한 문장.",

  "p3_headline": "3장 제목. 11자 이내. 예: 그래서 왜 중요하냐면",
  "why_text": "왜 중요한지. 두세 문장, 전체 70자 이내. 비유를 여기에 넣으면 좋습니다.",
  "chain": [
    {"step": "원인에서 결과까지 한 단계. 16자 이내. 예: 금리가 오른다"}
  ],
  "punch": "마무리 드립 한 줄. 30자 이내. 과장 없이, 피식할 정도로.",

  "p4_headline": "4장 제목. 11자 이내. 예: 누가 웃고 누가 울었나",
  "winners": [
    {"ticker": "제공된 후보목록에 실제로 있는 티커 그대로",
     "why": "오른 이유 한 조각. 13자 이내. 예: 금리 수혜 은행주"}
  ],
  "losers": [
    {"ticker": "제공된 후보목록에 실제로 있는 티커 그대로", "why": "13자 이내"}
  ],
  "kr_line": "한국 투자자에게 무슨 의미인지 한 줄. 28자 이내. 환율·외국인 수급 데이터가 있으면 씁니다.",

  "p5_headline": "5장 제목. 11자 이내. 예: 오늘 기억할 건 세 줄",
  "wrap": [
    {"text": "핵심 한 줄. 20자 이내"}
  ],
  "tomorrow": "내일 볼 일정이나 지표 한 줄. 24자 이내. 근거가 없으면 빈 문자열.",

  "kakao_text": "카톡 알림용 요약. 140자 이내.",
  "instagram_caption": "인스타 캡션 본문만. 150~250자. 해시태그·팔로우 유도는 코드가 붙이므로 넣지 마세요. 무슨 일이 있었고 왜 중요한지 구어체로."
}

facts 는 3개, chain 은 3~4개, winners·losers 는 각각 3개, wrap 은 3개를 채웁니다."""


# ══ 수집 ════════════════════════════════════════════════

def collect_issue() -> dict:
    """이슈 카드에 필요한 것만 모읍니다. 종목 심층 데이터는 받지 않습니다."""
    now = dt.datetime.now(cfg.KST)

    news = collect.fetch_news()
    market = collect.fetch_market()
    sectors = collect.fetch_sector_rotation()
    fg = collect.fetch_fear_greed()
    korea = collect.fetch_korea()
    events = collect.detect_market_events(market, fg, sectors, korea)
    log.info("감지된 시장 이벤트 %d개: %s", len(events), [e["kind"] for e in events])

    # 수혜·피해주 후보. 종목 브리핑과 같은 필터를 써서 잡주를 걸러냅니다.
    cands = collect.screen_universe()
    pool = {
        t: c for t, c in cands.items()
        if collect._passes_filter(c) and c.get("pct") is not None
    }
    log.info("수혜·피해주 후보 %d개", len(pool))

    return {
        "generated_at": now.isoformat(),
        "date_kr": now.strftime("%Y.%m.%d"),
        "date_slug": now.strftime("%Y-%m-%d"),
        "weekday_kr": "월화수목금토일"[now.weekday()],
        "market": market,
        "sector_rotation": sectors,
        "fear_greed": fg,
        "market_events": events,
        "korea": korea,
        "news": news,
        "mover_pool": pool,
    }


# ══ 요약 ════════════════════════════════════════════════

_DROP = ("series", "series_60")


def _slim(rows):
    if not rows:
        return rows
    if isinstance(rows, dict):
        return {k: v for k, v in rows.items() if k not in _DROP}
    return [{k: v for k, v in r.items() if k not in _DROP} for r in rows]


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(text[start : end + 1])


def _fallback(data: dict) -> dict:
    """API 가 실패해도 카드가 빈 채로 나가지 않도록 수집 데이터로 채웁니다."""
    events = data.get("market_events") or []
    gauges = {g["ticker"]: g for g in data.get("market", {}).get("gauges", [])}
    indices = {i["ticker"]: i for i in data.get("market", {}).get("indices", [])}
    sectors = data.get("sector_rotation") or []
    ev = events[0] if events else None

    facts = []
    for tk, row in list(indices.items())[:1] + list(gauges.items())[:2]:
        if row.get("pct") is not None:
            facts.append({
                "num": f"{row['pct']:+.2f}%",
                "label": row.get("label", tk),
                "text": f"종가 {row.get('last')}",
            })

    tag = (ev or {}).get("kind") or "미국장 정리"
    return {
        "issue_tag": tag,
        "hook1": "어젯밤 미국장",
        "hook2": (ev or {}).get("headline", "무슨 일이 있었나")[:15],
        "cover_sub": (ev or {}).get("context", "")[:28],
        "p2_headline": "무슨 일이 있었냐면",
        "facts": facts[:3],
        "p2_note": "",
        "p3_headline": "왜 중요하냐면",
        "why_text": (ev or {}).get("context", ""),
        "chain": [{"step": s["label"]} for s in sectors[:3]],
        "punch": "",
        "p4_headline": "누가 웃고 누가 울었나",
        "winners": [], "losers": [],
        "kr_line": "",
        "p5_headline": "한 줄로 정리하면",
        "wrap": [{"text": (ev or {}).get("headline", "")[:20]}] if ev else [],
        "tomorrow": "",
        "kakao_text": (ev or {}).get("headline", "미국장 이슈 정리"),
        "instagram_caption": "",
    }


def summarize_issue(data: dict) -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    pool = data.get("mover_pool") or {}
    ranked = sorted(pool.values(), key=lambda r: r["pct"], reverse=True)
    show = [
        {"티커": r["ticker"], "종목명": r["name"], "등락률": r["pct"]}
        for r in ranked[:MOVER_SHOW] + ranked[-MOVER_SHOW:]
    ]

    payload = {
        "날짜": data["date_kr"],
        "요일": data["weekday_kr"],
        "감지된시장이벤트": data.get("market_events"),
        "미국지수": _slim(data.get("market", {}).get("indices")),
        "시장지표_VIX금리달러유가": _slim(data.get("market", {}).get("gauges")),
        "섹터로테이션": _slim(data.get("sector_rotation")),
        "CNN공포탐욕지수": data.get("fear_greed", {}),
        "한국투자자참고": _slim(data.get("market", {}).get("kr_context")),
        "전일한국증시": data.get("korea", {}),
        "수혜피해주_후보목록": show,
        "뉴스헤드라인": (data.get("news") or [])[:25],
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
            log.error("응답이 max_tokens(%d)에 걸려 잘렸습니다", MAX_TOKENS)
        result = _extract_json(text)
    except Exception as e:
        log.exception("이슈 요약 생성 실패 — 폴백 사용")
        try:
            Path(cfg.OUT_DIR).mkdir(exist_ok=True)
            Path(cfg.OUT_DIR, "issue_error.txt").write_text(
                f"{type(e).__name__}: {e}", encoding="utf-8"
            )
        except Exception:
            pass
        return _fallback(data)

    base = _fallback(data)
    for k, v in base.items():
        result.setdefault(k, v)
    return result


# ══ 캡션·카톡 ═══════════════════════════════════════════

def _build_caption(summary: dict) -> str:
    tag = (summary.get("issue_tag") or "").strip()
    hook = " ".join(x for x in [summary.get("hook1"), summary.get("hook2")] if x).strip()

    head = f"[{tag}] {hook}".strip() if tag else hook
    body = (summary.get("instagram_caption") or "").strip()
    if not body:
        body = summary.get("why_text") or summary.get("cover_sub") or ""

    footer = CAPTION_FOOTER.format(handle=cfg.INSTAGRAM_HANDLE)
    tag_line = " ".join(ISSUE_TAGS)

    parts = [head, "", body, "", footer, "", CAPTION_DISCLAIMER, "", tag_line]
    return "\n".join(parts)[:2000]


def _build_kakao_cards(data: dict, summary: dict, ctx: dict,
                       image_urls: list[str], link_url: str) -> list[dict]:
    def _movers_line(rows):
        return " / ".join(f"{m['ticker']} {m['fmt_pct']}" for m in rows[:3])

    facts_line = " · ".join(
        f"{f['label']} {f['num']}" for f in (ctx["s"].get("facts") or [])[:3]
    )
    chain_line = " → ".join(c.get("step", "") for c in (ctx["s"].get("chain") or [])[:4])
    wrap_line = " / ".join(w.get("text", "") for w in (ctx["s"].get("wrap") or [])[:3])

    cards = [
        {"title": f"{data['date_kr']} · {summary.get('issue_tag', '미국장 이슈')}",
         "description": summary.get("cover_sub") or summary.get("kakao_text", "")},
        {"title": summary.get("p2_headline") or "무슨 일이",
         "description": facts_line or summary.get("p2_note", "")},
        {"title": summary.get("p3_headline") or "왜 중요한가",
         "description": summary.get("why_text") or chain_line},
        {"title": summary.get("p4_headline") or "누가 웃고 누가 울었나",
         "description": f"웃은 쪽 {_movers_line(ctx['winners'])} · 운 쪽 {_movers_line(ctx['losers'])}"},
        {"title": summary.get("p5_headline") or "한 줄 정리",
         "description": wrap_line or summary.get("kakao_text", "")},
    ]

    for card in cards:
        if not (card.get("description") or "").strip():
            card["description"] = "자세한 내용은 카드에서 확인하세요."

    for card, url in zip(cards, image_urls):
        card["image_url"] = url
        card["link_url"] = link_url
    return cards


# ══ 실행 ════════════════════════════════════════════════

def is_market_holiday(now: dt.datetime) -> bool:
    """한국 증시 휴장일이면 True. 판단이 불확실하면 False (그냥 실행)."""
    try:
        from pykrx import stock

        today = now.strftime("%Y%m%d")
        return stock.get_nearest_business_day_in_a_week(date=today, prev=True) != today
    except Exception:
        log.warning("휴장일 확인 실패 — 그대로 진행합니다")
        return False


def main() -> int:
    now = dt.datetime.now(cfg.KST)

    if "--force" not in sys.argv and is_market_holiday(now):
        log.info("오늘은 휴장일입니다. 이슈 카드뉴스를 건너뜁니다.")
        Path(cfg.OUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(cfg.OUT_DIR, "skip").write_text("holiday")
        return 0

    log.info("데이터 수집 중")
    data = collect_issue()

    log.info("이슈 선정·요약 중")
    summary = summarize_issue(data)
    log.info("오늘의 이슈: %s", summary.get("issue_tag"))

    # 종목 브리핑 파일명(YYYY-MM-DD-티커)과 겹치지 않도록 -issue 를 붙입니다
    slug = f"{now.strftime('%Y-%m-%d')}-issue"

    log.info("카드 %d장 렌더링 중", issue_render.CARD_COUNT)
    card_paths = issue_render.render_cards(data, summary, f"{cfg.DOCS_DIR}/cards", slug)
    issue_render.render_page(data, summary, slug)

    ctx = issue_render.build_context(data, summary)
    image_urls = [f"{cfg.PAGES_BASE}/cards/{slug}-{n}.jpg" for n in range(1, len(card_paths) + 1)]
    link_url = f"{cfg.PAGES_BASE}/{slug}.html"

    state = {
        "slug": slug,
        "date_kr": data["date_kr"],
        "weekday_kr": data["weekday_kr"],
        "link_url": link_url,
        "instagram_image_urls": image_urls,
        "instagram_caption": _build_caption(summary),
        "kakao_cards": _build_kakao_cards(data, summary, ctx, image_urls, link_url),
    }

    Path(cfg.OUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(cfg.OUT_DIR, "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(cfg.OUT_DIR, "issue_raw.json").write_text(
        json.dumps({"data": _slim_all(data), "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log.info("완료: %s · 카드 %d장", summary.get("issue_tag"), len(card_paths))
    return 0


def _slim_all(data: dict) -> dict:
    """디버그 파일에 60일치 시계열까지 쌓으면 레포가 무거워집니다."""
    out = dict(data)
    market = dict(out.get("market") or {})
    for key in ("indices", "gauges", "kr_context"):
        market[key] = _slim(market.get(key))
    out["market"] = market
    out["mover_pool"] = {k: v for k, v in list((out.get("mover_pool") or {}).items())[:40]}
    return out


if __name__ == "__main__":
    raise SystemExit(main())
