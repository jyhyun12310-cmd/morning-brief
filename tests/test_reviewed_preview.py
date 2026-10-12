"""Offline promotion tests; all data and JPEGs are synthetic, never submitted."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from test_packet_pipeline import sample_packet, build_test_packet, NOW, BASE
from editorial_packet import slug_for
from reviewed_preview import promote, verify_run

def prepared(tmp_path):
    p = sample_packet()
    p['is_test'] = False
    source = tmp_path / 'preview'
    state = build_test_packet(source, p)
    slug = slug_for(p)
    (source/'docs'/f'{slug}.html').write_text(f'<img src="cards/{slug}-1.jpg">', encoding='utf-8')
    live = copy.deepcopy(p)
    live['intent'] = 'publish'
    live['reviewed_preview'] = {'run_id': 123, 'image_sha256': state['image_sha256']}
    return source, live, state

def test_exact_jpegs_reused(tmp_path):
    source, p, preview = prepared(tmp_path)
    result = promote(p, source, out_dir=tmp_path/'out', docs_dir=tmp_path/'docs', pages_base=BASE, now=NOW)
    assert result['image_sha256'] == preview['image_sha256']
    for n, h in enumerate(result['image_sha256'], 1):
        assert hashlib.sha256((tmp_path/'docs/cards'/f'{slug_for(p)}-{n}.jpg').read_bytes()).hexdigest() == h
    assert result['intent'] == 'publish'

@pytest.mark.parametrize('change', ['body','time','hash','missing','test','stale'])
def test_changed_or_unsafe_preview_rejected(tmp_path, change):
    source, p, state = prepared(tmp_path)
    now = NOW
    if change == 'body':
        p['summary']['visual_story'][0]['body'] += ' 내용 변경.'
    elif change == 'time':
        p['created_at'] = '2026-09-29T22:01:00Z'
    elif change == 'hash':
        p['reviewed_preview']['image_sha256'][0] = '0'*64
    elif change == 'missing':
        next((source/'docs/cards').glob('*.jpg')).unlink()
    elif change == 'test':
        p['is_test'] = True
    else:
        from datetime import timedelta
        now += timedelta(days=2)
    with pytest.raises(ValueError):
        promote(p, source, out_dir=tmp_path/'out', docs_dir=tmp_path/'docs', pages_base=BASE, now=now)
    assert not (tmp_path/'out/state.json').exists()

def test_failed_foreign_or_wrong_workflow_run_rejected():
    run = dict(id=123,status='completed',conclusion='success',head_branch='main',
               path='.github/workflows/card-packet.yml',event='push',
               head_repository={'full_name':'owner/repo'})
    verify_run(run,'owner/repo','card-packet.yml',123)
    for field, value in [('conclusion','failure'),('head_branch','other'),
                         ('path','.github/workflows/other.yml'),
                         ('head_repository',{'full_name':'other/repo'}),
                         ('event','pull_request'),('id',124)]:
        bad = {**run,field:value}
        with pytest.raises(ValueError):
            verify_run(bad,'owner/repo','card-packet.yml',123)


@pytest.mark.parametrize('kind', ['market', 'breaking'])
def test_production_preview_has_same_card_markup_as_publish(kind):
    """Review is a delivery stage, not a reader-facing test watermark."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    root = Path(__file__).resolve().parents[1]
    packet = json.loads((root/'automation/examples'/f'{kind}-preview.json').read_text())
    packet.update(intent='preview', is_test=False)
    template = Environment(loader=FileSystemLoader(root/'src'),
                           autoescape=select_autoescape()).get_template(f'{kind}_card.html')
    for n, story in enumerate(packet['summary']['visual_story'], 1):
        context = dict(packet=packet, story=story, n=n, fonts={}, quotes=[], events=[],
                       snapshot='10.02 09:09', released='2026-10-02')
        preview = template.render(**context)
        packet['intent'] = 'publish'
        published = template.render(**context)
        assert preview == published
        header = preview.split('</header>', 1)[0]
        assert '디자인 테스트' not in header
        assert '디자인 미리보기' not in header
        packet['intent'] = 'preview'


@pytest.mark.parametrize('intent', ['preview', 'publish'])
def test_breaking_test_fixture_keeps_visible_test_label(intent):
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    root = Path(__file__).resolve().parents[1]
    packet = json.loads((root/'automation/examples/breaking-preview.json').read_text())
    packet.update(intent=intent, is_test=True)
    template = Environment(loader=FileSystemLoader(root/'src'),
                           autoescape=select_autoescape()).get_template('breaking_card.html')
    markup = template.render(packet=packet, story=packet['summary']['visual_story'][0],
                             n=1, fonts={}, snapshot='', released='')
    assert '과거 발표 · 디자인 테스트' in markup
