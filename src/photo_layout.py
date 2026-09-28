"""Photo-first presentation context. No invented market data or remote image fetches."""
from __future__ import annotations
import base64
import json
import math
import mimetypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _embed(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"이미지/폰트 파일이 없습니다: {path}")
    if path.stat().st_size > 18 * 1024 * 1024:
        raise ValueError(f"이미지는 18MB 이하로 준비하세요: {path.name}")
    content = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return f"data:{mime};base64," + base64.b64encode(content).decode('ascii')


def _photos(data: dict) -> dict:
    ticker = str((data.get('focus') or {}).get('ticker', '')).upper()
    supplied = data.get('visual_assets')
    if supplied is None:
        manifest = ROOT / 'assets' / 'manifest.json'
        supplied = json.loads(manifest.read_text(encoding='utf-8')).get(ticker, {}) if manifest.exists() else {}
    result = {}
    for role in ('cover', 'business'):
        item = supplied.get(role) or {}
        if not item.get('path') or not item.get('caption') or not item.get('credit'):
            raise ValueError(f"{ticker}: {role} 사진의 path·caption·credit을 assets/manifest.json 또는 data.visual_assets에 등록하세요. 사진 없는 게시물은 만들지 않습니다.")
        path = Path(item['path'])
        if not path.is_absolute():
            path = ROOT / path
        if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError('사진은 PNG/JPEG/WebP 로 준비하세요.')
        result[role] = {**item, 'src': _embed(path)}
    return result


def _text(value, limit=140):
    value = str(value or '').strip()
    if len(value) > limit:
        raise ValueError(f"카드 문장이 너무 깁니다({len(value)}자): {value[:38]}… 문장을 편집해 주세요.")
    return value


def comparison(rows: list, unit: str = '') -> dict | None:
    """Shared zero baseline, signed values, finite numbers only. True geometry."""
    if len(rows) < 2:
        return None
    clean = []
    for row in rows[:5]:
        value = row.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('비교 차트 값은 유한한 숫자여야 합니다.')
        clean.append({'label': _text(row.get('label'), 34), 'value': value,
                      'display': _text(row.get('display', f'{value:g}{unit}'), 32)})
    lo = min(0, *(r['value'] for r in clean))
    hi = max(0, *(r['value'] for r in clean))
    span = hi - lo or 1
    zero = (0-lo)/span * 100
    for row in clean:
        end = (row['value']-lo)/span * 100
        row.update(left=min(zero, end), width=abs(end-zero))
    return {'rows': clean, 'zero': zero, 'unit': unit}


def build_photo_deck(data: dict, summary: dict) -> dict:
    # Reject stale/thin summaries instead of silently replacing them with generic text.
    from summarize import validate_summary
    validate_summary(summary)
    photos = _photos(data)
    stories = summary.get('visual_story')
    if not isinstance(stories, list) or len(stories) != 7:
        raise ValueError('visual_story 는 정확히 7장이어야 합니다.')
    layouts = {'cover','photo','annotated','comparison','explain','conditions','closing'}
    pages=[]
    chapters=['오늘의 질문','확인된 변화','사업과 연결','숫자의 의미','평가의 기준','반론과 조건','질문에 대한 답']
    sources={x['id']:x for x in summary['sources']}
    evidence={x['id']:x for x in summary['evidence_notes']}
    for index, raw in enumerate(stories):
        layout=raw.get('layout')
        if layout not in layouts:
            raise ValueError(f'지원하지 않는 layout: {layout}')
        labels=[{'label':_text(x.get('label'),32), 'text':_text(x.get('text'),70),
                 'note':_text(x.get('note'),60)} for x in (raw.get('labels') or [])[:3]]
        source_ids=list(dict.fromkeys(sid for eid in raw['evidence_ids'] for sid in evidence[eid]['source_ids']))
        # Keep the card readable even when original publication titles are long.
        source_line='출처 '+ '·'.join(source_ids) + ' / 원문·기준일은 게시물 캡션 참고'
        page={**raw,'layout':layout,'title':_text(raw.get('title'),55),
              'body':_text(raw.get('body'),170), 'bridge':_text(raw.get('bridge'),45),
              'chapter':chapters[index], 'source_line':_text(raw.get('source_line') or source_line,160),
              'takeaway':_text(raw.get('takeaway'),70), 'labels':labels,
              'photo':photos['business' if index in (1,4,5) else 'cover']}
        if raw.get('photo_role'):
            if raw['photo_role'] not in photos:
                raise ValueError(f"등록되지 않은 photo_role: {raw['photo_role']}")
            page['photo']=photos[raw['photo_role']]
        if not page['title']:
            raise ValueError(f'{index+1}장 제목이 없습니다.')
        page['chart']=None
        # Explicit source metadata is required before a market-data chart is shown.
        if layout=='comparison':
            chart=raw.get('chart') or {}
            if not chart:
                focus=data.get('focus') or {}
                history=focus.get('revenue_history') or []
                source=focus.get('revenue_source')
                if history and source:
                    chart={'rows':[{'label':x['period'],'value':x['value'],'display':f"${x['value']/1e6:,.0f}M"} for x in history[-5:]],
                           'unit':'USD','source':source,'note':'매출 · 같은 0 기준'}
            if chart:
                if not chart.get('source') or not chart.get('note'):
                    raise ValueError('차트에는 source와 note가 필요합니다.')
                page['chart']=comparison(chart.get('rows') or [], chart.get('unit',''))
                if page['chart']:
                    page['chart'].update(note=_text(chart['note'],100),source=_text(chart['source'],120),
                                         annotation=_text(chart.get('annotation'),65))
            if not page['chart'] and not labels:
                raise ValueError('차트 자료가 없으면 의미 있는 labels로 근거를 설명하세요.')
        if layout=='conditions':
            branches=raw.get('branches') or []
            if len(branches)!=2 or any(not b.get('text') or not b.get('check') for b in branches):
                raise ValueError('조건 도식에는 내용이 있는 두 갈래(text·check)가 필요합니다.')
            page['branches']=[{'label':_text(b.get('label'),24),'text':_text(b['text'],65),'check':_text(b['check'],65)} for b in branches]
        pages.append(page)
    if [p['layout'] for p in pages].count('cover')!=1 or pages[0]['layout']!='cover' or pages[-1]['layout']!='closing':
        raise ValueError('첫 장은 cover, 마지막 장은 closing 이어야 합니다.')
    return {'pages':pages,'font':_embed(ROOT/'assets/NotoSansKR.ttf'),
            'edition':_text(summary.get('edition','한 종목 깊이 읽기'),50),
            'footer':_text(summary.get('source_line','자료 출처·기준일은 게시물 캡션 참고'),90)}
