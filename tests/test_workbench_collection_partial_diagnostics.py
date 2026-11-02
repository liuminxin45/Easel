"""Partial delivery keeps exact inserted counters and safe source coverage."""
import json
from easel_workbench.integrations.collection import builtin


def test_late_subsource_failure_keeps_inserted_results_and_safe_coverage(tmp_path,monkeypatch):
    def fail(source,folder,root,report,force):
        (folder/'coverage.json').write_text(json.dumps({'errors':[{'source':'36kr-quick','error':'private provider response with credential'}]}),encoding='utf-8')
        report('persisting',{'fetched':30,'selected':4,'inserted':4})
        raise RuntimeError('private raw error must not reach the UI')
    monkeypatch.setattr(builtin,'editorial_with_recovery',fail)
    value=builtin.run_source('8a49eef93fe5',tmp_path/'task',root=tmp_path)
    assert value['status']=='partial' and value['inserted']==4 and value['selected']==4
    assert any('36kr-quick' in text for text in value['warnings'])
    assert 'private' not in json.dumps(value)
    assert json.loads((tmp_path/'task/failure.json').read_text(encoding='utf-8'))==value
