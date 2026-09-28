"""Generate a sourced, seven-card editorial story; never publish a thin fallback.

The public summarize(data) interface and legacy publisher keys are preserved.
Only supplied source material is sent to the model. This module does not fetch news.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

log = logging.getLogger(__name__)

# Confirmed in the official model overview on 2026-09-28; env override is retained.
# https://platform.claude.com/docs/en/models/overview
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
# Sonnet 5's default adaptive thinking shares this limit with its response text.
MAX_TOKENS = 16000
SYSTEM = (Path(__file__).parent / "photo_editorial_prompt.txt").read_text(encoding="utf-8")
LAYOUTS = ("cover", "photo", "annotated", "comparison", "explain", "conditions", "closing")
_DROP_FIELDS = {"series", "series_60", "spark", "_peer_raw", "visual_assets"}
_SECRET_KEY = re.compile(r"(?:^|_)(?:api_key|token|password|secret|authorization|cookie)(?:$|_)", re.I)
_URL = re.compile(r"https?://[^\s<>\"'\]\[{}]+")


class SummaryGenerationError(RuntimeError):
    """The pipeline must stop here instead of rendering or publishing empty cards."""


def _clean_input(value, key=""):
    """Keep news bodies, periods, accounting bases and new metrics without a whitelist."""
    if isinstance(value, dict):
        return {str(k): _clean_input(v, str(k)) for k, v in value.items()
                if str(k) not in _DROP_FIELDS and not _SECRET_KEY.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [_clean_input(v, key) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None  # A missing numeric value is never converted to zero.
    if isinstance(value, str) and value.startswith("data:"):
        return None  # Binary image/font payloads are not editorial evidence.
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"원자료의 {key or '항목'}에 JSON으로 전달할 수 없는 {type(value).__name__} 값이 있습니다.")


def _source_urls(value) -> set[str]:
    urls = set()
    if isinstance(value, dict):
        for child in value.values():
            urls.update(_source_urls(child))
    elif isinstance(value, list):
        for child in value:
            urls.update(_source_urls(child))
    elif isinstance(value, str):
        for match in _URL.findall(value):
            url = match.rstrip(".,;:!?)）")
            parsed = urlsplit(url)
            if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
                urls.add(url)
    return urls


def _extract_json(text: str) -> dict:
    """Accept a complete JSON object, optionally enclosed in one code fence."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    result = json.loads(clean)
    if not isinstance(result, dict):
        raise ValueError("응답 최상위는 JSON 객체여야 합니다.")
    return result


def _string(value, field: str, low: int = 1, high: int = 2000) -> str:
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        size = len(value.strip()) if isinstance(value, str) else "문자열 아님"
        raise ValueError(f"{field}: {low}~{high}자 필요(현재 {size}).")
    return value.strip()


def _ids(value, field: str, available: set[str]) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or v not in available for v in value):
        raise ValueError(f"{field}: 실제 존재하는 근거/출처 ID를 1개 이상 연결해야 합니다.")
    if len(set(value)) != len(value):
        raise ValueError(f"{field}: 중복 ID가 있습니다.")


