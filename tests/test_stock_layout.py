"""Historical layout regression fixtures cannot be used as live manuscripts."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def qa_module():
    spec = importlib.util.spec_from_file_location('stock_layout_qa', ROOT / 'scripts/check_stock_layout.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_historical_xom_fixture_is_valid_but_never_live():
    from editorial_packet import validate_packet
    packet = json.loads((ROOT / 'tests/fixtures/xom-layout.json').read_text())
    assert packet['intent'] == 'preview' and packet['is_test'] is True
    assert 'reviewed_preview' not in packet
    validate_packet(packet)
    live = copy.deepcopy(packet)
    live['intent'] = 'publish'
    with pytest.raises(ValueError):
        validate_packet(live, live=True)


@pytest.mark.parametrize('intent,is_test', [('publish', True), ('preview', False), ('publish', False)])
def test_layout_runner_rejects_production_inputs(tmp_path, monkeypatch, intent, is_test):
    runner = qa_module()
    fixture = tmp_path / 'input.json'
    fixture.write_text(json.dumps({'intent': intent, 'is_test': is_test}))
    monkeypatch.setattr('sys.argv', ['check_stock_layout', str(fixture), '--out', str(tmp_path/'out'), '--docs', str(tmp_path/'docs')])
    calls = []
    monkeypatch.setattr(runner, 'build_packet', lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError, match='non-publishing test previews'):
        runner.main()
    assert not calls
    assert not (tmp_path / 'out').exists()
