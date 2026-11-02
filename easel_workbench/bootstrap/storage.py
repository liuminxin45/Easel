"""Ordered private storage bootstrap; preserves historical one-time imports."""


def initialize_store(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,source_job TEXT NOT NULL,run_id TEXT NOT NULL,run_at TEXT NOT NULL,hash TEXT NOT NULL,final_text TEXT NOT NULL,UNIQUE(source_job,run_id,hash));
CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY,source_job TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,url TEXT NOT NULL,publisher TEXT,published_at TEXT,run_at TEXT NOT NULL,run TEXT NOT NULL,unread INTEGER NOT NULL DEFAULT 1,selected INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,article_id TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,reply TEXT,error TEXT,thread TEXT NOT NULL,turn_id TEXT,rollout_offset INTEGER,output_path TEXT);
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provenance(article_id TEXT NOT NULL,run TEXT NOT NULL,PRIMARY KEY(article_id,run));
''')
    if 'published_at_raw' not in {r[1] for r in c.execute('pragma table_info(articles)')}: c.execute('alter table articles add column published_at_raw TEXT')
    if 'source_event_id' not in {r[1] for r in c.execute('pragma table_info(articles)')}: c.execute('alter table articles add column source_event_id TEXT')
    for field,kind in (('source_order','INTEGER'),('hot','TEXT'),('fetched_at','TEXT'),('source_protocol_id','TEXT')):
        if field not in {r[1] for r in c.execute('pragma table_info(articles)')}:c.execute('alter table articles add column '+field+' '+kind)
    from easel_workbench.runtime.source_registry import migrate as source_migrate
    source_migrate(c)
    c.execute('create unique index if not exists articles_source_event on articles(source_job,source_event_id) where source_event_id is not null')
    from easel_workbench.runtime import notifications as notifications
    notifications.migrate(c)
    from easel_workbench.runtime import news_feedback as news_feedback
    news_feedback.migrate(c)
    from easel_workbench.runtime import creative_review as creative_review
    creative_review.migrate(c)
    from easel_workbench.runtime.weekly_periodical import migrate as periodical_migrate
    periodical_migrate(c)


def initialize_toolbox(c, *, import_history, thread):
    c.executescript('''
CREATE TABLE IF NOT EXISTS toolbox_works(id TEXT PRIMARY KEY,article_id TEXT,title TEXT NOT NULL,material TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_jobs(id TEXT PRIMARY KEY,work_id TEXT,kind TEXT NOT NULL,text TEXT NOT NULL,candidate_id TEXT,scope TEXT NOT NULL DEFAULT '[]',files TEXT NOT NULL DEFAULT '[]',signature TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,turn_id TEXT,reply TEXT,error TEXT,dispatch_started INTEGER NOT NULL DEFAULT 0,queue_id TEXT,rollout_offset INTEGER);
CREATE INDEX IF NOT EXISTS toolbox_jobs_work ON toolbox_jobs(work_id,created_at);
CREATE TABLE IF NOT EXISTS toolbox_files(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_archive(file_id TEXT PRIMARY KEY,turn_id TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS toolbox_work_options(work_id TEXT PRIMARY KEY,format TEXT NOT NULL,article_mode TEXT NOT NULL);
''')
    from easel_workbench.runtime.article_drafts import initialize
    initialize(c)
    from easel_workbench.runtime.direct_turns import initialize as initialize_direct_turns
    initialize_direct_turns(c)
    from easel_workbench.runtime.browser_cleanup import initialize as initialize_cleanup
    initialize_cleanup(c)
    from easel_workbench.runtime.work_review import initialize as initialize_review
    initialize_review(c)
    from easel_workbench.runtime.content_studio import initialize as initialize_studio
    initialize_studio(c)
    from easel_workbench.runtime.production_outcome import initialize as initialize_outcomes
    initialize_outcomes(c)
    from easel_workbench.runtime.production_retry import initialize as initialize_retries
    initialize_retries(c)
    from easel_workbench.runtime.learning_execution import initialize as initialize_learning_execution
    initialize_learning_execution(c)
    from easel_workbench.runtime.completion_service import initialize as initialize_completions
    initialize_completions(c)
    from easel_workbench.runtime.local_operations import initialize as initialize_local
    initialize_local(c)
    from easel_workbench.runtime.creator_runtime import initialize as initialize_creator
    initialize_creator(c)
    from easel_workbench.runtime.task_runtime import initialize as initialize_task_runtime
    initialize_task_runtime(c)
    if not c.execute("SELECT 1 FROM toolbox_meta WHERE key='legacy-import-v1'").fetchone():
        import_history(c)
        c.execute("INSERT INTO toolbox_meta VALUES('legacy-import-v1','done')")
    if not c.execute("SELECT 1 FROM toolbox_meta WHERE key='legacy-files-v1'").fetchone():
        try:
            c.execute("INSERT OR IGNORE INTO toolbox_archive SELECT f.id,f.turn_id,f.created_at FROM wb_files f JOIN toolbox_files t ON t.id=f.id WHERE f.thread_id=? AND f.direction='output'",(thread,))
        except __import__('sqlite3').OperationalError:pass
        c.execute("INSERT INTO toolbox_meta VALUES('legacy-files-v1','done')")