def validate_summary(result: dict, allowed_source_urls: set[str] | None = None) -> dict:
    """Validate completeness, references and geometry inputs; not a semantic fact checker."""
    if not isinstance(result, dict):
        raise ValueError("원고 최상위는 JSON 객체여야 합니다.")
    if result.get("status") == "insufficient_evidence":
        missing = result.get("missing") or []
        raise ValueError("원자료 부족: " + "; ".join(str(x) for x in missing))
    for field, low, high in (("central_question", 12, 70), ("thesis", 40, 220),
                             ("edition", 1, 30), ("instagram_caption", 500, 2200)):
        _string(result.get(field), field, low, high)
    sources = result.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources: 실제 원자료 출처가 1개 이상 필요합니다.")
    source_ids = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}]: 객체여야 합니다.")
        sid = _string(source.get("id"), f"sources[{index}].id", 1, 30)
        if sid in source_ids:
            raise ValueError(f"sources: 중복 ID {sid}")
        source_ids.add(sid)
        _string(source.get("title"), f"sources[{index}].title", 3, 200)
        url = _string(source.get("url"), f"sources[{index}].url", 10, 2000)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"sources[{index}].url: 유효한 공개 출처 URL이 필요합니다.")
        if allowed_source_urls is not None and url not in allowed_source_urls:
            raise ValueError(f"sources[{index}].url: 입력에 없는 URL을 만들었습니다: {url}")
        _string(source.get("as_of"), f"sources[{index}].as_of", 4, 100)

    notes = result.get("evidence_notes")
    if not isinstance(notes, list) or len(notes) < 4:
        raise ValueError("evidence_notes: 서로 다른 사실/설명 근거가 4개 이상 필요합니다.")
    evidence_ids = set()
    for index, note in enumerate(notes):
        if not isinstance(note, dict):
            raise ValueError(f"evidence_notes[{index}]: 객체여야 합니다.")
        eid = _string(note.get("id"), f"evidence_notes[{index}].id", 1, 30)
        if eid in evidence_ids:
            raise ValueError(f"evidence_notes: 중복 ID {eid}")
        evidence_ids.add(eid)
        _string(note.get("claim"), f"evidence_notes[{index}].claim", 15, 450)
        _ids(note.get("source_ids"), f"evidence_notes[{index}].source_ids", source_ids)

    pages = result.get("visual_story")
    if not isinstance(pages, list) or len(pages) != 7:
        raise ValueError("visual_story: 정확히 7장의 원고가 필요합니다.")
    bodies, titles = [], []
    for index, page in enumerate(pages):
        prefix = f"visual_story[{index}]({index+1}장)"
        if not isinstance(page, dict) or page.get("layout") != LAYOUTS[index]:
            raise ValueError(f"{prefix}: layout은 {LAYOUTS[index]}여야 합니다.")
        title = _string(page.get("title"), prefix + ".title", 8, 55)
        if title.count("\n") > 1:
            raise ValueError(f"{prefix}.title: 제목은 최대 2줄입니다.")
        titles.append(title.replace("\n", " "))
        bodies.append(_string(page.get("body"), prefix + ".body", 40 if index == 0 else 80, 85 if index == 0 else 170))
        _string(page.get("takeaway"), prefix + ".takeaway", 25, 70)
        _string(page.get("bridge"), prefix + ".bridge", 18, 45)
        _ids(page.get("evidence_ids"), prefix + ".evidence_ids", evidence_ids)
        labels = page.get("labels") or []
        needs_labels = index in {1, 2, 4, 6} or (index == 3 and not page.get("chart"))
        if not isinstance(labels, list) or len(labels) > 3 or (needs_labels and len(labels) < 2):
            raise ValueError(f"{prefix}.labels: 구체적인 설명 라벨 2~3개가 필요합니다.")
        for label_index, label in enumerate(labels):
            if not isinstance(label, dict):
                raise ValueError(f"{prefix}.labels[{label_index}]: 객체여야 합니다.")
            _string(label.get("label"), prefix + ".label", 1, 24)
            _string(label.get("text"), prefix + ".text", 3, 70)
        if index == 3 and page.get("chart"):
            chart = page["chart"]
            if not isinstance(chart, dict):
                raise ValueError(f"{prefix}.chart: 객체여야 합니다.")
            _string(chart.get("source"), prefix + ".chart.source", 3, 120)
            _string(chart.get("note"), prefix + ".chart.note", 5, 100)
            _string(chart.get("unit"), prefix + ".chart.unit", 1, 40)
            rows = chart.get("rows")
            if not isinstance(rows, list) or not 2 <= len(rows) <= 5:
                raise ValueError(f"{prefix}.chart.rows: 같은 기준의 수치 2~5개가 필요합니다.")
            for row in rows:
                value = row.get("value") if isinstance(row, dict) else None
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{prefix}.chart.rows: 실제 유한 수치가 필요합니다.")
                _string(row.get("label"), prefix + ".chart.label", 1, 34)
                _string(row.get("display"), prefix + ".chart.display", 1, 32)
        if index == 5:
            _string(page.get("origin"), prefix + ".origin", 5, 65)
            branches = page.get("branches")
            if not isinstance(branches, list) or len(branches) != 2:
                raise ValueError(f"{prefix}.branches: 지지 조건과 반론 조건 2개가 필요합니다.")
            for branch in branches:
                if not isinstance(branch, dict):
                    raise ValueError(f"{prefix}.branches: 각 조건은 객체여야 합니다.")
                for field, low, high in (("label", 3, 24), ("text", 12, 65), ("check", 10, 65)):
                    _string(branch.get(field), prefix + ".branches." + field, low, high)
    if len(set(bodies)) != 7 or len(set(titles)) != 7:
        raise ValueError("같은 본문이나 제목을 여러 장에 반복할 수 없습니다.")
    return result


