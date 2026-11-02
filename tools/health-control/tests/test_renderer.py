import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from easel_health_control.renderer import stage_runtime,render


def installation(tmp_path,monkeypatch):
    base=tmp_path/'base';base.mkdir();(base/'python.exe').write_bytes(b'base-not-venv')
    (base/'python314.dll').write_bytes(b'dll');(base/'Lib').mkdir();(base/'Lib/os.py').write_text('stdlib')
    (base/'DLLs').mkdir();(base/'DLLs/module.pyd').write_bytes(b'pyd')
    venv=tmp_path/'venv';(venv/'Scripts').mkdir(parents=True);exe=venv/'Scripts/python.exe';exe.write_bytes(b'venv-redirector')
    (venv/'pyvenv.cfg').write_text('home = '+str(base)+'\n')
    (venv/'Lib/site-packages/PIL').mkdir(parents=True);(venv/'Lib/site-packages/PIL/Image.py').write_text('PIL')
    (base/'Lib/site-packages').mkdir();(base/'Lib/site-packages/private-config.py').write_text('not copied')
    fonts=tmp_path/'windows/Fonts';fonts.mkdir(parents=True);(fonts/'msyh.ttc').write_bytes(b'font')
    monkeypatch.setenv('WINDIR',str(tmp_path/'windows'))
    return exe


def test_staging_copies_base_runtime_not_venv_or_unrelated_packages(tmp_path,monkeypatch):
    exe=installation(tmp_path,monkeypatch);workspace=tmp_path/'project'
    result=stage_runtime(exe,workspace);target=Path(result['python']).parent
    assert Path(result['python']).read_bytes()==b'base-not-venv'
    assert not (target/'pyvenv.cfg').exists()
    assert not (target/'Lib/site-packages/private-config.py').exists()
    assert (target/'Lib/site-packages/PIL/Image.py').is_file()
    assert (target/'python314._pth').read_text().splitlines()==['.','Lib','DLLs','Lib/site-packages','import site']
    assert stage_runtime(exe,workspace)['files']==result['files']


def test_changed_staged_runtime_fails_closed(tmp_path,monkeypatch):
    exe=installation(tmp_path,monkeypatch);result=stage_runtime(exe,tmp_path/'project')
    Path(result['python']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='runtime_changed'):stage_runtime(exe,tmp_path/'project')


@pytest.mark.skipif(sys.platform!='win32',reason='Uses the installed Windows CJK font, no network download')
def test_renderer_decodes_with_nonce_and_creates_no_model_receipt(tmp_path):
    from PIL import Image
    output=tmp_path/'outputs/poster.png'
    result=render({'operation_id':'probe-op','title':'严格沙盒测试','body':'真实工具生成的验收图片，不冒称模型执行。','source_url':'https://example.org/source'},output,tmp_path)
    with Image.open(output) as image:
        image.load();assert image.size==(960,1280)
        assert image.info['easel_canary_operation']=='probe-op'
    assert result['sha256'] and not (tmp_path/'receipt.json').exists()
    with pytest.raises(FileExistsError):render({'operation_id':'probe-op','title':'原文件保留','body':'不能覆盖原件'},output,tmp_path)


def test_renderer_rejects_output_outside_workspace(tmp_path):
    with pytest.raises(ValueError,match='outside'):render({'operation_id':'probe-op','title':'title','body':'body'},tmp_path.parent/'outside.png',tmp_path)


def test_renderer_requires_operation_identity(tmp_path):
    with pytest.raises(ValueError,match='operation_missing'):render({'title':'title','body':'body'},tmp_path/'outputs/image.png',tmp_path)
