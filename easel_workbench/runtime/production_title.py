"""Read a version's explicit deliverable title without loading its caption/body."""
import json
import pathlib


def from_artifacts(rows, root, format='poster'):
    root = pathlib.Path(root).resolve()
    names = ('文章交付.json', '标题与配文.txt', '视频交付.json') if format == 'article' else ('标题与配文.txt', '视频交付.json', '文章交付.json')
    for name in names:
        matches = [row for row in rows if row['name'] == name]
        if len(matches) != 1:
            continue
        row = matches[0]
        path = pathlib.Path(row['path']).resolve()
        try:
            if not path.is_relative_to(root) or not path.is_file():
                continue
            if name.endswith('.txt'):
                if row['mime'].split(';')[0] != 'text/plain' or not 0 < path.stat().st_size <= 200_000:
                    continue
                # At most 500 Unicode characters, a UTF-8 BOM and the newline.
                with path.open('rb') as stream:
                    title = stream.readline(2008).decode('utf-8-sig').strip()
            else:
                if not 0 < path.stat().st_size <= 128_000:
                    continue
                manifest = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
                    continue
                title = manifest.get('title')
            if isinstance(title, str):
                title = title.strip()
                if 0 < len(title) <= 500 and not any(ord(char) < 32 for char in title):
                    return title
        except (OSError, UnicodeError, ValueError):
            continue
    return None
