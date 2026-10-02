"""Five distinct newsroom layouts from a frozen, validated market packet."""
import html
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright
from editorial_packet import KST, timestamp
from typography import card_fonts
import config as cfg

def render_cards(data, summary, docs_cards_dir, slug):
    folder = Path(docs_cards_dir); folder.mkdir(parents=True, exist_ok=True)
    packet = data['market_brief']
    template = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=select_autoescape()).get_template('market_card.html')
    fonts = card_fonts(Path(cfg.OUT_DIR) / 'font-cache')
    quotes = [dict(q, time=timestamp(q['as_of'], 'as_of').astimezone(KST).strftime('%H:%M'),
                   sign='+' if q['change_pct'] > 0 else '',
                   tone='up' if q['change_pct'] > 0 else 'down' if q['change_pct'] < 0 else 'flat') for q in packet['quotes']]
    events = [dict(e, time=timestamp(e['at'], 'at').astimezone(KST).strftime('%m.%d %H:%M')) for e in packet['events']]
    paths = []
    with sync_playwright() as p:
        args = {'headless': True}
        if os.environ.get('CARD_CHROMIUM_PATH'):
            args['executable_path'] = os.environ['CARD_CHROMIUM_PATH']
        browser = p.chromium.launch(**args)
        page = browser.new_page(viewport={'width':1080, 'height':1350}, device_scale_factor=1)
        for n, story in enumerate(summary['visual_story'], 1):
            content = template.render(packet=packet, story=story, n=n, fonts=fonts, quotes=quotes, events=events,
                                      snapshot=timestamp(packet['snapshot_at'], 'snapshot').astimezone(KST).strftime('%m.%d %H:%M'))
            page.set_content(content, wait_until='load')
            page.evaluate('document.fonts.ready')
            problems = page.evaluate('''() => {
              const issues = [];
              for (const e of document.querySelectorAll('[data-fit]')) {
                const r = e.getBoundingClientRect();
                if (e.scrollHeight > e.clientHeight + 2 || e.scrollWidth > e.clientWidth + 2 || r.bottom > 1270) issues.push(e.tagName + ':' + e.className);
              }
              if (!document.fonts.check('700 40px Display') || !document.fonts.check('400 32px Body')) issues.push('fonts');
              return issues;
            }''')
            if problems:
                raise ValueError(f'market card {n} overflow/font failure: {problems}')
            path = folder / f'{slug}-{n}.jpg'
            page.screenshot(path=str(path), type='jpeg', quality=95)
            paths.append(str(path))
        browser.close()
    return paths

def render_detail_page(data, summary, slug):
    esc = html.escape
    sources = ''.join(f'<li><a href="{esc(s["url"], quote=True)}">{esc(s["title"])}</a> — {esc(s["as_of"])} (확인 {esc(s["retrieved_at"])})</li>' for s in data['sources'])
    cards = ''.join(f'<img src="cards/{slug}-{n}.jpg" alt="{esc(s["title"], quote=True)}" loading="lazy">' for n,s in enumerate(summary['visual_story'],1))
    content = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(summary['visual_story'][0]['title'])}</title><style>body{{max-width:1080px;margin:32px auto;padding:20px;background:#f6f3eb;color:#122e2b;font:18px/1.7 sans-serif}}img{{width:100%;display:block;margin:24px 0}}a{{color:#12665b}}</style><h1>오후 두시 · 시장 뉴스</h1><p>{esc(data['market_brief']['snapshot_at'])} 기준 · 장중 수치는 이후 달라질 수 있습니다.</p><p>{esc(summary['instagram_caption'])}</p><h2>자료 출처</h2><ul>{sources}</ul>{cards}<p>사실·해석·관전 포인트를 구분한 정보 콘텐츠. 투자 참고용 · 매수·매도 권유 아님.</p></html>'''
    Path(cfg.DOCS_DIR).mkdir(parents=True, exist_ok=True)
    Path(cfg.DOCS_DIR, slug + '.html').write_text(content, encoding='utf-8')
