import json
import base64
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager, closing
from pathlib import Path

from easel_workbench.features.conversations.generated_images import receive, display


class Store:
    def __init__(self, path): self.path = path
    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path)) as c:
            with c: yield c


class GeneratedImagesTest(unittest.TestCase):
    def test_only_exact_completed_turn_image_is_received_and_projected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base/'project'; root.mkdir(); home = base/'codex'; home.mkdir()
            thread = '01a1a56a-798b-7a21-b798-aa2a444b2ec8'; native = '01a1a56d-5bd1-7ca3-a4d2-a9c22bd1359e'
            folder = home/'generated_images'/thread; folder.mkdir(parents=True)
            one = folder/'exec-e7574b18-c142-4718-a2ae-595a59dbbb0b.png'; one.write_bytes(b'\x89PNG\r\n\x1a\nverified')
            other = folder/'exec-1d59000b-7f8d-4a0c-86ba-7dc4c3aa5b5c.png'; other.write_bytes(b'\x89PNG\r\n\x1a\nunverified')
            rollout = home/'sessions'/'rollout.jsonl'; rollout.parent.mkdir()
            def event(path, turn):
                return {'payload':{'type':'item_completed','thread_id':thread,'turn_id':turn,'item':{'kind':'image_gen.generation','status':'completed','id':path.stem,'savedPath':str(path),'result':base64.b64encode(path.read_bytes()).decode()}}}
            rollout.write_text('\n'.join(json.dumps(v) for v in [event(one,native),event(other,thread)]),encoding='utf8')
            with closing(sqlite3.connect(home/'state_5.sqlite')) as c:
                with c:
                    c.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT)'); c.execute('INSERT INTO threads VALUES(?,?)',(thread,str(rollout)))
            store = Store(base/'desk.sqlite')
            with store.connect() as c: c.execute('CREATE TABLE artifacts(id TEXT PRIMARY KEY,task_id TEXT,name TEXT,path TEXT,mime TEXT)')
            turn = {'runtime':'codex','status':'completed','native_id':thread,'native_turn_id':native,'id':'turn','session_id':'session',
                    'output':f'[第一张]({one}) [不属于本回合]({other}) [网页](https://example.com)'}
            self.assertEqual(receive(root,store,turn,home=home),1)
            self.assertEqual(receive(root,store,turn,home=home),1)
            with store.connect() as c:
                rows=c.execute('SELECT source,artifact_id,sha256 FROM easel_generated_image_sources').fetchall()
                artifact=c.execute('SELECT path FROM artifacts').fetchone()[0]
            self.assertEqual(Path(artifact).read_bytes(),one.read_bytes())
            projected=display(turn['output'],{row[0]:row[1] for row in rows})
            self.assertIn('/api/files/'+rows[0][1],projected)
            self.assertIn('不属于本回合（图片暂不可用）',projected)
            self.assertIn('[网页](https://example.com)',projected)
            self.assertEqual(display('[网页](https://example.com/generated_images/a.png)',{}),'[网页](https://example.com/generated_images/a.png)')
            self.assertIn(str(one),turn['output'])
            one.write_bytes(b'\x89PNG\r\n\x1a\nreplaced')
            self.assertEqual(receive(root,store,turn,home=home),0)
            self.assertEqual(Path(artifact).read_bytes(),b'\x89PNG\r\n\x1a\nverified')
            self.assertEqual(receive(root,store,{**turn,'status':'unknown'},home=home),0)


if __name__ == '__main__': unittest.main()