def _compatibility_keys(result: dict) -> dict:
    """Derive old keys from the validated story; no independently invented copy."""
    pages = result["visual_story"]
    result.update(cover_title=pages[0]["title"], cover_sub=pages[0]["takeaway"],
                  conclusion=pages[6]["takeaway"],
                  cover_qs=[pages[i]["title"].replace("\n", " ") for i in (1, 2, 4)])
    for number in range(2, 7):
        page = pages[number - 1]
        result[f"p{number}_q"] = page["title"]
        result[f"p{number}_a"] = page["takeaway"]
        result[f"p{number}_secs"] = [{"h": "핵심 설명", "t": page["body"]}] + [
            {"h": row["label"], "t": row["text"]} for row in page.get("labels", [])[:2]]
    result["p3_flow"] = [{"step": row["label"], "text": row["text"]} for row in pages[2]["labels"]]
    result["p6_bull"] = [{"fact": pages[5]["branches"][0]["text"], "check": pages[5]["branches"][0]["check"]}]
    result["p6_bear"] = [{"fact": pages[5]["branches"][1]["text"], "check": pages[5]["branches"][1]["check"]}]
    result.update(p7_oneline=pages[6]["title"], p7_facts=[row["claim"] for row in result["evidence_notes"][:3]],
                  p7_keep=pages[5]["branches"][0]["text"], p7_review=pages[5]["branches"][1]["text"],
                  p7_checks=[f"{row['label']}: {row['text']}" for row in pages[6]["labels"]])
    if not isinstance(result.get("kakao_text"), str) or not result["kakao_text"].strip():
        result["kakao_text"] = pages[0]["title"].replace("\n", " ") + " — " + pages[6]["takeaway"]
    if not isinstance(result.get("kr_line"), str):
        result["kr_line"] = ""
    if not isinstance(result.get("source_line"), str) or not result["source_line"].strip():
        result["source_line"] = "자료 출처·기준일: 게시물 캡션 참고"
    missing = [f"• {s['title']} ({s['as_of']})\n{s['url']}" for s in result["sources"]
               if s["url"] not in result["instagram_caption"]]
    if missing:
        result["instagram_caption"] += "\n\n자료 출처\n" + "\n".join(missing)
    if len(result["instagram_caption"]) > 2200:
        raise ValueError("출처를 포함한 instagram_caption이 2,200자를 넘습니다. 근거를 유지하며 설명을 줄여 주세요.")
    return result


