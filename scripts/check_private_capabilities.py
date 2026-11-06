"""Read-only documentation and change-impact checks for the private Easel fork.

This is a maintenance check, not a runtime capability registry or an approval
engine. A valid ID documents impact; it never grants production permissions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

INDEX = 'docs/workbench/PRIVATE-CAPABILITIES.md'
CARDS = 'docs/workbench/private-capabilities'
LEDGER = 'docs/workbench/shared-source-changes.json'
ROW = re.compile(r'\| \[((?:PC|C|U)-\d+) [^\]]+\]\((private-capabilities/[^)]+)\)')
LINK = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
KINDS = {'official-overlay', 'shared-extraction', 'host-port', 'generic-fix', 'private-policy', 'mixed'}
PRIVATE_ROOTS = ('easel_workbench/', 'web/frontend/src/workbench/', 'tools/health-control/',
                 '.agents/skills/', 'skills/builtin/', 'skills/shared/workbench/')
CODE_SUFFIXES = {'.py', '.pyw', '.ts', '.tsx', '.js', '.mjs', '.cjs', '.css', '.json', '.ps1', '.sh'}
SHARED_INCLUDE = {'easel/', 'web/app.py', 'web/frontend/src/', 'skills/shared/scripts/weixin_mp_stats.py'}
SHARED_EXCLUDE = {'web/frontend/src/workbench/', 'web/frontend/src/assets/workbench/'}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=root, text=True, encoding='utf-8',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def local_links(root: Path, document: Path, text: str, errors: list[str]) -> set[str]:
    found = set()
    for raw in LINK.findall(text):
        raw = raw.strip('<>')
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (document.parent / unquote(parsed.path)).resolve()
        if not target.is_relative_to(root):
            errors.append(f'{document.relative_to(root)}: link escapes repository: {raw}')
        elif not target.exists():
            errors.append(f'{document.relative_to(root)}: broken local link: {raw}')
        else:
            found.add(target.relative_to(root).as_posix())
    return found


def in_scope(path: str, scope: dict) -> bool:
    def matches(prefix):
        return path.startswith(prefix) if prefix.endswith('/') else path == prefix
    return any(matches(p) for p in scope['include']) and not any(matches(p) for p in scope['exclude'])


def changes(root: Path, before: str, after: str | None, paths=()) -> list[tuple[str, str]]:
    # NUL framing preserves Chinese, spaces and newlines in real source paths;
    # Git's default quoted path display is not a machine-readable protocol.
    args = ['diff', '--name-status', '-z', '--no-renames', before]
    if after:
        args.append(after)
    args.extend(['--', *paths])
    fields = git(root, *args).rstrip('\0').split('\0')
    result = list(zip(fields[::2], fields[1::2])) if fields != [''] else []
    if after is None:
        tracked = {p for _, p in result}
        result.extend(('A', p) for p in git(root, 'ls-files', '-z', '--others', '--exclude-standard', '--', *paths).split('\0') if p and p not in tracked)
    return result


def check_repository(root: Path, *, base_ref: str | None = None, head_ref: str | None = None) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    index_path = root / INDEX
    if not index_path.is_file():
        return [f'missing capability index: {INDEX}']
    index = index_path.read_text(encoding='utf-8-sig')
    local_links(root, index_path, index, errors)
    entries: dict[str, str] = {}
    owners: dict[str, set[str]] = {}
    section = ''
    for line in index.splitlines():
        if line.startswith('## '):
            section = line
        match = ROW.search(line)
        if not match:
            continue
        identifier, relative = match.groups()
        if identifier in entries:
            errors.append(f'duplicate capability ID: {identifier}')
        expected = '已确认' if identifier.startswith('PC-') else '退役' if identifier.startswith('C-') else '核对'
        if expected not in section:
            errors.append(f'{identifier}: incorrect status section: {section}')
        card = index_path.parent / relative
        card_relative = card.relative_to(root).as_posix()
        entries[identifier] = card_relative
        if not card.is_file():
            continue  # The link check above reports the missing card.
        body = card.read_text(encoding='utf-8-sig')
        if not body.startswith(f'# {identifier} ') or not card.name.startswith(identifier + '-'):
            errors.append(f'{identifier}: card heading/filename does not match ID')
        required = ['状态', '验证入口']
        state = next((line for line in body.splitlines() if '**状态：**' in line), '')
        allowed_states = ('已确认',) if identifier.startswith('PC-') else ('退役', '兼容', '隐藏') if identifier.startswith('C-') else ('待核对', '已核对', '分类')
        if not any(value in state for value in allowed_states):
            errors.append(f'{identifier}: card status does not match its registered category')
        if identifier.startswith('PC-'):
            required += ['需求依据', '能力范围', '官方复用', '接口与状态归属', '后续维护']
        for field in required:
            if field not in body:
                errors.append(f'{identifier}: missing maintenance field: {field}')
        if not any(field in body for field in ('登记记录', '核对记录', '更新记录')):
            errors.append(f'{identifier}: missing dated maintenance record')
        owners[identifier] = local_links(root, card, body, errors)
    for card in (root / CARDS).glob('*.md'):
        if card.relative_to(root).as_posix() not in entries.values():
            errors.append(f'unlisted maintenance card: {card.name}')
    if not entries:
        errors.append('capability index has no registered rows')
    for title, amount in re.findall(r'^## (已确认能力|退役与兼容代码|待核对存量|已核对存量)（(\d+) 项', index, re.MULTILINE):
        prefix = {'已确认能力': 'PC-', '退役与兼容代码': 'C-', '待核对存量': 'U-', '已核对存量': 'U-'}[title]
        if int(amount) != sum(identifier.startswith(prefix) for identifier in entries):
            errors.append(f'outdated section count: {title}')

    ledger_path = root / LEDGER
    if not ledger_path.is_file():
        return [*errors, f'missing shared-source ledger: {LEDGER}']
    try:
        ledger = json.loads(ledger_path.read_text(encoding='utf-8-sig'))
        baseline = json.loads((root / 'docs/workbench/upstream-base.json').read_text(encoding='utf-8-sig'))['upstream_commit']
        if ledger.get('schema_version') != 1 or ledger.get('upstream_commit') != baseline:
            errors.append('shared-source ledger schema or official baseline does not match')
        scope = ledger['scope']
        if not scope['include'] or not all(isinstance(p, str) and p for p in scope['include'] + scope['exclude']):
            raise ValueError('invalid shared-source scope')
        if set(scope['include']) != SHARED_INCLUDE or set(scope['exclude']) != SHARED_EXCLUDE:
            errors.append('shared-source scope must match the audited public directories; do not hide differences by narrowing it')
        shared: dict[str, dict] = {}
        for entry in ledger['entries']:
            path = entry['path']
            if path in shared:
                errors.append(f'duplicate shared-source entry: {path}')
            shared[path] = entry
            if not in_scope(path, scope):
                errors.append(f'shared-source path outside declared scope: {path}')
            if entry.get('kind') not in KINDS or entry.get('status') not in {'A', 'M', 'D', 'T'}:
                errors.append(f'invalid shared-source classification: {path}')
            if not entry.get('reason', '').strip() or not entry.get('upstream_check', '').strip():
                errors.append(f'missing shared-source rationale or upstream check: {path}')
            identifiers = entry.get('capabilities', [])
            if not identifiers or any(identifier not in entries for identifier in identifiers):
                errors.append(f'unknown/missing capability in shared-source entry: {path}')
        actual = {p: s for s, p in changes(root, baseline, head_ref, scope['include']) if in_scope(p, scope)}
        for path, status in actual.items():
            if path not in shared:
                errors.append(f'unregistered shared-source difference: {path}')
            elif shared[path].get('status') != status:
                errors.append(f'shared-source status differs from Git: {path}')
        for path in shared.keys() - actual.keys():
            errors.append(f'stale shared-source difference: {path}')
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [*errors, f'invalid shared-source ledger: {exc}']

    if base_ref:
        head = head_ref or 'HEAD'
        try:
            if git(root, 'merge-base', base_ref, head).strip() != git(root, 'rev-parse', base_ref).strip():
                errors.append('change base must be an ancestor of the reviewed head; do not silently skip commits')
            commits = git(root, 'rev-list', '--reverse', f'{base_ref}..{head}').splitlines()
            # Preserve genuine upstream history. Only immutable commits already
            # contained in the recorded official baseline are exempt; the fork's
            # integration/maintenance commit still declares its own impact.
            official_commits = set(git(root, 'rev-list', baseline).splitlines())
            for commit in commits:
                if commit in official_commits:
                    continue
                parents = git(root, 'show', '-s', '--format=%P', commit).split()
                if not parents:
                    continue
                changed = changes(root, parents[0], commit)
                check_impact(root, commit, changed, entries, owners, shared, scope, errors)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def check_impact(root, commit, changed, entries, owners, shared, scope, errors):
    """Require explicit impact for code; new capability claims also update docs.

    A maintenance declaration is not automatic proof of unchanged behavior.
    Reviewers still assess the stated reason and the source diff.
    """
    code = [(s, p) for s, p in changed if production_path(p, owners, scope)]
    if not code:
        return
    message = git(root, 'show', '-s', '--format=%B', commit)
    trailers = {}
    for key, value in re.findall(r'^(Private-Change|Private-Capabilities|Private-Reason):[ \t]*(.*)$', message, re.MULTILINE):
        trailers[key] = value.strip()
    prefix = commit[:12] + ': '
    mode = trailers.get('Private-Change')
    if mode not in {'feature', 'maintenance'}:
        errors.append(prefix + 'production changes require Private-Change: feature|maintenance')
    identifiers = set(re.findall(r'(?:PC|C|U)-\d+', trailers.get('Private-Capabilities', '')))
    if not identifiers or any(i not in entries for i in identifiers):
        errors.append(prefix + 'Private-Capabilities must name existing maintenance card IDs')
    if not trailers.get('Private-Reason'):
        errors.append(prefix + 'production changes require a concrete Private-Reason')
    changed_paths = {p for _, p in changed}
    if mode == 'feature':
        if any(not i.startswith('PC-') for i in identifiers):
            errors.append(prefix + 'retired/review entries do not authorize new features')
        if INDEX not in changed_paths:
            errors.append(prefix + 'feature changes must update the capability index in the same commit')
        for identifier in identifiers:
            if identifier in entries and entries[identifier] not in changed_paths:
                errors.append(prefix + f'feature changes must update {identifier} card in the same commit')
    for status, path in code:
        if in_scope(path, scope):
            associated = set(shared.get(path, {}).get('capabilities', []))
            if path not in shared and 'PC-20' in entries:
                # Final structural validation proves this path has no retained
                # difference from the official tree. Its appearance in a fork
                # integration diff is upstream maintenance, not a private feature.
                associated = {'PC-20'}
        else:
            associated = {i for i, paths in owners.items() if any(path == p or path.startswith(p.rstrip('/') + '/') for p in paths)}
        if not associated.intersection(identifiers):
            errors.append(prefix + f'production path lacks a declared owning capability: {path}')
        if status == 'A' and not in_scope(path, scope):
            if not any(entries.get(i) in changed_paths for i in associated.intersection(identifiers)):
                errors.append(prefix + f'new private source requires its owning maintenance card update: {path}')
        if status == 'A' and in_scope(path, scope) and LEDGER not in changed_paths:
            errors.append(prefix + f'new shared source requires the shared-source ledger in the same commit: {path}')


def production_path(path: str, owners: dict[str, set[str]], scope: dict) -> bool:
    if path.startswith(('tests/', 'docs/', 'specs/')) or '/tests/' in path:
        return False
    if in_scope(path, scope):
        return True
    source = Path(path)
    relevant = source.suffix in CODE_SUFFIXES or source.name == 'SKILL.md' or path == 'scripts/git-hooks/pre-push'
    owned = any(path == p or path.startswith(p.rstrip('/') + '/') for paths in owners.values() for p in paths)
    return relevant and (path.startswith(PRIVATE_ROOTS) or path.startswith('scripts/') or owned)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--base-ref', help='Validate impact trailers and same-commit documentation for every commit after this ancestor.')
    parser.add_argument('--head-ref', help='Git tree to compare; defaults to the current working tree for structural checks.')
    args = parser.parse_args()
    try:
        errors = check_repository(args.root, base_ref=args.base_ref, head_ref=args.head_ref)
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    print(json.dumps({'passed': not errors, 'errors': errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
