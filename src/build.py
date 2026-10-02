"""Frozen packet -> existing licensed photos -> existing seven-card renderer."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from editorial_packet import load_packet, validate_packet, render_data, digest, slug_for, publication_key
from summarize import summarize
from editorial_packet import card_count, packet_summary

log = logging.getLogger('build')
DISCLAIMER = '투자 참고용 · 매수·매도 권유 아님.'

def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)

def _build_caption(data, summary, link_url):
    # Full financial evidence and photo attribution stay on the detailed page.
    caption = summary['instagram_caption'].strip()
    if len(caption) > 400:
        raise ValueError('caption body exceeds 400 characters; edit it instead of truncating')
    caption += ('\n\n자료 출처: ' if 'market_brief' in data else '\n\n자료·사진 출처: ') + link_url
    if DISCLAIMER not in caption:
        caption += '\n\n' + DISCLAIMER
    if len(caption) > 600:
        raise ValueError('final caption exceeds 600 characters')
    return caption

def _build_kakao_cards(data, summary, image_urls, link_url):
    return [{'title':p['title'].replace('\n', ' '), 'description':p['body'],
             'image_url':url, 'link_url':link_url}
            for p, url in zip(summary['visual_story'], image_urls)]

def build_packet(packet, *, out_dir='out', docs_dir='docs', pages_base='',
                 assets=None, renderer=None, detail_renderer=None):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    for stale in ('skip', 'state.json', 'raw.json', 'packet.json'):
        (out / stale).unlink(missing_ok=True)
    validate_packet(packet)
    count = card_count(packet)
    if renderer is None or assets is None or detail_renderer is None:
        import config as cfg
        cfg.DOCS_DIR = str(docs_dir)
        cfg.OUT_DIR = str(out_dir)
        if packet.get('kind') == 'market_brief':
            from market_render import render_cards, render_detail_page
            prepare_visual_assets = lambda data: data
        else:
            from render import render_cards, render_detail_page
            from visual_assets import prepare_visual_assets
        renderer = renderer or render_cards
        detail_renderer = detail_renderer or render_detail_page
        assets = assets or prepare_visual_assets
    data = render_data(packet)
    summary = packet_summary(packet, data)
    # This call may retrieve photographs; it must not change market/source inputs.
    original_focus = copy.deepcopy(data['focus'])
    original_sources = copy.deepcopy(data['sources'])
    data = assets(data)
    if data['focus'] != original_focus or data['sources'] != original_sources:
        raise ValueError('photo preparation changed the frozen financial inputs')
    slug = slug_for(packet)
    paths = renderer(data, summary, str(Path(docs_dir) / 'cards'), slug)
    if len(paths) != count:
        raise ValueError(f'renderer did not produce exactly {count} cards')
    from PIL import Image
    image_hashes = []
    for index, path in enumerate(paths, 1):
        path = Path(path)
        if path.name != f'{slug}-{index}.jpg':
            raise ValueError('renderer returned unexpected file order/name')
        with Image.open(path) as im:
            if im.format != 'JPEG' or im.size != (1080, 1350):
                raise ValueError('every card must be a 1080x1350 JPEG')
            im.verify()
        image_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    detail_renderer(data, summary, slug)
    base = pages_base.rstrip('/')
    parsed = urlsplit(base)
    if base and (parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment):
        raise ValueError('PAGES_BASE_URL must be a plain HTTPS base URL')
    urls = [f'{base}/cards/{slug}-{n}.jpg' for n in range(1, count + 1)]
    link = f'{base}/{slug}.html'
    state = {'schema_version':1, 'slug':slug, 'packet_sha256':digest(packet),
             'publication_key':publication_key(packet), 'intent':packet['intent'],
             'is_test':packet.get('is_test', False), 'date_kr':data['date_kr'],
             'weekday_kr':data['weekday_kr'], 'link_url':link,
             'instagram_image_urls':urls, 'image_sha256':image_hashes,
             'instagram_caption':_build_caption(data, summary, link),
             'kakao_cards':_build_kakao_cards(data, summary, urls, link)}
    write_json(out / 'packet.json', packet)
    write_json(out / 'raw.json', {'data':data, 'summary':summary})
    # State is written last, only after all seven images have passed validation.
    write_json(out / 'state.json', state)
    log.info('Frozen packet built: %s; %s JPEGs; zero AI API calls', slug, count)
    return state

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default=os.environ.get('CARD_INPUT_FILE', 'automation/inbox/latest.json'))
    parser.add_argument('--force', action='store_true', help='Compatibility only; never bypasses validation')
    parser.add_argument('--out', default='out'); parser.add_argument('--docs', default='docs')
    args = parser.parse_args(argv)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    for name in ('state.json', 'raw.json', 'packet.json', 'skip'):
        (out / name).unlink(missing_ok=True)
    if not Path(args.input).is_file():
        (out / 'skip').write_text('awaiting ChatGPT manuscript packet', encoding='utf-8')
        log.info('원고 파일 대기 중. 데이터 재수집·유료 AI·게시를 실행하지 않습니다.')
        return 0
    build_packet(load_packet(args.input), out_dir=args.out, docs_dir=args.docs,
                 pages_base=os.environ.get('PAGES_BASE_URL', ''))
    return 0

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        raise SystemExit(main())
    except Exception as exc:
        log.error('Build stopped: %s', str(exc))
        raise SystemExit(1)
