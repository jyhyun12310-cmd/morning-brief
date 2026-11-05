"""Validate a supplied seven-card manuscript. No AI SDK, key, or paid fallback."""
from __future__ import annotations
import copy
from editorial_packet import PacketError, number, public_url, text

LAYOUTS = ('cover', 'photo', 'annotated', 'comparison', 'explain', 'conditions', 'closing')
class SummaryGenerationError(PacketError):
    pass

def _ids(values, field, available):
    if (not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values)
            or len(set(values)) != len(values) or not set(values) <= available):
        raise SummaryGenerationError(field + ': valid, unique reference IDs are required')

def validate_summary(result, allowed_source_urls=None):
    if not isinstance(result, dict) or result.get('status') == 'insufficient_evidence':
        raise SummaryGenerationError('complete, sourced manuscript required')
    for field, low, high in [('central_question', 12, 70), ('thesis', 40, 220),
                             ('edition', 1, 30), ('instagram_caption', 40, 400)]:
        text(result.get(field), field, low, high)
    sources = result.get('sources')
    if not isinstance(sources, list) or not sources:
        raise SummaryGenerationError('sources are required')
    source_ids = set()
    for source in sources:
        sid = text(source.get('id'), 'source.id', 1, 30)
        if sid in source_ids:
            raise SummaryGenerationError('duplicate source id')
        source_ids.add(sid)
        text(source.get('title'), 'source.title', 3, 200)
        public_url(source.get('url'))
        if allowed_source_urls is not None and source['url'] not in allowed_source_urls:
            raise SummaryGenerationError('source URL was not supplied in the packet')
        text(source.get('as_of'), 'source.as_of', 4, 100)
    notes = result.get('evidence_notes')
    if not isinstance(notes, list) or len(notes) < 4:
        raise SummaryGenerationError('at least four distinct evidence notes are required')
    evidence_ids = set()
    for note in notes:
        eid = text(note.get('id'), 'evidence.id', 1, 30)
        if eid in evidence_ids:
            raise SummaryGenerationError('duplicate evidence id')
        evidence_ids.add(eid)
        text(note.get('claim'), 'evidence.claim', 15, 450)
        _ids(note.get('source_ids'), 'evidence.source_ids', source_ids)
    pages = result.get('visual_story')
    if not isinstance(pages, list) or len(pages) != 7:
        raise SummaryGenerationError('exactly seven cards are required')
    titles, bodies = set(), set()
    # Opt in by omitting both redundant blocks on the editorial-v2 cover only.
    compact_cover = (result.get('design') == 'editorial-v2' and isinstance(pages[0], dict)
                     and 'takeaway' not in pages[0] and 'bridge' not in pages[0])
    for i, page in enumerate(pages):
        if not isinstance(page, dict) or page.get('layout') != LAYOUTS[i]:
            raise SummaryGenerationError('incorrect layout order')
        title = text(page.get('title'), 'page.title', 8, 55)
        if title.count('\n') > 1:
            raise SummaryGenerationError('title exceeds two lines')
        if compact_cover and i == 0:
            body = text(page.get('body'), 'cover comparison', 8, 55)
            if len(title) > 32 or len(body.splitlines()) != 1:
                raise SummaryGenerationError('compact cover needs a short title and one comparison line')
            if any(page.get(k) for k in ('labels', 'items', 'chart', 'branches', 'origin')):
                raise SummaryGenerationError('move compact cover details onto a supporting card')
        else:
            body = text(page.get('body'), 'page.body', 40, 85 if i == 0 else 170)
            text(page.get('takeaway'), 'page.takeaway', 25, 70)
            text(page.get('bridge'), 'page.bridge', 18, 45)
        titles.add(title.replace('\n', ' ')); bodies.add(body)
        _ids(page.get('evidence_ids'), 'page.evidence_ids', evidence_ids)
        labels = page.get('labels', [])
        required = i in (1, 2, 4, 6) or (i == 3 and not page.get('chart'))
        if not isinstance(labels, list) or len(labels) > 3 or (required and len(labels) < 2):
            raise SummaryGenerationError('two or three explanatory labels are required')
        for label in labels:
            text(label.get('label'), 'label.label', 1, 24)
            text(label.get('text'), 'label.text', 3, 70)
        if i == 3 and page.get('chart'):
            chart = page['chart']
            for field, low, high in [('source',3,120), ('note',5,100), ('unit',1,40)]:
                text(chart.get(field), 'chart.' + field, low, high)
            rows = chart.get('rows')
            if not isinstance(rows, list) or not 2 <= len(rows) <= 5:
                raise SummaryGenerationError('chart needs two to five source-linked rows')
            for row in rows:
                number(row.get('value'), 'chart.value')
                text(row.get('label'), 'chart.label', 1, 34)
                text(row.get('display'), 'chart.display', 1, 32)
        if i == 5:
            text(page.get('origin'), 'page.origin', 5, 65)
            branches = page.get('branches')
            if not isinstance(branches, list) or len(branches) != 2:
                raise SummaryGenerationError('supporting and opposing conditions are required')
            for branch in branches:
                for field, low, high in [('label',3,24), ('text',12,65), ('check',10,65)]:
                    text(branch.get(field), 'branch.' + field, low, high)
    if compact_cover:
        supported = {ref for page in pages[1:] for ref in page['evidence_ids']}
        if not set(pages[0]['evidence_ids']) <= supported:
            raise SummaryGenerationError('support compact cover evidence on cards 2–7')
    if len(titles) != 7 or len(bodies) != 7:
        raise SummaryGenerationError('duplicate card text')
    return result

def _compatibility_keys(result):
    pages = result['visual_story']
    result.update(cover_title=pages[0]['title'], cover_sub=pages[0].get('takeaway', pages[0]['body']),
                  conclusion=pages[6]['takeaway'], cover_qs=[pages[i]['title'] for i in (1,2,4)])
    for n in range(2, 7):
        page = pages[n-1]
        result[f'p{n}_q'] = page['title']; result[f'p{n}_a'] = page['takeaway']
        result[f'p{n}_secs'] = [{'h':'핵심 설명','t':page['body']}] + [
            {'h':r['label'],'t':r['text']} for r in page.get('labels', [])[:2]]
    result['p3_flow'] = [{'step':r['label'],'text':r['text']} for r in pages[2]['labels']]
    result['p6_bull'] = [{'fact':pages[5]['branches'][0]['text'],'check':pages[5]['branches'][0]['check']}]
    result['p6_bear'] = [{'fact':pages[5]['branches'][1]['text'],'check':pages[5]['branches'][1]['check']}]
    result.update(p7_oneline=pages[6]['title'], p7_facts=[r['claim'] for r in result['evidence_notes'][:3]],
                  p7_keep=pages[5]['branches'][0]['text'], p7_review=pages[5]['branches'][1]['text'],
                  p7_checks=[f"{r['label']}: {r['text']}" for r in pages[6]['labels']],
                  source_line='자료·사진 출처: 게시글의 상세 링크', kr_line=result.get('kr_line',''))
    result.setdefault('kakao_text', pages[0]['title'] + ' — ' + pages[6]['takeaway'])
    return result

def summarize(data, draft=None):
    if draft is None:
        raise SummaryGenerationError('유료 AI 호출은 제거되었습니다. 원고와 시세가 포함된 JSON 파일을 전달하세요.')
    result = copy.deepcopy(draft)
    validate_summary(result, {s['url'] for s in data.get('sources', [])})
    return _compatibility_keys(result)
