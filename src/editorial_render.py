"""Shared 3/5/7-card artwork layout; all text and numbers remain deterministic."""
from __future__ import annotations
import html
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright
from editorial_visuals import asset_data_uri, validate_visuals
from editorial_packet import KST, timestamp
from typography import card_fonts
import config as cfg

def card_context(packet, story):
    rows = [dict(row) for row in story.get('items', story.get('labels', []))]
    # Keep every source-linked number/condition from the existing contracts.
    if story.get('branches'):
        rows += [dict(label=b['label'], text=b['text'] + ' · ' + b['check'], type='watch') for b in story['branches']]
    if story.get('chart'):
        rows += [dict(label=r['label'], text=r['display']) for r in story['chart']['rows']]
    if packet.get('kind') == 'market_brief' and story['layout'] == 'headline':
        rows += [dict(label=q['name'], text=f"{q['value']:,.2f} · {q['change_pct']:+.2f}% · " + timestamp(q['as_of'], 'as_of').astimezone(KST).strftime('%H:%M') + ' KST 장중') for q in packet['quotes']]
    if packet.get('kind') == 'market_brief' and story['layout'] == 'calendar':
        rows += [dict(label=e['title'], text=timestamp(e['at'], 'at').astimezone(KST).strftime('%m.%d %H:%M') + ' KST 예정 · ' + e['note']) for e in packet['events']]
    accent = story.get('accent')
    title = story['title']
    if accent:
        before, _, after = title.partition(accent)
        title_parts = [(before, False), (accent, True), (after, False)]
    else:
        lines = title.split('\n')
        title_parts = [(lines[0], False)] + ([('\n' + lines[1], True)] if len(lines) == 2 else [])
    return {'rows': rows, 'title_parts': title_parts}

def render_cards(packet, summary, docs_cards_dir, slug):
    validate_visuals(packet)
    folder = Path(docs_cards_dir); folder.mkdir(parents=True, exist_ok=True)
    template = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=select_autoescape()).get_template('editorial_card.html')
    fonts = card_fonts(Path(cfg.OUT_DIR) / 'font-cache')
    pages = summary['visual_story']
    count = len(pages)
    date_label = packet['publication_date_kst'] + ' · 자료 출처는 상세 링크'
    if packet.get('kind') == 'breaking_news':
        from breaking_packet import release_label
        date_label = '발표 ' + release_label(packet) + ' · 확인 ' + timestamp(packet['snapshot_at'], 'snapshot_at').astimezone(KST).strftime('%m.%d %H:%M') + ' KST'
    paths = []
    with sync_playwright() as p:
        options = {'headless': True}
        if os.environ.get('CARD_CHROMIUM_PATH'):
            options['executable_path'] = os.environ['CARD_CHROMIUM_PATH']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width':1080, 'height':1350}, device_scale_factor=1)
        for n, story in enumerate(pages, 1):
            content = template.render(packet=packet, story=story, n=n, count=count, fonts=fonts,
                                      image=asset_data_uri(story['visual']), date_label=date_label,
                                      **card_context(packet, story))
            page.set_content(content, wait_until='load')
            page.evaluate('''async () => {
                await document.fonts.ready;
                await Promise.all([...document.images].map(i => i.decode()));
                if (!document.fonts.check('800 90px Editorial', '매출과 이익') || document.images[0].naturalWidth < 640)
                    throw new Error('editorial image/font load failure');
            }''')
            errors = page.evaluate('''() => {
                const errors=[];
                const footer=document.querySelector('footer').getBoundingClientRect();
                const title=document.querySelector('h1');
                if (title.scrollHeight > parseFloat(getComputedStyle(title).lineHeight)*2+4) errors.push('title exceeds two lines');
                for (const e of document.querySelectorAll('[data-fit]')) {
                    const r=e.getBoundingClientRect();
                    if(e.scrollHeight>e.clientHeight+3 || e.scrollWidth>e.clientWidth+3 || r.bottom>footer.top-16 || r.left<60 || r.right>1020) errors.push(e.className || e.tagName);
                }
                return errors;
            }''')
            if errors:
                page.screenshot(path=str(folder / f'{slug}-{n}.failure.jpg'), type='jpeg', quality=95)
                raise ValueError(f'editorial card {n}: overflow {errors}; shorten copy, never shrink text')
            path = folder / f'{slug}-{n}.jpg'
            page.screenshot(path=str(path), type='jpeg', quality=95)
            paths.append(str(path))
        browser.close()
    return paths

def render_detail_page(packet, summary, slug):
    esc = html.escape
    sections=[]
    for n, story in enumerate(summary['visual_story'], 1):
        visual=story['visual']
        attribution='AI 생성 개념 일러스트 · 실제 현장이나 공식 제품 사진이 아닙니다.' if visual['kind']=='concept' else visual['credit']+' · '+visual['license']+' · '+visual['source_url']
        rows=''.join('<li>'+esc(r['label'])+': '+esc(r['text'])+'</li>' for r in card_context(packet,story)['rows'])
        notes=' '.join(str(story.get(k,'')) for k in ('takeaway','bridge','origin'))
        if story.get('chart'): notes+=' '+story['chart']['unit']+' · '+story['chart']['source']+' · '+story['chart']['note']
        sections.append(f'<section><h2>{esc(story["title"])}</h2><img src="cards/{slug}-{n}.jpg" alt="{esc(visual["alt"],quote=True)}"><p>{esc(story["body"])}</p><ul>{rows}</ul><p>{esc(notes)}</p><small>{esc(attribution)}</small></section>')
    sources=''.join(f'<li><a href="{esc(s["url"],quote=True)}">{esc(s["title"])}</a> · {esc(s["as_of"])} · 조회 {esc(s["retrieved_at"])}</li>' for s in packet['sources'])
    review=esc(__import__('json').dumps(summary.get('editorial_review',{}),ensure_ascii=False,indent=2))
    document=f'<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(summary["visual_story"][0]["title"])}</title><style>body{{max-width:1080px;margin:32px auto;padding:24px;background:#F5F2EA;color:#17191B;font:18px/1.6 sans-serif}}img{{width:100%}}section{{margin:48px 0}}pre{{white-space:pre-wrap}}a{{color:#3157ED}}</style><h1>{esc(summary["visual_story"][0]["title"])}</h1><p>{esc(summary["instagram_caption"])}</p>{"".join(sections)}<h2>자료 출처</h2><ul>{sources}</ul><details><summary>편집 기록</summary><pre>{review}</pre></details><p>투자 참고용 · 매수·매도 권유 아님.</p></html>'
    Path(cfg.DOCS_DIR).mkdir(parents=True,exist_ok=True)
    Path(cfg.DOCS_DIR,slug+'.html').write_text(document,encoding='utf-8')
