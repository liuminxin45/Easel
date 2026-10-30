"""Historical audit projection must never rewrite or clear a retained receipt."""
import ast
from pathlib import Path
import sqlite3

import pytest


def adapter():
    path=Path(__file__).resolve().parents[1]/'scripts/activate_workbench.py'
    node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef) and n.name=='HistoricalAuditConnection')
    namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    return namespace['HistoricalAuditConnection']


def test_nullable_source_snapshot_preserves_the_exact_old_row_shape():
    with sqlite3.connect(':memory:') as c:
        c.row_factory=sqlite3.Row;c.execute('CREATE TABLE collection_tasks(id TEXT,status TEXT,source_snapshot TEXT)')
        c.execute("INSERT INTO collection_tasks VALUES('original','blocked',NULL)")
        view=adapter()(c)
        assert dict(view.execute('SELECT * FROM collection_tasks WHERE id=?',('original',)).fetchone())=={'id':'original','status':'blocked'}
        c.execute("UPDATE collection_tasks SET status='failed' WHERE id='original'")
        assert view.execute('SELECT * FROM collection_tasks WHERE id=?',('original',)).fetchone()['status']=='failed'
        c.execute("UPDATE collection_tasks SET source_snapshot='{}' WHERE id='original'")
        with pytest.raises(ValueError):view.execute('SELECT * FROM collection_tasks WHERE id=?',('original',))
        assert c.execute("SELECT source_snapshot FROM collection_tasks WHERE id='original'").fetchone()[0]=='{}'


def test_unchanged_schema_keeps_legacy_query_semantics():
    with sqlite3.connect(':memory:') as c:
        c.execute('CREATE TABLE collection_tasks(id TEXT,status TEXT)');c.execute("INSERT INTO collection_tasks VALUES('old','blocked')")
        assert adapter()(c).execute('SELECT * FROM collection_tasks WHERE id=?',('old',)).fetchone()==('old','blocked')
