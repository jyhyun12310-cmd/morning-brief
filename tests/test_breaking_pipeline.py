import copy
import json
from pathlib import Path
from datetime import datetime
import pytest
from editorial_packet import validate_packet, publication_key, card_count, PacketError
from publication_journal import GitHubJournal
from build import build_packet
from publish import validate_state

BASE=Path(__file__).resolve().parents[1]
NOW=datetime.fromisoformat('2026-10-02T22:35:00+09:00')

@pytest.fixture
def packet():
    p=json.loads((BASE/'automation/examples/breaking-preview.json').read_text(encoding='utf-8'))
    p.update(intent='publish',is_test=False,created_at='2026-10-02T22:30:00+09:00',snapshot_at='2026-10-02T22:28:00+09:00')
    p['event']['occurred_at']='2026-10-02T22:15:00+09:00'
    p['sources'][0].update(published_at=p['event']['occurred_at'],retrieved_at=p['snapshot_at'])
    return p

def test_confirmed_event_can_publish_at_night(packet):
    validate_packet(packet,live=True,now=NOW)
    assert card_count(packet)==3
    assert GitHubJournal('owner/repo','test-token')._url(publication_key(packet)).endswith('.json')

def test_same_release_cannot_republish_with_new_date_or_title(packet):
    changed=copy.deepcopy(packet)
    changed['publication_date_kst']='2026-10-03'
    changed['summary']['visual_story'][0]['title']='새로운 제목으로 바꾼 동일 발표'
    assert publication_key(packet)==publication_key(changed)
    changed['event']['release_id']='2026-10-03-new-decision'
    assert publication_key(packet)!=publication_key(changed)

@pytest.mark.parametrize('issue',['old','future','test','preview','undated','secondary','mismatch','rumor','smallcap','unsupported','missing_evidence','stale','four_cards','no_materiality','bad_identity','source_before_release'])
def test_invalid_bulletins_stop(packet,issue):
    if issue=='old':
        packet['event']['occurred_at']='2026-10-02T18:00:00+09:00'
        packet['sources'][0]['published_at']=packet['event']['occurred_at']
    if issue=='future': packet['event']['occurred_at']='2026-10-02T22:40:00+09:00'
    if issue=='test': packet['is_test']=True
    if issue=='preview': packet['intent']='preview'
    if issue=='undated': del packet['sources'][0]['published_at']
    if issue=='secondary': packet['sources'][0]['kind']='secondary'
    if issue=='mismatch': packet['sources'][0]['published_at']='2026-10-02T21:30:00+09:00'
    if issue=='rumor': packet['event']['status']='unconfirmed'
    if issue=='smallcap': packet['event']['market_scope']='single_small_cap'
    if issue=='unsupported': packet['event']['category']='celebrity'
    if issue=='missing_evidence': packet['summary']['visual_story'][1]['items'][0]['source_ids']=[]
    if issue=='stale': packet['created_at']='2026-10-02T20:00:00+09:00';packet['snapshot_at']=packet['created_at']
    if issue=='four_cards': packet['summary']['visual_story'].append(copy.deepcopy(packet['summary']['visual_story'][0]))
    if issue=='no_materiality': packet['event']['materiality']=''
    if issue=='bad_identity': packet['event']['release_id']='../override'
    if issue=='source_before_release': packet['sources'][0]['retrieved_at']='2026-10-02T22:00:00+09:00'
    with pytest.raises(PacketError): validate_packet(packet,live=True,now=NOW)

def test_three_card_build_hash_and_caption_integrity(tmp_path):
    from PIL import Image
    p=json.loads((BASE/'automation/examples/breaking-preview.json').read_text(encoding='utf-8'))
    def renderer(data,summary,folder,slug):
        Path(folder).mkdir(parents=True,exist_ok=True);paths=[]
        for n in range(1,4):
            path=Path(folder)/f'{slug}-{n}.jpg';Image.new('RGB',(1080,1350),(n,20,30)).save(path);paths.append(path)
        return paths
    state=build_packet(p,out_dir=tmp_path/'out',docs_dir=tmp_path/'docs',pages_base='https://owner.github.io/repo',renderer=renderer,detail_renderer=lambda *a:None,assets=lambda d:d)
    validate_state(state,p,'https://owner.github.io/repo')
    assert len(state['image_sha256'])==3
    state['instagram_image_urls'].append('https://owner.github.io/extra.jpg')
    with pytest.raises(ValueError):validate_state(state,p,'https://owner.github.io/repo')
