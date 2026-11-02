"""Original schema fragments; caller owns connection, ordering and transaction."""


def initialize_chat_submissions(c):
    c.execute('CREATE TABLE IF NOT EXISTS easel_chat_submissions(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,signature TEXT NOT NULL,document TEXT NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS easel_chat_submission_session ON easel_chat_submissions(session_id)')


def initialize_collection(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS collection_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,run_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collection_runs(id TEXT PRIMARY KEY,trigger TEXT NOT NULL,scope TEXT NOT NULL,created_at TEXT NOT NULL,retry_of TEXT);
CREATE TABLE IF NOT EXISTS collection_tasks(id TEXT PRIMARY KEY,source_id TEXT NOT NULL,status TEXT NOT NULL,phase TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,force INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,owner TEXT,owner_pid INTEGER,owner_creation TEXT,lease_token TEXT,lease_until REAL,heartbeat TEXT,fetched INTEGER NOT NULL DEFAULT 0,selected INTEGER NOT NULL DEFAULT 0,inserted INTEGER NOT NULL DEFAULT 0,duplicates INTEGER NOT NULL DEFAULT 0,error TEXT,message TEXT NOT NULL DEFAULT '',warnings TEXT NOT NULL DEFAULT '[]',retry_of TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS collection_source_active ON collection_tasks(source_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS collection_run_tasks(run_id TEXT NOT NULL,task_id TEXT NOT NULL,PRIMARY KEY(run_id,task_id));
CREATE INDEX IF NOT EXISTS collection_tasks_created ON collection_tasks(created_at);
CREATE TABLE IF NOT EXISTS collection_schedule_state(source_id TEXT PRIMARY KEY,next_run_at TEXT NOT NULL,last_slot TEXT,schedule_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collection_slots(source_id TEXT NOT NULL,scheduled_for TEXT NOT NULL,task_id TEXT NOT NULL,PRIMARY KEY(source_id,scheduled_for));
''')
    if 'resume_from' not in {row[1] for row in c.execute('PRAGMA table_info(collection_tasks)')}:c.execute('ALTER TABLE collection_tasks ADD COLUMN resume_from TEXT')
    if 'source_snapshot' not in {row[1] for row in c.execute('PRAGMA table_info(collection_tasks)')}:c.execute('ALTER TABLE collection_tasks ADD COLUMN source_snapshot TEXT')


def initialize_distribution(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS distribution_connections(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_revisions(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_approvals(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_deliveries(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_attempts(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_batches(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_runners(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS distribution_delivery_dedupe ON distribution_deliveries(json_extract(document,'$.dedupe_key'));
CREATE INDEX IF NOT EXISTS distribution_delivery_status ON distribution_deliveries(json_extract(document,'$.status'));
CREATE INDEX IF NOT EXISTS distribution_revision_work ON distribution_revisions(json_extract(document,'$.work_id'));
CREATE TRIGGER IF NOT EXISTS distribution_revision_no_update BEFORE UPDATE ON distribution_revisions BEGIN SELECT RAISE(ABORT,'distribution revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS distribution_revision_no_delete BEFORE DELETE ON distribution_revisions BEGIN SELECT RAISE(ABORT,'distribution revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS distribution_approval_no_update BEFORE UPDATE ON distribution_approvals BEGIN SELECT RAISE(ABORT,'distribution approvals are immutable'); END;
CREATE TRIGGER IF NOT EXISTS distribution_approval_no_delete BEFORE DELETE ON distribution_approvals BEGIN SELECT RAISE(ABORT,'distribution approvals are immutable'); END;
''')


def initialize_accounts(c):
    c.executescript('CREATE TABLE IF NOT EXISTS media_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL); CREATE TABLE IF NOT EXISTS media_account_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL);')
    c.execute('CREATE TABLE IF NOT EXISTS easel_native_account_bindings(platform TEXT PRIMARY KEY,session_id TEXT NOT NULL)')


def initialize_installations(c):
    c.executescript('CREATE TABLE IF NOT EXISTS media_install_jobs(id TEXT PRIMARY KEY,recipe TEXT NOT NULL,document TEXT NOT NULL);')


def initialize_evidence(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS learning_evidence(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL UNIQUE,document TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_evidence_search(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_proposals(id TEXT PRIMARY KEY,document TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_runs(id TEXT PRIMARY KEY,document TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_analysis_queue(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,owner TEXT,lease_token TEXT,lease_until REAL,result TEXT,error TEXT);
CREATE INDEX IF NOT EXISTS learning_queue_ready ON learning_analysis_queue(status,priority,created_at);
CREATE TABLE IF NOT EXISTS learning_index_state(id TEXT PRIMARY KEY,document TEXT NOT NULL);
''')


def initialize_chat_plans(c):
    c.execute('CREATE TABLE IF NOT EXISTS easel_chat_plans(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,signature TEXT NOT NULL,document TEXT NOT NULL)')


def initialize_creator(c):
    statements = '''
CREATE TABLE IF NOT EXISTS creator_profiles(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_profile_history(id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(id,revision));
CREATE TABLE IF NOT EXISTS creator_skills(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_skill_versions(skill_id TEXT NOT NULL,version INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(skill_id,version));
CREATE TABLE IF NOT EXISTS creator_skill_pointers(skill_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS creator_skill_blobs(sha256 TEXT PRIMARY KEY,bytes BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS creator_skill_events(id TEXT PRIMARY KEY,skill_id TEXT NOT NULL,version INTEGER NOT NULL,action TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_work_owners(work_id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,profile_revision INTEGER NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_profile_proposals(id TEXT PRIMARY KEY,document TEXT NOT NULL);
'''
    for statement in statements.split(';'):
        if statement.strip():
            c.execute(statement)



def initialize_tasks(c):
    # execute, rather than executescript, preserves the caller's transaction.
    for sql in (
        'CREATE TABLE IF NOT EXISTS creator_task_runs(id TEXT PRIMARY KEY,work_id TEXT,document TEXT NOT NULL,updated_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS creator_model_calls(id TEXT PRIMARY KEY,task_id TEXT,document TEXT NOT NULL,updated_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS creator_thread_contexts(id TEXT PRIMARY KEY,document TEXT NOT NULL,updated_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS creator_experience_receipts(id TEXT PRIMARY KEY,document TEXT NOT NULL,updated_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS creator_experience_coverage(profile_id TEXT NOT NULL,source_key TEXT NOT NULL,task_id TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(profile_id,source_key))',
    ):
        c.execute(sql)



def initialize_sources(connection):
    connection.executescript('''
CREATE TABLE IF NOT EXISTS collection_source_versions(source_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(source_id,revision));
CREATE TABLE IF NOT EXISTS collection_source_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
''')
