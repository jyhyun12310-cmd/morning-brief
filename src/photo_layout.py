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


def _legacy_pages(data: dict, s: dict) -> list:
    """Bridge the existing summary keys. No missing-data narratives are fabricated."""
    def rows(key):
        return [{'label': x.get('h',''), 'text': x.get('t','')} for x in (s.get(key) or [])[:2]]
    pages = [
        {'layout':'cover','title':s.get('cover_title'), 'takeaway':s.get('cover_sub'), 'labels':[]},
        {'layout':'photo','title':s.get('p2_q'), 'takeaway':s.get('p2_a'), 'labels':rows('p2_secs')},
        {'layout':'annotated','title':s.get('p3_q'), 'takeaway':s.get('p3_a'),
         'labels':[{'label':x.get('step',''),'text':x.get('text','')} for x in (s.get('p3_flow') or [])[:3]]},
        {'layout':'comparison','title':s.get('p4_q'), 'takeaway':s.get('p4_a'), 'labels':rows('p4_secs')},
        {'layout':'explain','title':s.get('p5_q'), 'takeaway':s.get('p5_a'), 'labels':rows('p5_secs')},
        {'layout':'conditions','title':s.get('p6_q'), 'takeaway':s.get('p6_a'),
         'branches':[{'label':'기대를 지지하는 근거','text':'; '.join(str(x.get('fact','')) for x in (s.get('p6_bull') or [])[:1]),
                      'check':'; '.join(str(x.get('check','')) for x in (s.get('p6_bull') or [])[:1])},
                     {'label':'다시 확인할 근거','text':'; '.join(str(x.get('fact','')) for x in (s.get('p6_bear') or [])[:1]),
                      'check':'; '.join(str(x.get('check','')) for x in (s.get('p6_bear') or [])[:1])}]},
        {'layout':'closing','title':'그래서, 지금의 답은', 'takeaway':s.get('conclusion'),
         'labels':[{'label':str(i+1).zfill(2),'text':x} for i,x in enumerate((s.get('p7_checks') or [])[:3])]},
    ]
    return pages


def build_photo_deck(data: dict, summary: dict) -> dict:
    photos = _photos(data)
    stories = summary.get('visual_story') or _legacy_pages(data, summary)
    if not isinstance(stories, list) or len(stories) != 7:
        raise ValueError('visual_story 는 정확히 7장이어야 합니다.')
    layouts = {'cover','photo','annotated','comparison','explain','conditions','closing'}
    pages=[]
    for index, raw in enumerate(stories):
        layout=raw.get('layout')
        if layout not in layouts:
            raise ValueError(f'지원하지 않는 layout: {layout}')
        labels=[{'label':_text(x.get('label'),24), 'text':_text(x.get('text'),70)} for x in (raw.get('labels') or [])[:3]]
        page={**raw,'layout':layout,'title':_text(raw.get('title'),55),
              'takeaway':_text(raw.get('takeaway'),140), 'labels':labels,
              'photo':photos['business' if index in (1,4,5) else 'cover']}
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
                    page['chart'].update(note=chart['note'],source=chart['source'])
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
            'edition':_text(summary.get('edition','한 종목 깊이 읽기'),30),
            'footer':_text(summary.get('source_line','자료 출처·기준일은 게시물 캡션 참고'),90)}
