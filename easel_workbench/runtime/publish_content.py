"""Read publish copy only from already captured deliverables, never source folders."""
import pathlib


def from_artifacts(rows, root):
    candidates = [r for r in rows if r['name'] == '标题与配文.txt' and r['mime'].split(';')[0] == 'text/plain']
    if len(candidates) != 1:
        return None
    artifact = candidates[0]
    path = pathlib.Path(artifact['path']).resolve()
    try:
        if not path.is_relative_to(pathlib.Path(root).resolve()) or path.stat().st_size > 200000:
            return None
        lines = path.read_text(encoding='utf-8-sig').strip().splitlines()
        title = lines[0].strip() if lines else ''
        caption = '\n'.join(lines[1:]).strip()
        if not title or len(title) > 500 or not caption:
            return None
        return {'title': title, 'caption': caption, 'source_artifact_id': artifact['id']}
    except (OSError, UnicodeError):
        return None
