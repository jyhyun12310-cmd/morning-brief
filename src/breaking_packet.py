"""Verified material event -> three-card bulletin, with a stable event identity."""
import copy
import hashlib
import re
from datetime import datetime, timedelta, timezone
from editorial_packet import PacketError, KST, text, timestamp, public_url, _safe_json

CATEGORIES = {'rates','inflation','employment','policy','geopolitics','systemic','major_earnings'}

def news_key(packet):
    event = packet['event']
    identity = event['issuer'] + '/' + event['release_id']
    return 'market-news-' + hashlib.sha256(identity.encode()).hexdigest()[:24]

def validate_breaking_packet(packet, *, live=False, now=None):
    _safe_json(packet)
    if packet.get('schema_version') != 1 or packet.get('kind') != 'breaking_news':
        raise PacketError('expected breaking_news schema 1')
    if packet.get('intent') not in ('preview','publish') or type(packet.get('is_test')) is not bool:
        raise PacketError('intent and boolean is_test are required')
    current = now or datetime.now(timezone.utc)
    created = timestamp(packet.get('created_at'),'created_at')
    snapshot = timestamp(packet.get('snapshot_at'),'snapshot_at')
    if created > current + timedelta(minutes=5) or snapshot > created:
        raise PacketError('future news snapshot or creation')
    if packet.get('publication_date_kst') != created.astimezone(KST).date().isoformat():
        raise PacketError('publication_date_kst differs from created_at')
    event = packet.get('event',{})
    for k in ('issuer','release_id'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,79}',text(event.get(k),'event.'+k)):
            raise PacketError('event identity must be a stable lowercase release identifier')
    occurred = timestamp(event.get('occurred_at'),'event.occurred_at')
    if occurred > snapshot or event.get('category') not in CATEGORIES:
        raise PacketError('unsupported category or event not yet released')
    if event.get('status') != 'confirmed' or event.get('market_scope') not in ('broad_market','major_sector','systemic'):
        raise PacketError('only confirmed material market events qualify')
    text(event.get('materiality'),'event.materiality',25,300)
    sources = packet.get('sources')
    if not isinstance(sources,list) or not sources:
        raise PacketError('original announcement is required')
    source_map={}
    for s in sources:
        sid=text(s.get('id'),'source.id',1,30)
        if sid in source_map: raise PacketError('duplicate source id')
        public_url(s.get('url')); text(s.get('title'),'source.title',3,200)
        text(s.get('as_of'),'source.as_of',4,120)
        retrieved=timestamp(s.get('retrieved_at'),'retrieved_at')
        if retrieved > created + timedelta(minutes=5): raise PacketError('source after creation')
        source_map[sid]=s
    primary=source_map.get(event.get('primary_source_id'),{})
    if primary.get('kind') != 'primary' or primary.get('published_at') is None:
        raise PacketError('dated primary announcement required')
    if timestamp(primary['published_at'],'published_at') != occurred:
        raise PacketError('event time differs from official announcement time')
    if timestamp(primary['retrieved_at'],'retrieved_at') < occurred:
        raise PacketError('primary source retrieved before announcement')
    def refs(ids):
        if not isinstance(ids,list) or not ids or any(s not in source_map for s in ids):
            raise PacketError('source-linked evidence required')
    summary=packet.get('summary',{})
    text(summary.get('instagram_caption'),'caption',20,400)
    story=summary.get('visual_story')
    if not isinstance(story,list) or [p.get('layout') for p in story] != ['headline','impact','watch']:
        raise PacketError('three bulletin layouts required')
    for page in story:
        text(page.get('title'),'title',5,38); text(page.get('body'),'body',15,100)
        refs(page.get('source_ids'))
        items=page.get('items',[])
        if not isinstance(items,list) or not 2 <= len(items) <= 3:
            raise PacketError('two or three short items required')
        for item in items:
            text(item.get('label'),'label',2,22); text(item.get('text'),'item.text',5,80)
            if item.get('type') not in ('fact','analysis','watch'): raise PacketError('label facts and analysis')
            refs(item.get('source_ids'))
    if live:
        if packet['intent'] != 'publish' or packet['is_test']:
            raise PacketError('preview and test bulletins cannot publish')
        if current - occurred > timedelta(hours=3):
            raise PacketError('old news must not be published as breaking news')
        if current - created > timedelta(minutes=35) or current - snapshot > timedelta(minutes=35):
            raise PacketError('stale breaking-news manuscript')
        if current < occurred or current < snapshot:
            raise PacketError('news has not been observed yet')
    return packet

def render_breaking_data(packet):
    day=datetime.fromisoformat(packet['publication_date_kst']).date()
    return {'date_kr':day.isoformat(),'weekday_kr':'월화수목금토일'[day.weekday()],
            'focus':{'name':'시장 핵심 속보'},'sources':copy.deepcopy(packet['sources']),
            'market_brief':copy.deepcopy(packet)}
