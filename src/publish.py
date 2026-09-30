"""Default: offline preview. Live Instagram requires explicit gates + durable lock."""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from editorial_packet import load_packet, digest, publication_key, slug_for
from publication_journal import GitHubJournal, JournalError, publish_once

log = logging.getLogger('publish')

class RedactSecrets(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for key in ('IG_ACCESS_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN', 'KAKAO_REFRESH_TOKEN'):
            value = os.environ.get(key)
            if value:
                message = message.replace(value, '[REDACTED]')
        record.msg, record.args = message, ()
        # HTTP exception tracebacks can contain credential-bearing URLs.
        if record.exc_info:
            record.msg += ' [exception details omitted to protect credentials]'
            record.exc_info = None; record.exc_text = None
        return True

def validate_state(state, packet, pages_base):
    expected_slug = slug_for(packet)
    base = pages_base.rstrip('/')
    expected_urls = [f'{base}/cards/{expected_slug}-{n}.jpg' for n in range(1,8)]
    if (state.get('schema_version') != 1 or state.get('packet_sha256') != digest(packet)
            or state.get('publication_key') != publication_key(packet)
            or state.get('slug') != expected_slug or state.get('instagram_image_urls') != expected_urls):
        raise ValueError('state does not match the frozen packet and expected image URLs')
    hashes = state.get('image_sha256')
    if not isinstance(hashes, list) or len(hashes) != 7 or any(
            not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h) for h in hashes):
        raise ValueError('seven image hashes are required')
    from summarize import summarize
    from editorial_packet import render_data
    from build import _build_caption
    data = render_data(packet)
    expected_caption = _build_caption(data, summarize(data, packet['summary']))
    if state.get('instagram_caption') != expected_caption:
        raise ValueError('caption changed after packet validation')
    return state

def verify_public_images(state, *, session=None, attempts=12, delay=10):
    import requests
    session = session or requests.Session()
    for url, expected in zip(state['instagram_image_urls'], state['image_sha256']):
        for attempt in range(attempts):
            try:
                response = session.get(url, timeout=25, allow_redirects=False)
                if (response.status_code == 200 and
                    response.headers.get('Content-Type','').split(';')[0] == 'image/jpeg' and
                    hashlib.sha256(response.content).hexdigest() == expected):
                    break
            except requests.RequestException:
                pass
            if attempt + 1 < attempts:
                time.sleep(delay)
        else:
            raise RuntimeError('public image is unavailable or differs from the validated JPEG')

def main(argv=None):
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--live', action='store_true')
    group.add_argument('--dry-run', action='store_true')
    parser.add_argument('--out', default='out')
    parser.add_argument('--settings', default='automation/settings.json')
    args = parser.parse_args(argv)
    out = Path(args.out)
    if (out / 'skip').exists():
        log.info('No packet; nothing to publish.')
        return 0
    packet = load_packet(out / 'packet.json', live=args.live)
    state = json.loads((out / 'state.json').read_text(encoding='utf-8'))
    base = os.environ.get('PAGES_BASE_URL', '').rstrip('/')
    validate_state(state, packet, base)
    if not args.live:
        log.info('DRY RUN OK: seven JPEGs; frozen data/caption match; Instagram and journal untouched.')
        return 0
    settings = json.loads(Path(args.settings).read_text(encoding='utf-8'))
    if settings.get('allow_publish') is not True or os.environ.get('ALLOW_INSTAGRAM_PUBLISH') != 'YES':
        raise ValueError('live publication has not been enabled')
    expected_host = urlsplit(base).hostname or ''
    if (urlsplit(base).scheme != 'https' or not expected_host.endswith('.github.io')
            or urlsplit(base).query or urlsplit(base).fragment):
        raise ValueError('live PAGES_BASE_URL must be the configured GitHub Pages URL')
    for required in ('IG_USER_ID', 'IG_ACCESS_TOKEN', 'GH_TOKEN', 'GITHUB_REPOSITORY'):
        if not os.environ.get(required):
            raise ValueError(required + ' is missing; no publication attempted')
    import publish_instagram
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactSecrets())
    journal = GitHubJournal(os.environ['GITHUB_REPOSITORY'], os.environ['GH_TOKEN'])
    key = publication_key(packet)
    existing = journal.read(key)
    if existing:
        if existing[0].get('status') == 'published':
            log.info('Duplicate session skipped: %s', key)
            return 0
        raise JournalError('reserved session: manual reconciliation required; no retry')
    verify_public_images(state)
    result = publish_once(journal, key, digest(packet), lambda: publish_instagram.publish_carousel(
        image_urls=state['instagram_image_urls'], caption=state['instagram_caption'],
        token_dir=str(out / 'tokens')))
    (out / 'publish_result.json').write_text(json.dumps(result), encoding='utf-8')
    log.info('Publication status: %s', result['status'])
    # Kakao cards remain in state for compatibility but are not sent by this
    # Instagram-only automation. This avoids an unrelated side effect.
    return 0

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Deliberately omit network exception text/traceback, which may contain tokens.
        log.error('Publication stopped (%s). Check gates, inputs, Pages, or the journal; do not blindly retry.', type(exc).__name__)
        raise SystemExit(1)
