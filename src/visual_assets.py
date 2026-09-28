"""Acquire attributed, topical raster photographs from Wikimedia Commons.

prepare_visual_assets(data) returns the same data dict with cover/business assets.
Local overrides win. Automatic assets keep source/author/license evidence in JSON.
Only Commons API and upload.wikimedia.org are fetched; no article thumbnails.
Pillow, when available, performs full decoding; otherwise the renderer must decode
the image (this module still checks raster signatures and actual dimensions).
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import struct
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
API = 'https://commons.wikimedia.org/w/api.php'
MAX_BYTES = 12 * 1024 * 1024
MIN_WIDTH = 800
USER_AGENT = 'MorningBriefCardNews/2.0 (https://github.com/jyhyun12310-cmd/morning-brief)'
ALLOWED_HOSTS = {'commons.wikimedia.org', 'upload.wikimedia.org'}
ALIASES = {
    'META': ['Meta Platforms', 'Facebook headquarters', 'Facebook campus'],
    'MSTR': ['MicroStrategy', 'Microstrategy headquarters'],
    'GOOG': ['Google', 'Googleplex'], 'GOOGL': ['Google', 'Googleplex'],
    'ARE': ['Alexandria Real Estate Equities'],
    'ARM': ['Arm Holdings'], 'CAT': ['Caterpillar Inc', 'Caterpillar factory'],
}
# Explicit industry associations. Fallback photos are labeled as industry context.
INDUSTRIES = [
    (('semiconductor',), 'semiconductor fabrication cleanroom', '반도체 생산시설', ('semiconductor', 'cleanroom', 'wafer')),
    (('reit-office', 'reit office', 'biotechnology', 'diagnostics', 'pharmaceutical'), 'research laboratory interior', '연구시설', ('laboratory', 'research lab')),
    (('software', 'internet', 'information', 'communication', 'computer', 'data', 'technology'), 'data center server racks', '데이터센터', ('data center', 'data centre', 'server rack')),
    (('auto',), 'automobile factory assembly line', '자동차 생산시설', ('automobile', 'automotive', 'assembly line')),
    (('aerospace', 'airline'), 'commercial aircraft assembly factory', '항공 산업', ('aircraft', 'airplane', 'aeroplane')),
    (('oil', 'gas', 'energy'), 'oil refinery industrial photograph', '에너지 시설', ('refinery', 'oil platform')),
    (('retail', 'discount store', 'department store'), 'retail warehouse interior', '유통시설', ('warehouse', 'retail')),
    (('bank', 'financial', 'insurance', 'asset management'), 'financial district office buildings', '금융업 업무지구', ('financial district', 'office building')),
    (('industrial', 'machinery', 'manufacturing'), 'industrial manufacturing factory interior', '제조시설', ('factory', 'manufacturing')),
    (('utility', 'utilities', 'electric'), 'electric power substation', '전력시설', ('substation', 'power station')),
    (('real estate', 'reit'), 'commercial office building', '상업용 부동산', ('office building', 'commercial building')),
]


def _plain(value) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()


def _safe_url(url: str) -> str:
    p = urlparse(str(url))
    if p.scheme != 'https' or p.hostname not in ALLOWED_HOSTS or p.port not in (None, 443) or p.username or p.password:
        raise ValueError('허용되지 않은 사진 URL')
    return str(url)


def _raster(blob: bytes) -> tuple[str, int, int]:
    """Get dimensions from file bytes, not trusting HTTP or API width metadata."""
    if len(blob) < 32 or len(blob) > MAX_BYTES:
        raise ValueError('사진 크기 또는 파일 내용이 유효하지 않습니다')
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        with Image.open(io.BytesIO(blob)) as im:
            fmt, width, height = im.format, im.width, im.height
            if fmt not in {'PNG', 'JPEG', 'WEBP'} or width * height > 80_000_000:
                raise ValueError('지원하지 않는 사진 형식 또는 해상도')
            im.verify()
        with Image.open(io.BytesIO(blob)) as im:
            im.load()
        return {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[fmt], width, height
    if blob[:8] == b'\x89PNG\r\n\x1a\n' and blob[12:16] == b'IHDR' and b'IEND' in blob[-16:]:
        width, height = struct.unpack('>II', blob[16:24])
        return '.png', width, height
    if blob[:2] == b'\xff\xd8' and blob.rstrip().endswith(b'\xff\xd9'):
        p = 2
        while p + 4 < len(blob):
            if blob[p] != 255:
                p += 1
                continue
            while p < len(blob) and blob[p] == 255:
                p += 1
            marker = blob[p]
            p += 1
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(blob[p:p + 2], 'big')
            if length < 2 or p + length > len(blob):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height, width = struct.unpack('>HH', blob[p + 3:p + 7])
                return '.jpg', width, height
            p += length
    if blob[:4] == b'RIFF' and blob[8:12] == b'WEBP' and int.from_bytes(blob[4:8], 'little') + 8 == len(blob):
        kind = blob[12:16]
        if kind == b'VP8X':
            return '.webp', 1 + int.from_bytes(blob[24:27], 'little'), 1 + int.from_bytes(blob[27:30], 'little')
        if kind == b'VP8 ' and blob[23:26] == b'\x9d\x01\x2a':
            return '.webp', int.from_bytes(blob[26:28], 'little') & 0x3fff, int.from_bytes(blob[28:30], 'little') & 0x3fff
        if kind == b'VP8L' and blob[20] == 0x2f:
            packed = int.from_bytes(blob[21:25], 'little')
            return '.webp', (packed & 0x3fff) + 1, ((packed >> 14) & 0x3fff) + 1
    raise ValueError('정상 PNG/JPEG/WebP 사진이 아닙니다')


def _validate_local(item) -> dict | None:
    if not isinstance(item, dict) or not all(item.get(k) for k in ('path', 'caption', 'credit')):
        return None
    path = Path(str(item['path']))
    path = path if path.is_absolute() else ROOT / path
    try:
        if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'} or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        _, width, height = _raster(path.read_bytes())
        if width < MIN_WIDTH or height < 400 or width * height > 80_000_000:
            return None
    except (OSError, ValueError, SyntaxError):
        return None
    return {**item, 'path': str(path), 'width': width, 'height': height}


class _Budget:
    def __init__(self):
        self.end = time.monotonic() + 43
        self.calls = 0

    def left(self):
        left = self.end - time.monotonic()
        if left < 0.5 or self.calls >= 10:
            raise TimeoutError('사진 검색 시간 한도에 도달했습니다')
        return left


def _get(session, url, budget, *, params=None, binary=False):
    url = _safe_url(url)
    for attempt in range(2):
        remaining = budget.left()
        budget.calls += 1
        try:
            with session.get(url, params=params, headers={'User-Agent': USER_AGENT}, stream=True,
                             allow_redirects=False, timeout=(min(3, remaining / 2), min(4, remaining / 2))) as r:
                if r.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                    continue
                r.raise_for_status()
                if 300 <= r.status_code < 400:
                    raise ValueError('사진 다운로드 리다이렉트는 허용하지 않습니다')
                limit = MAX_BYTES if binary else 2 * 1024 * 1024
                if int(r.headers.get('Content-Length') or 0) > limit:
                    raise ValueError('사진 응답이 너무 큽니다')
                chunks, size = [], 0
                for chunk in r.iter_content(65536):
                    if time.monotonic() >= budget.end:
                        raise TimeoutError('사진 다운로드 시간 초과')
                    size += len(chunk)
                    if size > limit:
                        raise ValueError('사진 응답이 너무 큽니다')
                    chunks.append(chunk)
                content = b''.join(chunks)
                return content if binary else json.loads(content)
        except requests.RequestException:
            if attempt:
                raise
    raise ValueError('사진 다운로드 실패')


def _queries(focus):
    ticker = str(focus.get('ticker', '')).upper()
    name = re.sub(r'\s+(?:Inc\.?|Corp(?:oration)?\.?|Ltd\.?|plc|Class [A-Z]|Common Stock)\b.*$', '', str(focus.get('name') or ''), flags=re.I).strip()
    aliases = ALIASES.get(ticker) or ([name] if len(name) >= 3 and name.upper() != ticker else [])
    # Ambiguous ordinary words must not be mistaken for the listed company.
    if aliases and aliases[0].lower() in {'apple', 'target', 'gap', 'block', 'strategy', 'arm', 'unity', 'snowflake'}:
        aliases = [aliases[0] + (' Inc' if aliases[0].lower() != 'arm' else ' Holdings')]
    if aliases:
        terms = ' OR '.join('"' + a.replace('"', '') + '"' for a in aliases[:3])
        yield terms, aliases, False, ''
    industry = ' '.join(str(focus.get(k) or '') for k in ('industry', 'industry_key', 'sector', 'sector_kr')).lower()
    for markers, query, label, matching in INDUSTRIES:
        if any(marker in industry for marker in markers):
            yield query, matching, True, label
            break


def _candidate(page, markers):
    infos = page.get('imageinfo') or []
    if not infos:
        return None
    info = infos[0]
    meta = {k: _plain(v.get('value')) for k, v in (info.get('extmetadata') or {}).items() if isinstance(v, dict)}
    title = _plain(page.get('title'))
    description = meta.get('ImageDescription', '')
    text = ' '.join((title, description, meta.get('Categories', ''))).lower().replace('_', ' ')
    if not any(re.search(r'(?<!\w)' + re.escape(m.lower()) + r'(?!\w)', text) for m in markers):
        return None
    if re.search(r'\b(svg|logo|icon|diagram|chart|illustration|drawing|screenshot|map|flag|rendering|artwork|infographic)\b', title.lower()):
        return None
    if re.search(r'\b(illustration|computer.generated|rendering|screenshot|stock chart)\b', description.lower()):
        return None
    if info.get('mime') not in {'image/jpeg', 'image/png', 'image/webp'}:
        return None
    license_name = meta.get('LicenseShortName', '')
    if not re.fullmatch(r'(?:CC BY(?:-SA)? [1-4]\.0|CC0(?: 1\.0)?|Public domain|PD(?:-[\w-]+)?)', license_name, re.I):
        return None
    if re.search(r'\b(NC|ND)\b', license_name, re.I) or meta.get('Restrictions'):
        return None
    author = meta.get('Artist')
    if not author or len(author) > 1000:
        return None
    url = info.get('thumburl') or info.get('url')
    source = info.get('descriptionurl')
    if not url or not source:
        return None
    _safe_url(url)
    _safe_url(source)
    if urlparse(url).hostname != 'upload.wikimedia.org' or urlparse(source).hostname != 'commons.wikimedia.org':
        return None
    license_url = meta.get('LicenseUrl', '')
    if license_url.startswith('//'):
        license_url = 'https:' + license_url
    if license_url.startswith('http://creativecommons.org/'):
        license_url = license_url.replace('http:', 'https:', 1)
    if license_url:
        license_parts = urlparse(license_url)
        if (license_parts.scheme != 'https' or license_parts.hostname not in {'creativecommons.org', 'commons.wikimedia.org'}
                or license_parts.username or license_parts.password):
            return None
    elif license_name.upper().startswith('CC'):
        return None
    return {'asset_url': url, 'source_url': source, 'title': title.removeprefix('File:'),
            'description': description, 'author': author, 'license': license_name,
            'license_url': license_url, 'usage_terms': meta.get('UsageTerms', '')}


def prepare_visual_assets(data: dict) -> dict:
    """Fill missing photo roles. Safe failure includes manual override instructions."""
    focus = data.get('focus') or {}
    ticker = str(focus.get('ticker') or '').upper()
    if not re.fullmatch(r'[A-Z0-9.^=-]{1,20}', ticker):
        raise ValueError('사진 수집에 유효한 focus.ticker가 필요합니다')
    folder = ROOT / 'assets' / 'auto' / re.sub(r'[^A-Z0-9_-]', '_', ticker)
    sources = [data.get('visual_assets') or {}]
    for path, keyed in ((ROOT / 'assets' / 'manifest.json', True), (folder / 'credits.json', False)):
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
            sources.append(item.get(ticker, {}) if keyed else item)
        except (OSError, ValueError, AttributeError):
            pass
    assets = {}
    for role in ('cover', 'business'):
        for source in sources:
            valid = _validate_local(source.get(role)) if isinstance(source, dict) else None
            if valid:
                assets[role] = valid
                break
    if len(assets) == 2:
        data['visual_assets'] = assets
        return data
    errors, acquired, budget = [], [], _Budget()
    seen = set()
    with requests.Session() as session:
        for query, markers, generic, label in _queries(focus):
            try:
                result = _get(session, API, budget, params={
                    'action': 'query', 'format': 'json', 'generator': 'search',
                    'gsrsearch': query, 'gsrnamespace': 6, 'gsrlimit': 8,
                    'prop': 'imageinfo', 'iiprop': 'url|size|mime|extmetadata',
                    'iiurlwidth': 1400, 'iiextmetadatalanguage': 'en',
                    'iiextmetadatafilter': 'Artist|LicenseShortName|LicenseUrl|UsageTerms|ImageDescription|Categories|Restrictions',
                })
                if result.get('error'):
                    raise ValueError('Commons API: ' + str(result['error'].get('code')))
                pages = (result.get('query') or {}).get('pages') or {}
                for page in sorted(pages.values(), key=lambda p: p.get('index', 999)):
                    try:
                        item = _candidate(page, markers)
                        if not item or item['asset_url'] in seen:
                            continue
                        seen.add(item['asset_url'])
                        blob = _get(session, item['asset_url'], budget, binary=True)
                        suffix, width, height = _raster(blob)
                        if width < MIN_WIDTH or height < 400 or width * height > 80_000_000:
                            continue
                        folder.mkdir(parents=True, exist_ok=True)
                        target = folder / (hashlib.sha256(blob).hexdigest()[:20] + suffix)
                        target.write_bytes(blob)
                        caption = f'산업 참고 사진 · {ticker} 실제 시설 아님 · {label}' if generic else f'{ticker} 관련 사진 · 촬영시점과 현재 모습은 다를 수 있음'
                        credit = f"{item['author'][:70]} · {item['license']}"
                        item.update(path=str(target), caption=caption, credit=credit, width=width, height=height,
                                    credit_full=f"{item['title']} / {item['author']} / {item['license']} / {item['source_url']} / {item['license_url']}",
                                    kind='industry_reference' if generic else 'company_photo', retrieved_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
                        acquired.append(item)
                        if len(acquired) >= 2 - len(assets):
                            break
                    except (requests.RequestException, OSError, ValueError, SyntaxError) as exc:
                        errors.append(type(exc).__name__)
                if acquired:
                    break
            except (requests.RequestException, OSError, ValueError, TimeoutError) as exc:
                errors.append(str(exc)[:140])
            if time.monotonic() >= budget.end:
                break
    if acquired:
        for role in ('cover', 'business'):
            if role not in assets:
                assets[role] = dict(acquired[min(len(acquired) - 1, 0 if role == 'cover' else 1)])
    elif assets:
        existing = next(iter(assets.values()))
        for role in ('cover', 'business'):
            assets.setdefault(role, dict(existing))
    if len(assets) < 2:
        detail = '; '.join(errors[-2:]) or '회사/업종에 맞는 라이선스 확인 사진 없음'
        raise ValueError(f'{ticker}: Commons 자동 사진 수집 실패({detail}). 네트워크를 확인해 재시도하거나 assets/manifest.json의 {ticker} 항목에 cover/business의 path·caption·credit을 등록하세요. 사진은 너비800px 이상 PNG/JPEG/WebP여야 합니다.')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'credits.json').write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding='utf-8')
    data['visual_assets'] = assets
    return data
