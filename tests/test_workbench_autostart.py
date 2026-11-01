"""Exercise the console-less launcher without starting production roles."""
from pathlib import Path
import runpy

import pytest
from easel_workbench import supervisor


def test_launcher_import_does_not_start_manager(monkeypatch):
    monkeypatch.setattr(supervisor, 'main', lambda root: pytest.fail('Unexpected startup'))
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'launcher.pyw'), run_name='fixture')
    assert callable(module['launch'])


def test_manager_failure_preserves_trace_and_nonzero_exit(tmp_path, monkeypatch):
    def fail(root):
        assert root == tmp_path
        raise RuntimeError('selection changed')
    monkeypatch.setattr(supervisor, 'main', fail)
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'launcher.pyw'), run_name='fixture')
    with pytest.raises(RuntimeError, match='selection changed'):
        module['launch'](tmp_path)
    log = (tmp_path / '.local/workbench-deployment/manager.log').read_text(encoding='utf-8')
    assert 'manager=' in log and 'Traceback' in log and 'RuntimeError: selection changed' in log


def test_successful_duplicate_exit_does_not_log_failure(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(supervisor, 'main', calls.append)
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'launcher.pyw'), run_name='fixture')
    module['launch'](tmp_path)
    assert calls == [tmp_path]
    assert not (tmp_path / '.local').exists()
