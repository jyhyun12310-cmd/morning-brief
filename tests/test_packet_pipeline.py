"""Offline regression suite. All prices, sources, assets and HTTP replies are synthetic."""
import base64
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import build
import editorial_packet as ep
import publication_journal as pj
import publish
import summarize

NOW = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
BASE = 'https://jyhyun12310-cmd.github.io/morning-brief'


def sample_packet():
    """Fictional fixture, never an investment article or a live publication packet."""
    source = dict(id='S1', title='SYNTHETIC TEST ONLY — not market evidence',
                  url='https://example.com/test-only', as_of='2026-09-29 TEST',
                  retrieved_at='2026-09-29T21:30:00Z')
    market = dict(ticker='TEST', name='FICTIONAL TEST COMPANY', session_date='2026-09-29',
                  session_close_at='2026-09-29T16:00:00-04:00', price_basis='regular_close',
                  currency='USD', close=102.0, previous_close=100.0, change_pct=2.0, source_id='S1')
    pages = []
    for i, layout in enumerate(summarize.LAYOUTS):
        body = (f'{i+1}번째 검증용 카드입니다. 실제 회사나 주가를 설명하는 자료가 아니며 외부 게시를 금지합니다. '
                '원고와 데이터가 한 파일에서 전달되는지 검사합니다.')
        if i == 0:
            body = '이 카드는 자동화 검증에만 사용하는 가상 자료입니다. 실제 종목 분석이나 투자 판단의 근거가 아닙니다.'
        pages.append(dict(layout=layout, title=f'{i+1}장 테스트 전용 자료입니다', body=body,
                          takeaway='검증용 가상 자료이므로 실제 투자 정보로 사용하거나 게시하지 않습니다.',
                          bridge='다음 카드에서도 데이터 연결 상태를 확인합니다.', evidence_ids=[f'E{min(i+1,4)}'],
                          labels=[dict(label='테스트 구분', text='실제 금융 데이터가 아닌 가상 자료입니다.'),
                                  dict(label='게시 제한', text='시험 실행에만 사용하고 게시하지 않습니다.')]))
    pages[5].update(origin='시험용 조건을 확인합니다', branches=[
        dict(label='연결 성공', text='원고와 시세 기준이 서로 일치하는지 확인합니다.', check='일치하더라도 시험 원고는 게시하지 않습니다.'),
        dict(label='연결 실패', text='원고와 시세 기준이 다르면 즉시 중단합니다.', check='값을 추측하거나 외부 API로 대체하지 않습니다.')])
    summary = dict(central_question='검증용 원고와 시세가 같은 기준으로 전달될까요?',
                   thesis='이 문서는 실제 주식 분석이 아닌 소프트웨어 시험 자료입니다. 원고와 데이터가 어긋날 때 작업을 멈추는지 확인합니다.',
                   edition='TEST ONLY', instagram_caption=('시험용 설명이며 실제 투자 정보가 아닙니다. 게시해서는 안 됩니다.\n' * 16),
                   market_basis={k: market[k] for k in ep.BASIS_KEYS}, sources=[copy.deepcopy(source)],
                   evidence_notes=[dict(id=f'E{i}', claim=f'시험 근거 {i}: 실제 사실을 주장하지 않는 검증용 문장입니다.', source_ids=['S1']) for i in range(1,5)],
                   visual_story=pages)
    return dict(schema_version=1, intent='preview', is_test=True,
                created_at='2026-09-29T22:00:00Z', publication_date_kst='2026-09-30',
                market=market, sources=[source], metrics=[], summary=summary)


