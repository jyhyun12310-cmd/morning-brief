import copy
import hashlib
import io
from pathlib import Path
import pytest
from PIL import Image
from editorial_packet import PacketError, validate_packet
from editorial_visuals import validate_visuals, asset_data_uri
from editorial_render import card_context
from test_packet_pipeline import sample_packet, NOW

def visual(n=0):
    sha=hashlib.sha256(str(n).encode()).hexdigest()
    return dict(path=f'automation/visual_assets/{sha}.png',sha256=sha,kind='concept',tone='light',
                alt='실제 현장이 아닌 시험용 개념 이미지입니다',prompt='Synthetic test illustration; not a photograph or financial evidence.')

def styled():
    p=sample_packet();p['summary']['design']='editorial-v2'
    for n,page in enumerate(p['summary']['visual_story']): page['visual']=visual(n)
    return p

@pytest.mark.parametrize('issue',['duplicate','missing','escape','remote','tone','kind','accent','design'])
def test_invalid_visual_manifest_rejected(issue):
    p=styled();s=p['summary'];v=s['visual_story'][0]['visual']
    if issue=='duplicate': s['visual_story'][1]['visual']=copy.deepcopy(v)
    if issue=='missing': del s['visual_story'][0]['visual']
    if issue=='escape': v['path']='../private.png'
    if issue=='remote': v['path']='https://example.com/image.png'
    if issue=='tone': v['tone']='invisible'
    if issue=='kind': v['kind']='svg'
    if issue=='accent': s['visual_story'][0]['accent']='not in title'
    if issue=='design': del s['design']
    with pytest.raises(PacketError): validate_packet(p,now=NOW)

def test_frozen_visual_rejects_changed_bytes_and_symlink(tmp_path):
    stream=io.BytesIO();Image.new('RGB',(800,800),'blue').save(stream,format='PNG')
    data=stream.getvalue();v=visual();v['sha256']=hashlib.sha256(data).hexdigest()
    v['path']=f'automation/visual_assets/{v["sha256"]}.png'
    path=tmp_path/v['path'];path.parent.mkdir(parents=True);path.write_bytes(data)
    assert asset_data_uri(v,tmp_path).startswith('data:image/png;base64,')
    path.write_bytes(data+b'changed')
    with pytest.raises(PacketError,match='differ'): asset_data_uri(v,tmp_path)
    path.unlink();outside=tmp_path/'outside.png';outside.write_bytes(data);path.symlink_to(outside)
    with pytest.raises(PacketError,match='symlink'): asset_data_uri(v,tmp_path)

def test_all_stock_comparison_and_condition_evidence_is_retained():
    p=styled()
    page=p['summary']['visual_story'][5]
    rows=card_context(p,page)['rows']
    for branch in page['branches']:
        assert any(branch['text'] in r['text'] and branch['check'] in r['text'] for r in rows)
    chart={'rows':[{'label':'기준','value':-1,'display':'−1달러'},{'label':'비교','value':2,'display':'2달러'}]}
    assert card_context(p,dict(title='비교',chart=chart))['rows']==[{'label':'기준','text':'−1달러'},{'label':'비교','text':'2달러'}]

def test_visual_metadata_survives_exact_preview_promotion(tmp_path):
    # Existing promotion suite tests byte identity and altered hashes. The new
    # manifest must not introduce an artwork fetch during that path.
    from editorial_packet import digest
    p=styled();validate_packet(p,now=NOW)
    changed=copy.deepcopy(p);changed['summary']['visual_story'][0]['visual']['alt']='다른 의미로 바뀐 이미지 설명입니다'
    assert digest(p)!=digest(changed)

@pytest.mark.parametrize('kind',['market','breaking'])
def test_news_schema_with_visuals_preserves_existing_contract(kind):
    import json
    p=json.loads((Path(__file__).resolve().parents[1]/f'automation/examples/{kind}-preview.json').read_text())
    p['summary']['design']='editorial-v2'
    for n,page in enumerate(p['summary']['visual_story']):page['visual']=visual(n)
    validate_packet(p)
    for page in p['summary']['visual_story']:
        rows=card_context(p,page)['rows']
        assert len(rows)>=len(page.get('items',[]))
