"""Validate Easel source protocols and immutable Python assets."""
import hashlib,os,tempfile
from pathlib import Path
from easel.trends.sources import _source,display_label

class SourceAssets:
    def __init__(self,root):self.root=Path(root).resolve()

    def prepare(self, identifier, value):
        row = {'id': identifier, 'label': value.get('label'), 'type': value.get('type'),
               'refresh_seconds': value.get('refresh_seconds', 300), 'default': True}
        if row['type'] == 'python':
            from easel.trends.management import _prepare_script
            directory = self.root/'data/collection/source-assets'
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='validate-', dir=directory) as temporary:
                checked = _prepare_script(row, value, Path(temporary), dict(os.environ))
                raw = checked.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                target = directory/(digest+'.py')
                try:
                    with target.open('xb') as output:
                        output.write(raw)
                except FileExistsError:
                    if target.read_bytes() != raw:
                        raise ValueError('来源脚本资产 SHA 不匹配')
                row['script'] = target.relative_to(self.root).as_posix()
                row['script_sha256'] = digest
                row.pop('uploaded_script', None)
        else:
            row.update(url=value.get('url'), headers=value.get('headers', {}))
            if row['type'] == 'http':
                row['method']=value.get('method','GET')
                if row['method']=='POST':row['body']=value.get('body',{})
        source = _source(row, self.root)
        return {**row, 'label': display_label(source.label), 'name': display_label(source.label),
                'feed': identifier, 'enabled': True, 'builtin': False}

    def source(self, snapshot):
        row = dict(snapshot)
        if row.get('builtin'):
            raise ValueError('内置来源保留专用采集流程')
        if row['type'] == 'python':
            path = (self.root/row['script']).resolve()
            if not path.is_relative_to(self.root/'data/collection/source-assets') or path.is_symlink():
                raise ValueError('来源脚本路径无效')
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['script_sha256']:
                raise ValueError('来源脚本 SHA 不匹配')
        return _source(row, self.root)
