import copy
import json
from datetime import datetime
from pathlib import Path
import pytest
from editorial_packet import validate_packet, publication_key, card_count, PacketError, render_data, packet_summary
from publication_journal import GitHubJournal
from build import build_packet
from publish import validate_state

BASE = Path(__file__).resolve().parents[1]

@pytest.fixture
def packet():
    p = json.loads((BASE/'automation/examples/market-preview.json').read_text(encoding='utf-8'))
    p.update(created_at='2026-10-02T14:00:00+09:00', snapshot_at='2026-10-02T13:58:00+09:00', intent='publish')
    for q in p['quotes']:
        q.update(basis='intraday', as_of=p['snapshot_at'])
    return p

NOW = datetime.fromisoformat('2026-10-02T14:05:00+09:00')

def test_live_market_and_distinct_key(packet):
    validate_packet(packet, live=True, now=NOW)
    assert card_count(packet) == 5
    assert publication_key(packet) == 'kr-market-2026-10-02-afternoon'
    journal = GitHubJournal('owner/repo', 'unit-test-token')
    assert journal._url(publication_key(packet)).endswith('kr-market-2026-10-02-afternoon.json')
    assert journal._url('us-stock-2026-10-01').endswith('us-stock-2026-10-01.json')

@pytest.mark.parametrize('change', ['stale','future','percent','missing_source','closed','six_cards','preview','old_open','wrong_date','before_window','past_event','unknown_kind'])
def test_bad_market_packets_stop(packet, change):
    now = NOW
    if change == 'stale': packet['quotes'][0]['as_of']='2026-10-02T12:00:00+09:00'
    if change == 'future': packet['quotes'][0]['as_of']='2026-10-02T14:06:00+09:00'
    if change == 'percent': packet['quotes'][0]['change_pct']=99
    if change == 'missing_source': packet['summary']['visual_story'][1]['items'][0]['source_ids']=['missing']
    if change == 'closed': packet['kr_session']['status']='closed'
    if change == 'six_cards': packet['summary']['visual_story'].append(copy.deepcopy(packet['summary']['visual_story'][0]))
    if change == 'preview': packet['intent']='preview'
    if change == 'old_open': packet['quotes'][0]['basis']='open'
    if change == 'wrong_date': packet['publication_date_kst']='2026-10-01'
    if change == 'before_window': now=datetime.fromisoformat('2026-10-02T12:00:00+09:00')
    if change == 'past_event': packet['events'][0]['at']='2026-10-02T01:00:00+09:00'
    if change == 'unknown_kind': packet['kind']='newstype'
    with pytest.raises(PacketError): validate_packet(packet, live=True, now=now)

def test_five_card_build_and_caption_integrity(packet, tmp_path):
    from PIL import Image
    def renderer(data, summary, folder, slug):
        Path(folder).mkdir(parents=True, exist_ok=True)
        paths=[]
        for n in range(1,6):
            p=Path(folder)/f'{slug}-{n}.jpg'
            Image.new('RGB',(1080,1350),color=(n,10,20)).save(p)
            paths.append(p)
        return paths
    packet['created_at']='2026-10-02T09:30:00+09:00'
    packet['snapshot_at']='2026-10-02T09:20:00+09:00'
    for s in packet['sources']: s['retrieved_at']=packet['created_at']
    for q in packet['quotes']: q['as_of']=packet['snapshot_at']
    state=build_packet(packet,out_dir=tmp_path/'out',docs_dir=tmp_path/'docs',pages_base='https://owner.github.io/repo',renderer=renderer,detail_renderer=lambda *a:None,assets=lambda d:d)
    validate_state(state,packet,'https://owner.github.io/repo')
    assert len(state['image_sha256']) == 5
    state['instagram_caption']+=' changed'
    with pytest.raises(ValueError): validate_state(state,packet,'https://owner.github.io/repo')

def test_event_timezone_and_preview_are_preserved(packet):
    from editorial_packet import timestamp, KST
    at=timestamp(packet['events'][0]['at'],'event').astimezone(KST)
    assert at.strftime('%H:%M') == '21:30'
    data=render_data(packet)
    assert packet_summary(packet,data)==packet['summary']
    assert data['market_brief']['quotes']==packet['quotes']
