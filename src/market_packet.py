"""Source-linked Korean intraday news; no data collection or AI calls here."""
from datetime import datetime, timedelta, timezone
import copy
from editorial_packet import PacketError, KST, text, timestamp, number, public_url, _safe_json

LAYOUTS = ['headline', 'drivers', 'sectors', 'calendar', 'watch']

def validate_market_packet(packet, *, live=False, now=None):
    _safe_json(packet)
    if packet.get('schema_version') != 1 or packet.get('kind') != 'market_brief':
        raise PacketError('expected market_brief schema 1')
    if packet.get('intent') not in ('preview', 'publish') or type(packet.get('is_test')) is not bool:
        raise PacketError('intent and boolean is_test are required')
    current = now or datetime.now(timezone.utc)
    created = timestamp(packet.get('created_at'), 'created_at')
    snapshot = timestamp(packet.get('snapshot_at'), 'snapshot_at')
    day = created.astimezone(KST).date()
    if created > current + timedelta(minutes=5) or snapshot > created:
        raise PacketError('future snapshot or creation')
    if packet.get('publication_date_kst') != day.isoformat() or snapshot.astimezone(KST).date() != day:
        raise PacketError('snapshot and publication date must match the Korean date')
    sources = packet.get('sources')
    if not isinstance(sources, list) or len(sources) < 2:
        raise PacketError('at least two sources are required')
    source_map = {}
    for s in sources:
        sid = text(s.get('id'), 'source.id', 1, 30)
        if sid in source_map:
            raise PacketError('duplicate source id')
        public_url(s.get('url'))
        text(s.get('title'), 'source.title', 3, 200)
        text(s.get('as_of'), 'source.as_of', 4, 100)
        retrieved = timestamp(s.get('retrieved_at'), 'source.retrieved_at')
        if retrieved > created + timedelta(minutes=5):
            raise PacketError('source retrieved after creation')
        source_map[sid] = s
    def refs(ids):
        if not isinstance(ids, list) or not ids or any(sid not in source_map for sid in ids):
            raise PacketError('missing or unknown evidence source')
    quotes = packet.get('quotes')
    if not isinstance(quotes, list) or {q.get('id') for q in quotes} != {'KOSPI', 'KOSDAQ'} or len(quotes) != 2:
        raise PacketError('exactly KOSPI and KOSDAQ quotes are required')
    for q in quotes:
        text(q.get('name'), 'quote.name', 2, 20)
        value, previous, pct = (number(q.get(k), 'quote.' + k) for k in ('value', 'previous_close', 'change_pct'))
        if value <= 0 or previous <= 0 or abs((value / previous - 1) * 100 - pct) > .02:
            raise PacketError('index value, previous close and percentage disagree')
        if q.get('basis') not in ('intraday', 'open'):
            raise PacketError('quote basis must be intraday or open')
        at = timestamp(q.get('as_of'), 'quote.as_of')
        if at > snapshot or at.astimezone(KST).date() != day:
            raise PacketError('quote timestamp does not match snapshot')
        refs([q.get('source_id')])
        if live and (q['basis'] != 'intraday' or current - at > timedelta(minutes=35)):
            raise PacketError('live quote must be an intraday observation within 35 minutes')
    session = packet.get('kr_session', {})
    if session.get('date') != day.isoformat() or session.get('status') != 'open' or day.weekday() > 4:
        raise PacketError('confirmed Korean trading day required')
    refs([session.get('source_id')])
    text(session.get('evidence'), 'kr_session.evidence', 10, 240)
    events = packet.get('events')
    if not isinstance(events, list) or len(events) > 3:
        raise PacketError('events must be a list of at most three verified events')
    for e in events:
        text(e.get('title'), 'event.title', 3, 40)
        text(e.get('note'), 'event.note', 5, 80)
        at = timestamp(e.get('at'), 'event.at')
        if not snapshot < at <= snapshot + timedelta(hours=36):
            raise PacketError('event must be upcoming within 36 hours')
        refs([e.get('source_id')])
    summary = packet.get('summary', {})
    text(summary.get('instagram_caption'), 'caption', 20, 400)
    story = summary.get('visual_story')
    if not isinstance(story, list) or [p.get('layout') for p in story] != LAYOUTS:
        raise PacketError('five market layouts are required in order')
    for page in story:
        text(page.get('title'), 'page.title', 5, 38)
        text(page.get('body'), 'page.body', 15, 110)
        refs(page.get('source_ids'))
        items = page.get('items', [])
        if not isinstance(items, list) or len(items) > 3:
            raise PacketError('at most three items per page')
        if page['layout'] in ('drivers', 'sectors', 'watch') and not 2 <= len(items) <= 3:
            raise PacketError('two or three news items required')
        for item in items:
            text(item.get('label'), 'item.label', 2, 25)
            text(item.get('text'), 'item.text', 5, 85)
            if item.get('type') not in ('fact', 'analysis', 'watch'):
                raise PacketError('separate fact, analysis and watch items')
            refs(item.get('source_ids'))
    if live:
        local = current.astimezone(KST)
        if packet['is_test'] or packet['intent'] != 'publish':
            raise PacketError('preview cannot publish')
        if local.date() != day or not (13*60+45 <= local.hour*60+local.minute <= 14*60+40):
            raise PacketError('afternoon publication window is 13:45–14:40 KST')
        if current - created > timedelta(minutes=35) or current - snapshot > timedelta(minutes=35):
            raise PacketError('stale intraday manuscript')
    return packet

def render_market_data(packet):
    day = datetime.fromisoformat(packet['publication_date_kst']).date()
    return {'date_kr': day.isoformat(), 'weekday_kr': '월화수목금토일'[day.weekday()],
            'focus': {'name': '오후 두시 시장 뉴스'}, 'sources': copy.deepcopy(packet['sources']),
            'market_brief': copy.deepcopy(packet)}
