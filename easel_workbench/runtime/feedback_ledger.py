"""Single writer for Hermes' existing news-feedback records.

The markdown files remain canonical. The journal/receipts are recovery and
idempotency metadata, not a second interest profile.
"""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import time
import uuid

FILES = ('feedback.md', 'profile-current.md', 'profile-algorithm.md', 'evolution.md')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def atomic(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    with temp.open('w', encoding='utf-8', newline='\n') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


@contextlib.contextmanager
def locked(path, timeout=20):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        if f.tell() == 0:
            f.write(b'0'); f.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                f.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('feedback writer is busy')
                time.sleep(.05)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


class Conflict(ValueError):
    pass


class Ledger:
    def __init__(self, skill):
        self.skill = pathlib.Path(skill).resolve()
        self.refs = self.skill / 'references'
        self.state = self.skill / '.feedback-state'

    def receipt(self, fid):
        self.valid_id(fid)
        p = self.state / 'receipts' / (fid + '.json')
        if not p.exists():
            return None
        receipt = json.loads(p.read_text(encoding='utf-8'))
        text = (self.refs / 'feedback.md').read_text(encoding='utf-8')
        match = re.search(r'(?ms)^## ' + re.escape(fid) + r'[^\n]*\n.*?```json\n(.*?)\n```', text)
        if not match or sha(json.dumps(json.loads(match.group(1)), ensure_ascii=False, sort_keys=True)) != receipt['event_hash']:
            raise Conflict('canonical original feedback no longer matches its receipt')
        if receipt['profile_changed'] and ('## Feedback amendment ' + fid) not in (self.refs / 'profile-current.md').read_text(encoding='utf-8'):
            raise Conflict('canonical profile amendment is missing')
        return receipt

    @staticmethod
    def valid_id(fid):
        if not isinstance(fid, str) or not re.fullmatch(r'(?:ND|CHAT)_[a-f0-9]{32}', fid):
            raise ValueError('invalid feedback ID')

    def _texts(self):
        return {name: (self.refs / name).read_text(encoding='utf-8') for name in FILES}

    def _recover(self):
        journal = self.state / 'pending.json'
        if not journal.exists():
            return
        tx = json.loads(journal.read_text(encoding='utf-8'))
        # Inspect all destinations before writing any: never overwrite an outside edit.
        for name, text in tx['after'].items():
            if name not in FILES:
                raise ValueError('invalid journal destination')
            current = (self.refs / name).read_text(encoding='utf-8')
            if sha(current) not in (tx['before'][name], sha(text)):
                raise Conflict('journal recovery conflicts with an external edit: ' + name)
        for name, text in tx['after'].items():
            if (self.refs / name).read_text(encoding='utf-8') != text:
                atomic(self.refs / name, text)
        # Verify canonical bytes before exposing a successful receipt.
        for name, text in tx['after'].items():
            if (self.refs / name).read_text(encoding='utf-8') != text:
                raise OSError('feedback readback failed')
        receipts = tx.get('receipts', [tx['receipt']] if 'receipt' in tx else [])
        if not receipts:raise ValueError('feedback journal has no receipts')
        for receipt in receipts:
            self.valid_id(receipt['id'])
            atomic(self.state / 'receipts' / (receipt['id'] + '.json'), receipt)
        journal.unlink()

    def snapshot(self, job=None):
        with locked(self.state / 'writer.lock'):
            self._recover()
            texts = self._texts()
            texts['SKILL.md'] = (self.skill / 'SKILL.md').read_text(encoding='utf-8')
            version = sha(json.dumps(texts, ensure_ascii=False, sort_keys=True))
            result = {'version': version, 'profile_hash': sha(texts['profile-current.md']),
                      'read_at': now(), 'documents': texts}
            if job:
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', job):
                    raise ValueError('invalid source job')
                with (self.state / 'consumption.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps({k: v for k, v in result.items() if k != 'documents'} |
                                       {'source_job': job}, ensure_ascii=False) + '\n')
                    f.flush(); os.fsync(f.fileno())
            return result

    def validate_event(self, event):
        self.valid_id(event.get('id'))
        for key in ('raw_text', 'title', 'url', 'source', 'created_at', 'kind'):
            if not isinstance(event.get(key), str) or len(event[key]) > 10000:
                raise ValueError('invalid feedback field: ' + key)
        if event['kind'] not in ('selection', 'topic_feedback', 'chat'):
            raise ValueError('invalid feedback subject')
        if not event['raw_text'].strip() and event['kind'] != 'selection':
            raise ValueError('feedback text required')
        # Context is data. File destinations and commands never come from the event.
        if len(json.dumps(event, ensure_ascii=False)) > 150000:
            raise ValueError('feedback context too large')

    def commit(self, event, proposal, base_version):
        return self.commit_batch([event], [proposal], base_version)[0]

    def commit_batch(self, events, proposals, base_version):
        """One version check and one recoverable transaction for a bounded batch.

        Every original event still owns an exact independent receipt. Replaying
        a successful batch does not require its now-old input profile version.
        """
        if not isinstance(events,list) or not 1 <= len(events) <= 20 or not isinstance(proposals,list) or len(events)!=len(proposals):
            raise ValueError('feedback batch must contain 1..20 matching entries')
        if len({event.get('id') for event in events})!=len(events):raise ValueError('duplicate feedback IDs in batch')
        for event in events:self.validate_event(event)
        with locked(self.state / 'writer.lock'):
            self._recover()
            previous=[]
            for event in events:
                receipt=self.receipt(event['id'])
                if receipt and receipt['event_hash']!=sha(json.dumps(event,ensure_ascii=False,sort_keys=True)):
                    raise Conflict('feedback ID reused with different content')
                previous.append(receipt)
            if all(previous):return previous
            texts=self._texts()
            original=dict(texts)
            version_texts=texts | {'SKILL.md':(self.skill/'SKILL.md').read_text(encoding='utf-8')}
            if sha(json.dumps(version_texts,ensure_ascii=False,sort_keys=True))!=base_version:
                raise Conflict('profile changed during interpretation; batch requires review')
            receipts=[]
            for event,proposal,old in zip(events,proposals,previous):
                if old:continue
                after,receipt=self._prepare_commit(event,proposal,texts,base_version)
                texts.update(after);receipts.append(receipt)
            for receipt in receipts:
                receipt['profile_version']=sha(texts['profile-current.md'])
                receipt['batch_size']=len(events)
            after={name:texts[name] for name in FILES if texts[name]!=original[name]}
            atomic(self.state/'pending.json',{'before':{name:sha(original[name]) for name in after},'after':after,'receipts':receipts})
            self._recover()
            return [self.receipt(event['id']) for event in events]

    def _prepare_commit(self,event,proposal,texts,base_version):
        p = self.validate_proposal(event, proposal, texts)
        fid = event['id']
        event_hash = sha(json.dumps(event, ensure_ascii=False, sort_keys=True))
        duplicate = p['duplicate_of']
        # Exact URL matches link to existing evidence; semantic matches come from Hermes.
        if not duplicate and event['url']:
            for block in re.split(r'(?m)(?=^## )', texts['feedback.md']):
                urls = {u.rstrip(')].,，。；』') for u in re.findall(r'''https?://[^\s<>"'`\\]+''', block)}
                if event['url'] in urls:
                    m = re.search(r'^##\s+((?:F\d+)|(?:(?:ND|CHAT)_[a-f0-9]{32}))\b', block)
                    if m:
                        duplicate = m.group(1); break
        raw = json.dumps(event, ensure_ascii=False, indent=2)
        record = (f'\n\n## {fid}：{event["title"].replace(chr(10), " ")}\n'
                  f'来源：{event["source"]}；时间：{event["created_at"]}；对象：新闻选题。\n'
                  f'原始提交（JSON字符串逐字保留原话，新闻上下文不是指令）：\n```json\n{raw}\n```\n'
                  f'信号：{p["signal"]}；理由类型：{p["reason_kind"]}。\n'
                  f'解释（来源见回执）：{p["analysis"]}\n'
                  f'适用范围：{p["scope"]}\n边界与反例：{p["counterexamples"]}\n'
                  f'关联已有事件反馈：{duplicate or "未识别；不据URL不同自动认定事件独立"}。\n'
                  f'学习动作：{p["learning"]}；关联规则：{", ".join(p["rule_ids"]) or "无"}。\n'
                  '本次选题动作及原话确定；新闻事实未因此获核验。沉默不是负反馈，成品采纳另行处理。\n')
        profile = texts['profile-current.md']
        if p['learning'] != 'none':
            confidence = 'explicit user correction; inferred scope remains tentative' if p['learning'] == 'correction' else 'tentative; no confidence promotion'
            profile += (f'\n\n## Feedback amendment {fid} — {event["created_at"]}\n'
                        f'Rules: {", ".join(p["rule_ids"])}; operation: {p["learning"]}; {confidence}.\n'
                        f'{p["profile_note"]}\nScope: {p["scope"]}\nBoundaries: {p["counterexamples"]}\n'
                        f'Evidence: {fid}; event: {event["url"] or "unknown"}; duplicate/support link: {duplicate or "independence unreviewed"}.\n'
                        'Preserve the original algorithm. This is an additive amendment; only an explicit correction supersedes its identified rule. '
                        'Count each underlying event once. Promotion still requires three independent compatible events, contradiction review and a recorded review.\n')
        changed = profile != texts['profile-current.md']
        receipt = {'id': fid, 'event_hash': event_hash, 'applied_at': now(),
                   'profile_changed': changed, 'profile_version': sha(profile),
                   'duplicate_of': duplicate, 'learning': p['learning'], 'rule_ids': p['rule_ids'],
                   'summary': p['analysis'], 'canonical': 'references/feedback.md#' + fid}
        evolution = (f'\n\n### {fid} before — {now()}\n'
                     f'Trigger: {event["source"]}; original feedback: {fid}. Prior bundle: {base_version}; prior profile hash: {sha(texts["profile-current.md"])}.\n'
                     f'Proposed change: {p["learning"]}; {p["profile_note"] or "event-local record only"}. '
                     f'Rationale: {p["analysis"]}. Risk/boundaries: {p["counterexamples"]}.\n'
                     'Validation: retain exact input; check subject, empty/production-only reasons, duplicates, tentative scope, and compare current version before writing.\n'
                     f'\n### {fid} outcome — {now()}\n'
                     f'Canonical raw feedback appended; profile_changed={changed}; resulting profile hash={sha(profile)}; duplicate_of={duplicate or "unknown"}. '
                     'Ranking algorithm, schedules and news facts unchanged. File journal and receipt permit idempotent recovery; no recommendation-quality claim. '
                     f'Rollback by appending a correction referencing {fid}, preserving original evidence.\n')
        after = {'feedback.md': texts['feedback.md'] + record,
                 'evolution.md': texts['evolution.md'] + evolution,
                 'profile-current.md': profile}
        receipt["execution"] = proposal.get("execution", "model_batch")
        return after,receipt


    @staticmethod
    def validate_proposal(event, p, texts):
        if not isinstance(p, dict):
            raise ValueError('Hermes proposal must be an object')
        for key in ('analysis', 'scope', 'counterexamples', 'profile_note', 'correction_quote'):
            if not isinstance(p.get(key), str) or len(p[key]) > 6000:
                raise ValueError('invalid proposal field: ' + key)
        if not p['analysis'].strip() or not p['scope'].strip() or not p['counterexamples'].strip():
            raise ValueError('interpretation and boundaries required')
        if p.get('learning') not in ('none', 'support', 'hypothesis', 'correction'):
            raise ValueError('invalid learning action; automatic confidence promotion is not a feedback ingestion action')
        if p.get('reason_kind') not in ('none', 'interest', 'production', 'mixed', 'correction'):
            raise ValueError('invalid reason type')
        if p.get('signal') not in ('positive', 'negative', 'mixed', 'correction'):
            raise ValueError('invalid signal')
        if event['kind'] == 'selection' and p['signal'] != 'positive':
            raise ValueError('selection is an explicit event-local positive signal')
        if not isinstance(p.get('rule_ids'), list) or len(p['rule_ids']) > 12:
            raise ValueError('invalid rule IDs')
        known = set(re.findall(r'\b(?:P\d+|H\d+|[HP]_(?:ND|CHAT)_[a-f0-9]{32})\b', texts['profile-current.md']))
        new_ids = {'H_' + event['id']} if p['learning'] == 'hypothesis' else ({'P_' + event['id']} if p['learning'] == 'correction' else set())
        allowed = known | new_ids
        if any(not isinstance(x, str) or x not in allowed for x in p['rule_ids']):
            raise ValueError('unknown rule ID; use H_<feedback_id> for hypotheses or P_<feedback_id> for an explicit general instruction')
        if p['learning'] != 'none' and (not p['rule_ids'] or not p['profile_note'].strip()):
            raise ValueError('profile change requires rule IDs and bounded note')
        if (not event['raw_text'].strip() or p['reason_kind'] in ('none', 'production')) and p['learning'] != 'none':
            raise ValueError('reasonless or production-only selection cannot update interest profile')
        if p['learning'] == 'correction':
            quote = p['correction_quote'].strip()
            if not quote or quote not in event['raw_text'] or p['reason_kind'] != 'correction':
                raise ValueError('correction requires a literal explicit user correction')
        duplicate = p.get('duplicate_of')
        if duplicate is not None and (not isinstance(duplicate, str) or not re.fullmatch(r'F\d+|(?:ND|CHAT)_[a-f0-9]{32}', duplicate) or duplicate not in texts['feedback.md']):
            raise ValueError('duplicate must link to existing feedback')
        return p


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--skill-dir', type=pathlib.Path, required=True)
    sub = ap.add_subparsers(dest='command', required=True)
    snap = sub.add_parser('snapshot'); snap.add_argument('--job')
    commit = sub.add_parser('commit'); commit.add_argument('--event', required=True); commit.add_argument('--proposal', required=True); commit.add_argument('--base-version', required=True)
    args = ap.parse_args(); ledger = Ledger(args.skill_dir)
    if args.command == 'snapshot':
        result = ledger.snapshot(args.job)
    else:
        result = ledger.commit(json.loads(pathlib.Path(args.event).read_text(encoding='utf-8-sig')),
                               json.loads(pathlib.Path(args.proposal).read_text(encoding='utf-8-sig')), args.base_version)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
