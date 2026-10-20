"""Synthetic 3/5/7 layout QA only. Never writes a production inbox or publishes."""
import hashlib
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_packet_pipeline import sample_packet
from editorial_render import render_cards, render_detail_page
import config as cfg

root=Path(__file__).resolve().parents[1]
cfg.OUT_DIR='qa-editorial-out';cfg.DOCS_DIR='qa/editorial'
for kind in ('breaking','market','stock'):
    packet=sample_packet() if kind=='stock' else json.loads((root/f'automation/examples/{kind}-preview.json').read_text())
    packet['intent']='preview';packet['is_test']=True
    summary=packet['summary'];summary['design']='editorial-v2'
    for n,story in enumerate(summary['visual_story']):
        # Geometric test patterns are not editorial artwork or financial charts.
        image=Image.new('RGB',(1000,700),'#F5F2EA' if n%2==0 else '#17191B')
        draw=ImageDraw.Draw(image);draw.rectangle((80+n*25,80,800,600),outline='#3157ED',width=20)
        import io
        out=io.BytesIO();image.save(out,format='PNG');raw=out.getvalue();sha=hashlib.sha256(raw).hexdigest()
        path=f'automation/visual_assets/{sha}.png';dest=root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        story['visual']=dict(path=path,sha256=sha,kind='concept',tone='light' if n%2==0 else 'dark',alt='레이아웃 테스트 전용 기하 도형',prompt='Synthetic geometric pattern for renderer regression; never publish this fixture.')
        story['title']=f'검수 전용 {n+1}번째\n실제 게시 금지'
        story['body']='이 카드는 화면 검증을 위한 가상 자료입니다. 실제 사건이나 투자 정보로 게시하지 않습니다.'
        if kind=='stock':
            story['takeaway']='검증한 원고와 그림이 같은 화면에 정확히 놓이는지 확인합니다.'
            story['bridge']='다음 장에서도 실제로 표시되는 내용을 확인합니다.'
            story['labels']=[dict(label='검증 내용',text='원문과 숫자가 정확히 유지됩니다.'),dict(label='검증 목적',text='본문과 하단 문구가 겹치지 않습니다.')]
            if story.get('branches'):
                story['labels']=[]
                story['branches']=[dict(label='첫 번째 조건',text='검수 전용 조건 설명입니다.',check='다음 확인 기준도 함께 남깁니다.'),dict(label='두 번째 조건',text='별도 조건의 설명입니다.',check='다른 확인 기준도 함께 남깁니다.')]
        else:
            story['items']=[dict(label='확인된 내용',text='숫자와 출처의 연결을 보존합니다.',type='fact'),dict(label='다음 기준',text='실제 게시 전 전체 이미지를 확인합니다.',type='watch')]
            if story['layout'] in ('headline','calendar') and kind=='market':story['items']=[]
    render_cards(packet,summary,f'qa/editorial/{kind}',kind)