def _save_diagnostic(payload: dict, raw: str, error: str, attempt: int, stop_reason=None) -> str:
    root = Path(os.environ.get("CARD_DIAGNOSTIC_DIR", "out/summary_diagnostics"))
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    directory = root / f"{stamp}_{uuid4().hex[:8]}_attempt{attempt}"
    directory.mkdir()
    (directory / "input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "response.txt").write_text(raw, encoding="utf-8")
    (directory / "error.json").write_text(json.dumps({"error": error, "stop_reason": stop_reason,
        "attempt": attempt, "model": MODEL}, ensure_ascii=False, indent=2), encoding="utf-8")
    log.error("원고 검증 실패; 원문 보존: %s (%s)", directory, error)
    return str(directory)


def summarize(data: dict) -> dict:
    """One initial generation and, only for a malformed draft, one repair request."""
    if not isinstance(data, dict):
        raise SummaryGenerationError("summarize(data)의 원자료는 dict여야 합니다.")
    payload = _clean_input(data)
    allowed_urls = _source_urls(payload)
    if not allowed_urls:
        path = _save_diagnostic(payload, "", "원자료에 출처 URL이 없습니다. 뉴스 본문·공시 수치·URL·기준일을 수집기에 추가하세요.", 0)
        raise SummaryGenerationError(f"출처 없는 원고 생성은 중단했습니다. 원자료 확인: {path}")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SummaryGenerationError("ANTHROPIC_API_KEY가 없습니다. API 키를 설정한 뒤 다시 실행하세요.")
    # Lazy import keeps validation and the local preview independent of API packages.
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise SummaryGenerationError("anthropic 패키지가 없습니다. 기존 requirements 의존성을 설치하세요.") from exc
    client = Anthropic(api_key=api_key, max_retries=0)
    user_input = json.dumps({"task": "원자료에 근거해 질문 하나에 답하는 7장 카드뉴스 JSON을 작성하세요.",
                             "source_material": payload}, ensure_ascii=False, allow_nan=False)
    messages = [{"role": "user", "content": user_input}]
    last_path = ""
    for attempt in (1, 2):
        raw, stop_reason = "", None
        try:
            response = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                                               system=SYSTEM, messages=messages)
        except Exception as exc:
            last_path = _save_diagnostic(payload, raw, f"API {type(exc).__name__}: {exc}", attempt)
            raise SummaryGenerationError(f"원고 API 요청에 실패했습니다. 자동 게시를 중단합니다. 확인: {last_path}") from exc
        raw = "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text")
        stop_reason = getattr(response, "stop_reason", None)
        try:
            if stop_reason != "end_turn":
                raise ValueError(f"응답이 완결되지 않았습니다(stop_reason={stop_reason}).")
            result = _extract_json(raw)
            validate_summary(result, allowed_urls)
            result = _compatibility_keys(result)
            log.info("출처 %d개, 근거 %d개, 7장 원고 검증 통과(시도 %d)", len(result["sources"]), len(result["evidence_notes"]), attempt)
            return result
        except (ValueError, TypeError, KeyError) as exc:
            last_path = _save_diagnostic(payload, raw, str(exc), attempt, stop_reason)
            if attempt == 2 or stop_reason not in {"end_turn", "max_tokens"}:
                raise SummaryGenerationError(f"7장 원고를 완성하지 못해 자동 게시를 중단했습니다. {exc} 확인: {last_path}") from exc
            messages = [
                {"role": "user", "content": user_input},
                {"role": "user", "content": "이전 응답에 아래 오류가 있습니다. 원자료만 사용해 완전한 JSON 객체를 처음부터 1회 다시 작성하세요. "
                 "빈칸이나 일반론으로 보충하지 말고 모든 필수필드·분량·출처 ID를 맞추세요. 원자료로 불가능하면 "
                 "{\"status\":\"insufficient_evidence\",\"missing\":[\"구체적으로 부족한 자료\"]}를 반환하세요.\n"
                 + json.dumps({"validation_error": str(exc), "previous_draft": raw}, ensure_ascii=False)}]
    raise SummaryGenerationError(f"원고 생성이 중단되었습니다. 확인: {last_path}")
