"""Local article review: prepare HTML, autosave notes, archive and advance."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[5]
ASSETS = Path(__file__).resolve().parent
LIMIT = 1_000_000

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.review-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def scoped(path, parent):
    path = Path(path).resolve()
    if not path.is_relative_to(parent.resolve()):
        raise ValueError('Path must remain inside its article directory')
    return path

@contextlib.contextmanager
def file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            deadline = time.monotonic() + 10
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Review files are busy; retry without clearing notes')
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

def metadata(document):
    found = re.search(r'<script id="neo-review-config" type="application/json">(.*?)</script>', document, re.S)
    if not found:
        raise ValueError('HTML has not been prepared for review')
    return json.loads(found.group(1))

def prepare(source, output, article_dir, version):
    article_dir = Path(article_dir).resolve()
    source, output = scoped(source, article_dir), scoped(output, article_dir)
    if output.exists():
        raise ValueError('Output exists; create a new version')
    document = source.read_text(encoding='utf-8-sig')
    if 'id="neo-review-config"' in document:
        raise ValueError('Prepare a clean article HTML, not a previous review shell')
    if 'id="article"' not in document or '<h1' not in document:
        raise ValueError('Expected article copy area and preview heading')
    document = re.sub(r'<h1(\s[^>]*)?>', lambda m: '<h1' + (m.group(1) or '') + ' data-review-scope="title">', document, count=1)
    identity = article_dir.relative_to(ROOT).as_posix() if article_dir.is_relative_to(ROOT) else str(article_dir)
    config = {'schema': 1, 'article_id': digest(identity.encode())[:20],
              'version': version, 'content_hash': digest(source.read_bytes())}
    encoded = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c')
    css = (ASSETS / 'review.css').read_text(encoding='utf-8')
    script = (ASSETS / 'review.js').read_text(encoding='utf-8')
    document = document.replace('</head>', '<style id="neo-review-css">' + css + '</style></head>', 1)
    extra = '<script id="neo-review-config" type="application/json">' + encoded + '</script><script id="neo-review-js">' + script + '</script>'
    document = document.replace('</body>', extra + '</body>', 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding='utf-8')
    return config

class Conflict(Exception):
    pass

class Store:
    def __init__(self, article_dir, runtime=None):
        self.root = Path(article_dir).resolve()
        self.folder = self.root / '批注'
        self.path = self.folder / '当前批注.json'
        runtime = Path(runtime) if runtime else ROOT / '.runtime' / '文章批注'
        self.lock = runtime / (digest(str(self.root).encode())[:20] + '.lock')

    def load(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def preserve_conflict(self, request):
        with file_lock(self.lock):
            target = self.folder / ('未合并意见-' + uuid.uuid4().hex + '.json')
            atomic_json(target, {'at': now(), 'reason': 'stale_review', 'request': request,
                                 'active_version': self.load()['version']})
            return target.relative_to(self.root).as_posix()

    def new_state(self, html, version, markdown=None):
        html = scoped(html, self.root)
        meta = metadata(html.read_text(encoding='utf-8'))
        if meta['version'] != version:
            raise ValueError('Version does not match prepared HTML')
        result = {'schema': 1, 'article_id': meta['article_id'], 'version': version,
                  'generation': uuid.uuid4().hex, 'content_hash': meta['content_hash'],
                  'source_html': html.relative_to(self.root).as_posix(),
                  'source_sha256': digest(html.read_bytes()), 'source_markdown': None,
                  'edit_seq': 0, 'updated_at': now(), 'annotations': []}
        if markdown:
            md = scoped(markdown, self.root)
            result['source_markdown'] = md.relative_to(self.root).as_posix()
            result['markdown_sha256'] = digest(md.read_bytes())
        return result

    def initialize(self, html, version, markdown=None):
        with file_lock(self.lock):
            if self.path.exists():
                current = self.load()
                if current['version'] != version or current['source_html'] != scoped(html, self.root).relative_to(self.root).as_posix():
                    raise Conflict('Active review exists. Archive and advance explicitly; never reset on startup.')
                return current
            current = self.new_state(html, version, markdown)
            atomic_json(self.path, current)
            return current

    def update(self, request):
        if not isinstance(request, dict):
            raise ValueError('Expected an annotation object')
        notes = request.get('annotations')
        if not isinstance(notes, list) or len(notes) > 300:
            raise ValueError('Invalid annotation list')
        seen = set()
        for note in notes:
            if not isinstance(note, dict) or not isinstance(note.get('id'), str) or note['id'] in seen:
                raise ValueError('Invalid or duplicate annotation ID')
            seen.add(note['id'])
            anchor = note.get('anchor', {})
            if not isinstance(anchor, dict):
                raise ValueError('Invalid selection anchor')
            if anchor.get('scope') not in ('title', 'article'):
                raise ValueError('Invalid annotation scope')
            if not all(isinstance(anchor.get(k), int) and not isinstance(anchor[k], bool) for k in ('start', 'end')) or not 0 <= anchor['start'] < anchor['end']:
                raise ValueError('Invalid selection offsets')
            if not isinstance(anchor.get('quote'), str) or not anchor['quote'].strip() or len(anchor['quote']) > 20000:
                raise ValueError('Invalid selected text')
            if not isinstance(note.get('comment'), str) or len(note['comment']) > 20000:
                raise ValueError('Invalid annotation comment')
            if not all(isinstance(anchor.get(k, ''), str) and len(anchor.get(k, '')) <= 100 for k in ('prefix', 'suffix')):
                raise ValueError('Invalid selection context')
        with file_lock(self.lock):
            state = self.load()
            if any(request.get(k) != state[k] for k in ('generation', 'version', 'content_hash', 'edit_seq')):
                raise Conflict('Review changed in another tab or a new version is active. Reload before editing.')
            if state['annotations'] == notes:
                return state
            before = state['annotations']
            state['annotations'] = notes
            state['edit_seq'] += 1
            state['updated_at'] = now()
            event = {'edit_seq': state['edit_seq'], 'at': state['updated_at'], 'before': before, 'after': notes}
            self.folder.mkdir(parents=True, exist_ok=True)
            journal = self.folder / ('事件-' + state['generation'] + '.jsonl')
            with journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            atomic_json(self.path, state)
            return state

    def refresh_ui(self, output):
        """Replace only the review assets; retain draft identity and every note."""
        with file_lock(self.lock):
            state = self.load()
            source = scoped(self.root / state['source_html'], self.root)
            original = source.read_bytes()
            if digest(original) != state['source_sha256']:
                raise Conflict('Original HTML changed; reconcile before refreshing the interface')
            output = scoped(output, self.root)
            if output.exists():
                raise ValueError('Output exists; retain it and choose a new interface revision')
            document = original.decode('utf-8')
            for tag, identity, asset in [('style', 'neo-review-css', 'review.css'), ('script', 'neo-review-js', 'review.js')]:
                pattern = r'(<'+tag+r' id="'+identity+r'">).*?(</'+tag+r'>)'
                document, count = re.subn(pattern, lambda match: match.group(1) + (ASSETS / asset).read_text(encoding='utf-8') + match.group(2), document, flags=re.S)
                if count != 1:
                    raise ValueError('Expected exactly one review asset: ' + identity)
            if metadata(document) != metadata(original.decode('utf-8')):
                raise ValueError('Review identity must not change during interface repair')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(document.encode('utf-8'))
            updated = dict(state)
            updated['source_html'] = output.relative_to(self.root).as_posix()
            updated['source_sha256'] = digest(output.read_bytes())
            updated['interface_revision'] = state.get('interface_revision', 0) + 1
            record = self.folder / ('界面修复-' + uuid.uuid4().hex + '.json')
            atomic_json(record, {'at': now(), 'reason': 'review_interface_only', 'before': state, 'after': updated})
            atomic_json(self.path, updated)
            return updated

    def advance(self, html, version, changes, expected_seq, markdown=None):
        with file_lock(self.lock):
            state = self.load()
            if state['edit_seq'] != expected_seq:
                raise Conflict('New comments arrived. Read and process them before clearing.')
            if version == state['version']:
                raise ValueError('A new review version is required')
            changes = scoped(changes, self.root)
            if not changes.is_file() or not changes.read_text(encoding='utf-8-sig').strip():
                raise ValueError('A saved revision/feedback record is required')
            new_state = self.new_state(html, version, markdown)
            source = scoped(self.root / state['source_html'], self.root)
            if digest(source.read_bytes()) != state['source_sha256']:
                raise Conflict('Original HTML changed. Preserve and reconcile before advancing.')
            if state.get('source_markdown'):
                md = scoped(self.root / state['source_markdown'], self.root)
                if digest(md.read_bytes()) != state['markdown_sha256']:
                    raise Conflict('Original Markdown changed; archive the correct source first')
            archive = self.folder / '轮次' / (state['generation'] + '-r' + str(state['edit_seq']))
            if not archive.exists():
                archive.parent.mkdir(parents=True, exist_ok=True)
                temp = Path(tempfile.mkdtemp(prefix='.archive-', dir=archive.parent))
                try:
                    atomic_json(temp / '批注.json', state)
                    shutil.copy2(source, temp / '原稿.html')
                    shutil.copy2(changes, temp / '修改记录.md')
                    if state.get('source_markdown'):
                        shutil.copy2(self.root / state['source_markdown'], temp / '原稿.md')
                    journal = self.folder / ('事件-' + state['generation'] + '.jsonl')
                    if journal.exists():
                        shutil.copy2(journal, temp / '事件.jsonl')
                    manifest = {'old_version': state['version'], 'new_version': version, 'edit_seq': expected_seq,
                                'files': {file.name: digest(file.read_bytes()) for file in temp.iterdir() if file.is_file()}}
                    atomic_json(temp / '归档清单.json', manifest)
                    scoped(temp, archive.parent).rename(scoped(archive, self.folder))
                finally:
                    if temp.exists():
                        shutil.rmtree(scoped(temp, archive.parent))
            else:
                archived = json.loads((archive / '批注.json').read_text(encoding='utf-8'))
                if archived != state:
                    raise Conflict('Archive exists with different content; no notes were cleared')
            new_state['previous_archive'] = archive.relative_to(self.root).as_posix()
            atomic_json(self.path, new_state)
            return new_state

def make_server(store, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, value, kind='application/json; charset=utf-8'):
            data = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, dict) else value
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403, {'error': 'Host not allowed'})
            path = urlsplit(self.path).path
            if path == '/health':
                return self.send(200, {'ok': True, 'article_id': store.load()['article_id']})
            if path == '/api/annotations':
                return self.send(200, store.load())
            if path in ('/', '/review'):
                state = store.load()
                source = scoped(store.root / state['source_html'], store.root)
                data = source.read_bytes()
                if digest(data) != state['source_sha256']:
                    return self.send(409, {'error': 'Article file changed; review source requires reconciliation'})
                return self.send(200, data, 'text/html; charset=utf-8')
            return self.send(404, {'error': 'Not found'})

        def do_PUT(self):
            origin = self.headers.get('Origin')
            valid_origins = (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
            if not self.allowed_host() or origin not in valid_origins or self.headers.get('X-Neo-Review') != '1':
                return self.send(403, {'error': 'Same-origin review request required'})
            if urlsplit(self.path).path != '/api/annotations':
                return self.send(404, {'error': 'Not found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= LIMIT or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid JSON request')
                value = json.loads(self.rfile.read(size))
                return self.send(200, store.update(value))
            except Conflict as exc:
                saved = store.preserve_conflict(value)
                return self.send(409, {'error': str(exc), 'preserved': saved})
            except (ValueError, TypeError, KeyError) as exc:
                return self.send(400, {'error': str(exc)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--article-dir', required=True)
    p.add_argument('--version', required=True)
    p = sub.add_parser('serve')
    p.add_argument('--article-dir', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--version', required=True)
    p.add_argument('--markdown')
    p.add_argument('--port', type=int, default=0)
    p.add_argument('--ready-file')
    p = sub.add_parser('read')
    p.add_argument('--article-dir', required=True)
    p = sub.add_parser('refresh-ui')
    p.add_argument('--article-dir', required=True)
    p.add_argument('--output', required=True)
    p = sub.add_parser('advance')
    p.add_argument('--article-dir', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--version', required=True)
    p.add_argument('--markdown')
    p.add_argument('--changes', required=True)
    p.add_argument('--expected-seq', type=int, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(json.dumps(prepare(args.input, args.output, args.article_dir, args.version), ensure_ascii=False))
        return
    store = Store(args.article_dir)
    if args.command == 'read':
        result = store.load()
        result['unmerged_files'] = [path.relative_to(store.root).as_posix() for path in store.folder.glob('未合并意见-*.json')]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == 'refresh-ui':
        value = store.refresh_ui(args.output)
        print(json.dumps({'version': value['version'], 'source_html': value['source_html'],
                          'interface_revision': value['interface_revision'], 'edit_seq': value['edit_seq'],
                          'annotations_preserved': len(value['annotations'])}, ensure_ascii=False))
    elif args.command == 'advance':
        value = store.advance(args.html, args.version, args.changes, args.expected_seq, args.markdown)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        store.initialize(args.html, args.version, args.markdown)
        server = make_server(store, args.port)
        ready = {'pid': os.getpid(), 'url': f'http://127.0.0.1:{server.server_port}/review', 'article_dir': str(store.root)}
        if args.ready_file:
            atomic_json(Path(args.ready_file), ready)
        print(json.dumps(ready, ensure_ascii=False), flush=True)
        server.serve_forever()

if __name__ == '__main__':
    main()
