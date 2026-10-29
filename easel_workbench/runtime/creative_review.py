"""Candidate-bound user decisions, independent of asynchronous archive work."""


def migrate(c):
    if 'candidate_task_id' not in {r[1] for r in c.execute('pragma table_info(tasks)')}:
        c.execute('alter table tasks add column candidate_task_id TEXT')
    # Also cover decisions from an old HTTP process during the rollout window.
    # Preserve existing user decisions without replaying any creative task.
    c.execute('''UPDATE tasks AS decision SET candidate_task_id=(
SELECT candidate.id FROM tasks AS candidate
WHERE candidate.article_id=decision.article_id AND candidate.kind IN ('select','change')
AND candidate.rowid<decision.rowid ORDER BY candidate.rowid DESC LIMIT 1)
WHERE decision.kind IN ('accept','reject') AND decision.candidate_task_id IS NULL''')
    c.execute('create index if not exists tasks_candidate_review on tasks(article_id,candidate_task_id,kind)')


def projections(tasks):
    candidates = {t['id']: {'candidate_task_id': t['id'], 'status': 'pending',
                            'decision_task_id': None, 'sync_status': None}
                  for t in tasks if t['kind'] in ('select', 'change')}
    for t in tasks:
        if t['kind'] in ('accept', 'reject') and t.get('candidate_task_id') in candidates:
            candidates[t['candidate_task_id']].update(
                status='accepted' if t['kind'] == 'accept' else 'rejected',
                decision_task_id=t['id'], sync_status=t['status'], decided_at=t['created_at'])
    return candidates
