"""Promote only the exact JPEG bytes inspected in a successful preview."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.request import Request, urlopen
from editorial_packet import load_packet, validate_packet, digest, slug_for, card_count, render_data, packet_summary, publication_key
from build import write_json, _build_caption, _build_kakao_cards
from publish import validate_state

def review_reference(packet):
    review = packet.get('reviewed_preview')
    if not isinstance(review, dict) or set(review) != {'run_id', 'image_sha256'}:
        raise ValueError('live packet requires reviewed_preview run_id and image_sha256')
    run_id = review['run_id']
    hashes = review['image_sha256']
    if type(run_id) is not int or run_id <= 0:
        raise ValueError('invalid reviewed preview run ID')
    if not isinstance(hashes, list) or len(hashes) != card_count(packet) or any(
        not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h) for h in hashes):
        raise ValueError('invalid reviewed image hashes')
    return review

def verify_run(run, repository, workflow, run_id):
    if (run.get('id') != run_id or run.get('status') != 'completed'
        or run.get('conclusion') != 'success' or run.get('head_branch') != 'main'
        or run.get('path') != '.github/workflows/' + workflow
        or run.get('event') not in ('push', 'workflow_dispatch')
        or (run.get('head_repository') or {}).get('full_name') != repository):
        raise ValueError('review must reference a successful same-repository main preview')

def promote(packet, source, *, out_dir='out', docs_dir='docs', pages_base='', now=None):
    validate_packet(packet, live=True, now=now)
    review = review_reference(packet)
    source, out, docs = Path(source), Path(out_dir), Path(docs_dir)
    preview = load_packet(source / 'out/packet.json', now=now)
    if preview['intent'] != 'preview' or preview.get('is_test') or 'reviewed_preview' in preview:
        raise ValueError('only a real unpublished preview may be promoted')
    expected = copy.deepcopy(packet)
    expected.pop('reviewed_preview')
    expected['intent'] = 'preview'
    if digest(expected) != digest(preview):
        raise ValueError('content or timestamps changed since preview; render and inspect again')
    state = json.loads((source / 'out/state.json').read_text(encoding='utf-8'))
    validate_state(state, preview, pages_base)
    if review['image_sha256'] != state['image_sha256']:
        raise ValueError('reviewed hashes do not match the preview')
    old_slug, new_slug = slug_for(preview), slug_for(packet)
    detail_path = source / 'docs' / (old_slug + '.html')
    if not detail_path.is_file() or detail_path.is_symlink():
        raise ValueError('preview detail page is missing')
    images = []
    from PIL import Image
    for n, h in enumerate(review['image_sha256'], 1):
        path = source / 'docs/cards' / f'{old_slug}-{n}.jpg'
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != h:
            raise ValueError('preview image is missing or changed')
        with Image.open(path) as im:
            if im.format != 'JPEG' or im.size != (1080, 1350):
                raise ValueError('preview image dimensions or format changed')
            im.verify()
        images.append(path)
    # All validation precedes writes. Never render or fetch a replacement photo.
    out.mkdir(parents=True, exist_ok=True)
    (docs / 'cards').mkdir(parents=True, exist_ok=True)
    for n, path in enumerate(images, 1):
        shutil.copyfile(path, docs / 'cards' / f'{new_slug}-{n}.jpg')
    (docs / (new_slug + '.html')).write_text(
        detail_path.read_text(encoding='utf-8').replace(old_slug, new_slug), encoding='utf-8')
    urls = [f'{pages_base.rstrip("/")}/cards/{new_slug}-{n}.jpg' for n in range(1, card_count(packet)+1)]
    link = f'{pages_base.rstrip("/")}/{new_slug}.html'
    data = render_data(packet)
    summary = packet_summary(packet, data)
    state.update(slug=new_slug, packet_sha256=digest(packet), publication_key=publication_key(packet),
                 intent='publish', is_test=False, link_url=link, instagram_image_urls=urls,
                 instagram_caption=_build_caption(data, summary, link),
                 kakao_cards=_build_kakao_cards(data, summary, urls, link))
    validate_state(state, packet, pages_base)
    write_json(out / 'packet.json', packet)
    write_json(out / 'state.json', state)
    shutil.copyfile(source / 'out/raw.json', out / 'raw.json')
    (out / 'skip').unlink(missing_ok=True)
    return state

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--source', default='reviewed-preview')
    parser.add_argument('--workflow', required=True)
    args = parser.parse_args()
    packet = load_packet(args.input, live=True)
    review = review_reference(packet)
    repo = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('invalid repository')
    request = Request(f'https://api.github.com/repos/{repo}/actions/runs/{review["run_id"]}',
                      headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                               'Accept': 'application/vnd.github+json'})
    with urlopen(request, timeout=30) as response:
        run = json.load(response)
    verify_run(run, repo, args.workflow, review['run_id'])
    state = promote(packet, args.source, pages_base=os.environ['PAGES_BASE_URL'])
    print(f'Reused {len(state["image_sha256"])} reviewed JPEGs without rendering')
if __name__ == '__main__':
    main()