def fake_renderer(data, summary, folder, slug):
    """Injectable JPEG generator, NOT the production HTML/photo renderer."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in range(1,8):
        image = Image.new('RGB', (1080, 1350), 'white')
        ImageDraw.Draw(image).text((80,80), f'TEST ONLY / NOT FOR PUBLICATION / {n} of 7', fill='black')
        path = folder / f'{slug}-{n}.jpg'; image.save(path, quality=90)
        paths.append(str(path))
    return paths


def build_test_packet(folder, packet=None):
    return build.build_packet(packet or sample_packet(), out_dir=folder/'out', docs_dir=folder/'docs',
        pages_base=BASE, assets=lambda d:d, renderer=fake_renderer, detail_renderer=lambda *a:None)


def test_valid_packet_and_legacy_summary():
    p = sample_packet(); original = copy.deepcopy(p)
    assert ep.validate_packet(p, now=NOW) is p
    result = summarize.summarize(ep.render_data(p), p['summary'])
    assert len(result['visual_story']) == 7 and 'p7_checks' in result
    assert p == original and p['sources'][0]['url'] in result['instagram_caption']


@pytest.mark.parametrize('path,value', [
    (('market','close'), 101.0), (('market','previous_close'), 0), (('market','change_pct'), 8.0),
    (('market','close'), True), (('market','close'), float('nan')), (('market','currency'), 'KRW'),
    (('market','price_basis'), 'after_hours'), (('market','source_id'), 'MISSING'),
    (('market','session_date'), '2026-09-28'), (('summary','market_basis','close'), 999),
    (('summary','sources',0,'title'), 'changed source title'),
    (('sources',0,'url'), 'https://127.0.0.1/private'),
    (('sources',0,'url'), 'https://example.com/?access_token=forbidden'),
    (('summary','visual_story',0,'evidence_ids'), ['MISSING']),
    (('summary','visual_story',0,'title'), 'x'),
    (('created_at',), '2026-10-01T22:00:00Z'),
    (('publication_date_kst',), '2026-09-29'),
])
def test_invalid_packet_rejected(path, value):
    p=sample_packet(); target=p
    for key in path[:-1]: target=target[key]
    target[path[-1]]=value
    with pytest.raises(ValueError): ep.validate_packet(p, now=NOW)


def test_no_missing_draft_fallback():
    with pytest.raises(summarize.SummaryGenerationError): summarize.summarize({})


def test_seven_cards_required():
    p=sample_packet(); p['summary']['visual_story'].pop()
    with pytest.raises(ValueError): ep.validate_packet(p, now=NOW)


def test_credential_fields_rejected():
    p=sample_packet(); p['access_token']='fake-not-a-secret'
    with pytest.raises(ValueError): ep.validate_packet(p, now=NOW)


def test_duplicate_json_keys_rejected(tmp_path):
    f=tmp_path/'bad.json'; f.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError): ep.load_packet(f)


def test_live_age_and_intent():
    p=sample_packet()
    with pytest.raises(ValueError): ep.validate_packet(p, live=True, now=NOW)
    p['intent']='publish'
    with pytest.raises(ValueError): ep.validate_packet(p, live=True, now=NOW)
    p['is_test']=False
    assert ep.validate_packet(p, live=True, now=NOW)
    with pytest.raises(ValueError): ep.validate_packet(p, live=True, now=NOW+timedelta(days=2))


def test_chart_values_must_match_metrics():
    p=sample_packet(); p['metrics']=[dict(id=f'M{i}',value=i*10,unit='TEST units',period=f'TEST {i}',basis='fictional',source_id='S1') for i in (1,2)]
    chart=dict(source='S1 TEST ONLY',note='가상 수치로만 구성한 시험용 비교입니다.',unit='TEST units',
               rows=[dict(metric_id=f'M{i}',value=i*10,label=f'TEST {i}',display=str(i*10)) for i in (1,2)])
    p['summary']['visual_story'][3]['chart']=chart
    ep.validate_packet(p, now=NOW)
    chart['rows'][0]['value']=99
    with pytest.raises(ValueError): ep.validate_packet(p, now=NOW)


def test_build_seven_jpegs_and_offline_dry_run(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session, 'request', Mock(side_effect=AssertionError('NO NETWORK permitted')))
    monkeypatch.setenv('PAGES_BASE_URL', BASE)
    p=sample_packet(); before=copy.deepcopy(p)
    state=build_test_packet(tmp_path,p)
    assert p==before and state['packet_sha256']==ep.digest(p)
    assert len(list((tmp_path/'docs/cards').glob('*.jpg')))==7
    assert publish.main(['--dry-run','--out',str(tmp_path/'out')])==0


def test_no_input_clears_stale_output(tmp_path):
    out=tmp_path/'out'; out.mkdir(); (out/'state.json').write_text('{}')
    assert build.main(['--input',str(tmp_path/'absent.json'),'--out',str(out)])==0
    assert not (out/'state.json').exists() and (out/'skip').exists()


def test_photo_stage_cannot_mutate_prices(tmp_path):
    def mutate(d): d['focus']['last']=999; return d
    with pytest.raises(ValueError):
        build.build_packet(sample_packet(),out_dir=tmp_path, assets=mutate, renderer=fake_renderer, detail_renderer=lambda *a:None)
    assert not (tmp_path/'state.json').exists()


def test_incomplete_deck_cannot_write_state(tmp_path):
    with pytest.raises(ValueError):
        build.build_packet(sample_packet(),out_dir=tmp_path,assets=lambda d:d,renderer=lambda *a:[],detail_renderer=lambda *a:None)
    assert not (tmp_path/'state.json').exists()


@pytest.mark.parametrize('field,value', [('instagram_caption','tampered'),('packet_sha256','0'*64),('instagram_image_urls',['https://example.com/wrong.jpg'])])
def test_state_tamper_rejected(tmp_path,field,value):
    p=sample_packet(); state=build_test_packet(tmp_path,p); state[field]=value
    with pytest.raises(ValueError): publish.validate_state(state,p,BASE)


class Response:
    def __init__(self,status,payload): self.status_code=status; self.payload=payload
    def json(self): return self.payload


class FakeGitHub:
    """Models create-if-absent and content-SHA compare-and-swap."""
    def __init__(self): self.headers={}; self.files={}; self.events=[]; self.fail_complete=False
    def get(self,url,**kw):
        item=self.files.get(url)
        return Response(404,{}) if item is None else Response(200,dict(content=item[0],sha=item[1]))
    def put(self,url,json,**kw):
        self.events.append('write')
        old=self.files.get(url)
        if old and json.get('sha')!=old[1]: return Response(409,{})
        if not old and 'sha' in json: return Response(409,{})
        if old and self.fail_complete: return Response(500,{})
        sha=hashlib.sha256(json['content'].encode()).hexdigest()
        self.files[url]=(json['content'],sha)
        return Response(200 if old else 201,dict(content=dict(sha=sha)))


def journal(session): return pj.GitHubJournal('owner/repo','FAKE-TEST-TOKEN',session=session)


def test_durable_reservation_precedes_send_and_blocks_duplicate():
    session=FakeGitHub(); j=journal(session); key=ep.publication_key(sample_packet()); sent=[]
    def send():
        assert j.read(key)[0]['status']=='reserved'
        sent.append(1); return 'TEST-MEDIA-ID'
    assert pj.publish_once(j,key,'a'*64,send)['status']=='published'
    pj.publish_once(j,key,'b'*64,send)
    assert len(sent)==1 and j.read(key)[0]['status']=='published'


def test_changed_ticker_does_not_bypass_session_dedup():
    a=sample_packet(); b=copy.deepcopy(a); b['market']['ticker']='OTHER'
    assert ep.publication_key(a)==ep.publication_key(b)


def test_ambiguous_send_is_not_retried():
    s=FakeGitHub(); j=journal(s); send=Mock(side_effect=TimeoutError('synthetic timeout'))
    with pytest.raises(TimeoutError): pj.publish_once(j,'us-stock-2026-09-29','a'*64,send)
    with pytest.raises(pj.JournalError): pj.publish_once(j,'us-stock-2026-09-29','a'*64,send)
    assert send.call_count==1


def test_journal_completion_failure_is_not_retried():
    s=FakeGitHub(); s.fail_complete=True; j=journal(s); send=Mock(return_value='TEST-MEDIA-ID')
    with pytest.raises(pj.JournalError): pj.publish_once(j,'us-stock-2026-09-29','a'*64,send)
    with pytest.raises(pj.JournalError): pj.publish_once(j,'us-stock-2026-09-29','a'*64,send)
    assert send.call_count==1


def test_reservation_conflict_never_sends():
    s=FakeGitHub(); s.put=Mock(return_value=Response(409,{})); send=Mock()
    with pytest.raises(pj.JournalError): pj.publish_once(journal(s),'us-stock-2026-09-29','a'*64,send)
    send.assert_not_called()


def test_http_200_stale_image_rejected():
    state={'instagram_image_urls':['https://example.com/test.jpg'], 'image_sha256':[hashlib.sha256(b'correct').hexdigest()]}
    s=SimpleNamespace(get=Mock(return_value=SimpleNamespace(status_code=200,headers={'Content-Type':'image/jpeg'},content=b'old')))
    with pytest.raises(RuntimeError): publish.verify_public_images(state,session=s,attempts=1,delay=0)
    s.get.return_value.content=b'correct'
    publish.verify_public_images(state,session=s,attempts=1,delay=0)


def test_paid_ai_dependencies_absent_from_execution_modules():
    import ast
    for name in ('build','summarize','editorial_packet','publish','publication_journal'):
        tree=ast.parse((Path(__file__).parents[1]/'src'/f'{name}.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): assert all(a.name.split('.')[0] not in ('anthropic','openai') for a in node.names)
            if isinstance(node,ast.ImportFrom): assert (node.module or '').split('.')[0] not in ('anthropic','openai')


def test_empty_reservation_acknowledgement_never_sends():
    s=FakeGitHub(); s.put=Mock(return_value=Response(201,{'content':{'sha':None}})); send=Mock()
    with pytest.raises(pj.JournalError): pj.publish_once(journal(s),'us-stock-2026-09-29','a'*64,send)
    send.assert_not_called()


def test_wrong_image_dimensions_rejected(tmp_path):
    def bad_renderer(data, summary, folder, slug):
        paths=fake_renderer(data,summary,folder,slug)
        Image.new('RGB',(100,100)).save(paths[0])
        return paths
    with pytest.raises(ValueError):
        build.build_packet(sample_packet(),out_dir=tmp_path/'out', docs_dir=tmp_path/'docs',
                           assets=lambda d:d, renderer=bad_renderer, detail_renderer=lambda *a:None)
    assert not (tmp_path/'out/state.json').exists()
