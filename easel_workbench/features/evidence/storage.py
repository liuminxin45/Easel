"""Evidence-indexed creative learning, with one canonical strategy document.

SQLite contains provenance, candidate proposals, queue receipts and immutable
execution snapshots. Only an explicit preview/confirm can change project policy.
Importing or constructing this service never starts a process or calls an AI.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import datetime as dt
import difflib
import hashlib
import json
import mimetypes
import math
import os
from pathlib import Path
import re
import time
import threading
import uuid

from easel_workbench.runtime.feedback_ledger import locked

from easel_workbench.features.evidence.records import POLICY_PATH, CONDITIONS, RELATIONSHIPS, TERMINAL, TEXT_SUFFIXES, MEDIA_SUFFIXES, SECRET_NAME, SECRET_TEXT, FORBIDDEN_PARTS, packed, sha, stamp, identity, bounded, atomic_bytes, original_mime, LearningConflict

class EvidenceRecords:
    def _all(self, c, table):
        return [json.loads(row['document']) for row in c.execute('SELECT document FROM ' + table + ' ORDER BY rowid')]

    def _get(self, c, table, key, required=True):
        row = c.execute('SELECT document FROM ' + table + ' WHERE id=?', (key,)).fetchone()
        if not row and required:
            raise ValueError('找不到对应学习记录')
        return json.loads(row['document']) if row else None

    def _put(self, c, table, document):
        document = copy.deepcopy(document)
        if table == 'learning_evidence':
            previous=self._get(c,table,document['id'],False)
            if previous and {k:v for k,v in previous.items() if k!='updated_at'}=={k:v for k,v in document.items() if k!='updated_at'}:
                return previous
            document['updated_at']=stamp()
            c.execute('INSERT INTO learning_evidence VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET sha256=excluded.sha256,document=excluded.document,updated_at=excluded.updated_at', (document['id'], document['sha256'], packed(document), document['updated_at']))
        else:
            document['updated_at'] = stamp()
            c.execute('INSERT OR REPLACE INTO ' + table + ' VALUES(?,?,?)', (document['id'], packed(document), document['updated_at']))
        return document
