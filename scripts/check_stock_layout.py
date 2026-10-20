"""Render a historical stock fixture for layout QA only; never publish it."""
import argparse
import json
from pathlib import Path

from build import build_packet
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture')
    parser.add_argument('--out', required=True)
    parser.add_argument('--docs', required=True)
    args = parser.parse_args()
    packet = json.loads(Path(args.fixture).read_text(encoding='utf-8'))
    if packet.get('intent') != 'preview' or not packet.get('is_test'):
        raise ValueError('Layout fixtures must be non-publishing test previews')
    try:
        build_packet(packet, out_dir=args.out, docs_dir=args.docs)
    except Exception:
        # Diagnostics are not a successful preview or publishable output.
        for html in sorted(Path(args.out).glob('_card-*.html')):
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={'width': 1080, 'height': 1350})
                page.goto(html.resolve().as_uri())
                page.wait_for_load_state('networkidle')
                page.evaluate('document.fonts.ready')
                details = page.evaluate('''() => [...document.querySelectorAll(
                  'main, h1, .body-copy, .visual, .hero, .cover-credit, .cover-stats, .cover-stat, .bridge'
                )].map(el => ({tag:el.tagName, cls:el.className,
                  text:el.textContent.trim(), height:el.clientHeight, scroll:el.scrollHeight,
                  rect:el.getBoundingClientRect().toJSON()}))''')
                print(json.dumps(details, ensure_ascii=False))
                page.screenshot(path=str(html.with_suffix('.failure.jpg')), type='jpeg')
                browser.close()
        raise


if __name__ == '__main__':
    main()
