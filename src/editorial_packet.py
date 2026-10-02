"""Frozen ChatGPT manuscript + market snapshot. No market or AI network calls."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')
BASIS_KEYS = ('ticker', 'session_date', 'price_basis', 'currency', 'close', 'previous_close', 'change_pct')
SECRET = re.compile(r'(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|cookie)', re.I)

class PacketError(ValueError):
    pass

def number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PacketError(f'{field}: a finite number is required')
    return float(value)

def text(value, field, minimum=1, maximum=2000):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise PacketError(f'{field}: expected {minimum}..{maximum} characters')
    return value.strip()

def timestamp(value, field):
    try:
        result = datetime.fromisoformat(text(value, field).replace('Z', '+00:00'))
    except ValueError as exc:
        raise PacketError(f'{field}: invalid ISO timestamp') from exc
    if result.tzinfo is None:
        raise PacketError(f'{field}: timezone is required')
    return result

def public_url(value):
    parsed = urlsplit(text(value, 'source.url'))
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or not host or '.' not in host or parsed.username or parsed.password
            or host == 'localhost' or host.endswith(('.local', '.internal'))):
        raise PacketError('source.url must be a public HTTPS URL without credentials')
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise PacketError('non-public source address')
    if any(SECRET.search(k) for k, _ in parse_qsl(parsed.query)):
        raise PacketError('credentials are forbidden in source URLs')
    return value

def _safe_json(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET.search(key):
                raise PacketError('credential-like field is forbidden in a public packet')
            _safe_json(child)
    elif isinstance(value, list):
        for child in value:
            _safe_json(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise PacketError('non-finite JSON number')

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()

def validate_packet(packet, *, live=False, now=None):
    if isinstance(packet, dict) and packet.get('kind') == 'breaking_news':
        from breaking_packet import validate_breaking_packet
        return validate_breaking_packet(packet, live=live, now=now)
    if isinstance(packet, dict) and packet.get('kind') == 'market_brief':
        from market_packet import validate_market_packet
        return validate_market_packet(packet, live=live, now=now)
    if isinstance(packet, dict) and packet.get('kind') not in (None, 'stock'):
        raise PacketError('unknown packet kind')
    from summarize import validate_summary
    if not isinstance(packet, dict) or packet.get('schema_version') != 1:
        raise PacketError('schema_version must be 1')
    _safe_json(packet)
    if packet.get('intent') not in ('preview', 'publish'):
        raise PacketError('intent must be preview or publish')
    if type(packet.get('is_test', False)) is not bool:
        raise PacketError('is_test must be boolean')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise PacketError('now must have timezone')
    created = timestamp(packet.get('created_at'), 'created_at')
    if created > current + timedelta(minutes=5):
        raise PacketError('created_at is in the future')
    market = packet.get('market')
    if not isinstance(market, dict):
        raise PacketError('market is required')
    ticker = text(market.get('ticker'), 'market.ticker', 1, 15)
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', ticker):
        raise PacketError('invalid ticker')
    text(market.get('name'), 'market.name', 1, 100)
    if market.get('currency') != 'USD' or market.get('price_basis') != 'regular_close':
        raise PacketError('only USD regular-session closes are supported')
    closed = timestamp(market.get('session_close_at'), 'session_close_at')
    session = closed.astimezone(NY).date()
    if market.get('session_date') != session.isoformat() or session.weekday() > 4:
        raise PacketError('market session date must match the US close timestamp')
    if created < closed or current < closed:
        raise PacketError('the supplied market session has not closed')
    close = number(market.get('close'), 'close')
    previous = number(market.get('previous_close'), 'previous_close')
    pct = number(market.get('change_pct'), 'change_pct')
    if close <= 0 or previous <= 0 or abs((close / previous - 1) * 100 - pct) > .02:
        raise PacketError('close, previous_close and change_pct disagree')
    if live:
        if packet.get('is_test') or packet['intent'] != 'publish':
            raise PacketError('test and preview packets cannot publish')
        if current - closed > timedelta(hours=36) or current - created > timedelta(hours=24):
            raise PacketError('stale packet; do not publish a previous session as current')
        if packet.get('publication_date_kst') != current.astimezone(KST).date().isoformat():
            raise PacketError('publication_date_kst is not today')
    expected_date = created.astimezone(KST).date().isoformat()
    if packet.get('publication_date_kst') != expected_date:
        raise PacketError('publication_date_kst does not match created_at')
    sources = packet.get('sources')
    if not isinstance(sources, list) or not sources:
        raise PacketError('sources are required')
    source_map = {}
    for source in sources:
        if not isinstance(source, dict):
            raise PacketError('source must be an object')
        sid = text(source.get('id'), 'source.id', 1, 30)
        if sid in source_map:
            raise PacketError('duplicate source id')
        public_url(source.get('url'))
        text(source.get('title'), 'source.title', 3, 200)
        text(source.get('as_of'), 'source.as_of', 4, 100)
        retrieved = timestamp(source.get('retrieved_at'), 'source.retrieved_at')
        if retrieved > created + timedelta(minutes=5):
            raise PacketError('source retrieved after packet creation')
        source_map[sid] = source
    if market.get('source_id') not in source_map:
        raise PacketError('market.source_id is missing from sources')
    summary = packet.get('summary')
    if not isinstance(summary, dict) or summary.get('market_basis') != {k: market[k] for k in BASIS_KEYS}:
        raise PacketError('summary.market_basis and frozen market snapshot disagree')
    validate_summary(summary, {s['url'] for s in sources})
    for source in summary['sources']:
        original = source_map.get(source['id'])
        if original is None or any(source.get(k) != original.get(k) for k in ('title', 'url', 'as_of')):
            raise PacketError('summary source metadata differs from the frozen sources')
    if market['source_id'] not in {s['id'] for s in summary['sources']}:
        raise PacketError('the market price source must appear in the caption sources')
    metrics = {}
    for metric in packet.get('metrics', []):
        mid = text(metric.get('id'), 'metric.id', 1, 40)
        if mid in metrics or metric.get('source_id') not in source_map:
            raise PacketError('duplicate metric or missing metric source')
        number(metric.get('value'), 'metric.value')
        for key in ('unit', 'period', 'basis'):
            text(metric.get(key), 'metric.' + key, 1, 100)
        metrics[mid] = metric
    chart = summary['visual_story'][3].get('chart')
    if chart:
        bases = set()
        for row in chart['rows']:
            metric = metrics.get(row.get('metric_id'))
            if not metric or row['value'] != metric['value'] or chart['unit'] != metric['unit']:
                raise PacketError('chart must use unchanged, source-linked metric values and units')
            if metric['source_id'] not in {s['id'] for s in summary['sources']}:
                raise PacketError('chart source missing from caption sources')
            bases.add(metric['basis'])
        if len(bases) != 1:
            raise PacketError('incomparable accounting bases in a chart')
    return packet

def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PacketError('duplicate JSON key: ' + key)
        result[key] = value
    return result

def load_packet(path, *, live=False, now=None):
    source = Path(path)
    if source.stat().st_size > 250_000:
        raise PacketError('packet is larger than 250 KB')
    packet = json.loads(source.read_text(encoding='utf-8'), object_pairs_hook=_unique_keys)
    return validate_packet(packet, live=live, now=now)

def render_data(packet):
    """Reconstruct renderer input exclusively from the frozen snapshot."""
    if packet.get('kind') == 'breaking_news':
        from breaking_packet import render_breaking_data
        return render_breaking_data(packet)
    if packet.get('kind') == 'market_brief':
        from market_packet import render_market_data
        return render_market_data(packet)
    m = packet['market']
    date = datetime.fromisoformat(packet['publication_date_kst']).date()
    return {'date_kr': date.isoformat(), 'weekday_kr': '월화수목금토일'[date.weekday()],
            'focus': {'ticker': m['ticker'], 'name': m['name'], 'last': m['close'],
                      'pct': m['change_pct'], 'currency': 'USD'},
            'sources': copy.deepcopy(packet['sources']), 'news': [], 'focus_news': []}

def publication_key(packet):
    if packet.get('kind') == 'breaking_news':
        from breaking_packet import news_key
        return news_key(packet)
    if packet.get('kind') == 'market_brief':
        return 'kr-market-' + packet['publication_date_kst'] + '-afternoon'
    # One stock per US market session, including corrections and ticker changes.
    return 'us-stock-' + packet['market']['session_date']

def slug_for(packet):
    if packet.get('kind') == 'breaking_news':
        return packet['publication_date_kst'] + '-news-' + digest(packet)[:12]
    if packet.get('kind') == 'market_brief':
        return packet['publication_date_kst'] + '-market-' + digest(packet)[:12]
    return packet['market']['session_date'] + '-' + packet['market']['ticker'].lower() + '-' + digest(packet)[:12]

def card_count(packet):
    if packet.get('kind') == 'breaking_news':
        return 3
    return 5 if packet.get('kind') == 'market_brief' else 7

def packet_summary(packet, data):
    if packet.get('kind') in ('market_brief','breaking_news'):
        return copy.deepcopy(packet['summary'])
    from summarize import summarize
    return summarize(data, packet['summary'])
