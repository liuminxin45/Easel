"""Collect a frozen generic Easel source into canonical private news records."""
import hashlib
import json
import os
from pathlib import Path

from easel.trends.runner import collect
from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.source_registry import SourceRegistry, packed


def run(snapshot, directory, *, root, report):
    store = Store(Path(root)/'data/desk.sqlite')
    registry = SourceRegistry(store, root)
    directory = Path(directory)
    raw_path = directory/'source-payload.json'
    report('fetching')
    if raw_path.exists():
        from easel.trends.protocol import validate_payload
        payload = validate_payload(json.loads(raw_path.read_text(encoding='utf-8')))
    else:
        payload = collect(registry.source(snapshot), dict(os.environ))
        from easel_workbench.runtime.feedback_ledger import atomic
        atomic(raw_path, payload)
    rows = payload['items']
    inserted = 0
    report('persisting', {'fetched': len(rows), 'selected': len(rows)})
    all_articles = [{'title': item['title'], 'url': item['url'],
                     'body': '来源仅提供标题／链接。请通过原文链接阅读来源内容。' if item['url'] else '来源仅提供标题，未提供正文或原文链接。',
                     'publisher': snapshot['label'], 'published_at': item['published_at'],
                     'source_event_id': 'protocol:'+hashlib.sha256(item['id'].encode()).hexdigest(),
                     'source_protocol_id': item['id'],
                     'source_order': index+1, 'hot': item['hot'], 'fetched_at': payload['fetched_at']}
                    for index, item in enumerate(rows)]
    batches=[];batch=[]
    for article in all_articles:
        if batch and (len(batch)==100 or len(packed([*batch,article]))>190000):
            batches.append(batch);batch=[]
        batch.append(article)
    if batch:batches.append(batch)
    for articles in batches:
        text = packed(articles)
        doc = {'schema_version': 1, 'source_job': snapshot['id'], 'feed_id': snapshot['feed'],
               'run_id': 'protocol-'+hashlib.sha256(text.encode()).hexdigest(), 'run_at': payload['fetched_at'],
               'final_text': text, 'articles': articles}
        receipt = store.ingest(doc)
        canonical = Path(root)/'data/canonical'/snapshot['id']/(receipt['run']+'.json')
        from easel_workbench.runtime.feedback_ledger import atomic
        atomic(canonical, doc)
        inserted += receipt['inserted']
    return {'status': 'completed', 'fetched': len(rows), 'selected': len(rows), 'inserted': inserted,
            'duplicates': len(rows)-inserted, 'message': '来源已检查' if rows else '采集成功，暂无热点', 'warnings': []}
