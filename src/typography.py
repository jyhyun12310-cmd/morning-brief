"""Pinned OFL fonts, embedded into cards so rendering never silently substitutes."""
from __future__ import annotations
import base64
import hashlib
import io
import time
import zipfile
from pathlib import Path

import requests

FONTS = {
    'display': {
        'url': 'https://corp.gmarket.com/fonts/GmarketSansTTF.zip',
        'sha256': 'a2cc0ab9eb3bc868a6f2affd89fa1d4718cb6e1226dcb695b05d0d2ff417ae02',
        'member': 'GmarketSansTTFBold.ttf', 'mime': 'font/ttf',
    },
    'body': {
        'url': 'https://raw.githubusercontent.com/orioncactus/pretendard/v1.3.9/packages/pretendard/dist/web/variable/woff2/PretendardVariable.woff2',
        'sha256': '9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4',
        'mime': 'font/woff2',
    },
}


def card_fonts(cache_dir: str | Path) -> dict:
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    result = {}
    for role, spec in FONTS.items():
        path = cache / (spec['sha256'] + '.bin')
        content = path.read_bytes() if path.is_file() else b''
        if hashlib.sha256(content).hexdigest() != spec['sha256']:
            for attempt in range(3):
                try:
                    response = requests.get(spec['url'], timeout=40)
                    response.raise_for_status()
                    content = response.content
                    if len(content) > 8 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != spec['sha256']:
                        raise ValueError(f'{role} font differs from the reviewed official release')
                    path.write_bytes(content)
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
        if spec.get('member'):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                content = archive.read(spec['member'])
        result[role] = f"data:{spec['mime']};base64," + base64.b64encode(content).decode('ascii')
    return result
