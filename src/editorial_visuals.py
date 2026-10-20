"""Frozen editorial artwork: local, content-addressed assets; never a network fetch."""
from __future__ import annotations
import base64
import hashlib
import io
import re
from pathlib import Path
from editorial_packet import PacketError, text, public_url

DESIGN = 'editorial-v2'
ROOT = Path(__file__).resolve().parents[1]

def validate_visuals(packet):
    summary = packet.get('summary', {})
    design = summary.get('design')
    pages = summary.get('visual_story', [])
    if design is None:
        if any(isinstance(p, dict) and 'visual' in p for p in pages):
            raise PacketError('visual assets require summary.design=editorial-v2')
        return
    if design != DESIGN:
        raise PacketError('unsupported editorial design')
    seen = set()
    for page in pages:
        visual = page.get('visual')
        if not isinstance(visual, dict):
            raise PacketError('every editorial-v2 card needs its own visual')
        sha = visual.get('sha256', '')
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) or sha in seen:
            raise PacketError('visual hashes must be valid and distinct')
        seen.add(sha)
        path = visual.get('path', '')
        if path not in [f'automation/visual_assets/{sha}.{ext}' for ext in ('png', 'jpg')]:
            raise PacketError('visual path must be content-addressed under automation/visual_assets')
        text(visual.get('alt'), 'visual.alt', 8, 180)
        if visual.get('tone') not in ('light', 'dark'):
            raise PacketError('visual tone must be light or dark')
        if visual.get('kind') == 'concept':
            text(visual.get('prompt'), 'visual.prompt', 20, 2400)
        elif visual.get('kind') == 'photo':
            public_url(visual.get('source_url'))
            text(visual.get('credit'), 'visual.credit', 2, 180)
            text(visual.get('license'), 'visual.license', 2, 180)
        else:
            raise PacketError('visual kind must be concept or photo')
        accent = page.get('accent')
        if accent is not None and (not isinstance(accent, str) or not accent or accent not in page.get('title', '')):
            raise PacketError('accent must be an exact part of the title')

def asset_data_uri(visual, root=None):
    """Verify bytes and raster dimensions at preview build, not during promotion."""
    from PIL import Image
    root = Path(root or ROOT).resolve()
    path = root / visual['path']
    if any(p.is_symlink() for p in [path, *path.parents]) or not path.is_file():
        raise PacketError('visual is missing or is a symlink')
    if not path.resolve().is_relative_to(root / 'automation/visual_assets'):
        raise PacketError('visual escaped the approved directory')
    if not 0 < path.stat().st_size <= 12 * 1024 * 1024:
        raise PacketError('visual must be at most 12 MB')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != visual['sha256']:
        raise PacketError('visual bytes differ from the frozen manuscript')
    with Image.open(io.BytesIO(raw)) as image:
        expected = 'PNG' if path.suffix == '.png' else 'JPEG'
        if image.format != expected or min(image.size) < 640 or max(image.size) > 4096 or getattr(image, 'n_frames', 1) != 1:
            raise PacketError('visual must be a single 640..4096 pixel PNG/JPEG')
        image.verify()
    mime = 'image/png' if path.suffix == '.png' else 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
