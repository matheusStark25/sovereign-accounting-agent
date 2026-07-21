-- Schema migrations (initial): creates core tables used by the agent
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS empresas (
  cnpj TEXT PRIMARY KEY,
  nome TEXT,
  regime TEXT,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cnpj TEXT,
  correlation_id TEXT,
  owner_pid INTEGER,
  started_at INTEGER,
  payload TEXT,
  priority TEXT,
  state TEXT,
  attempts INTEGER DEFAULT 0,
  created_at INTEGER,
  updated_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_tasks_cnpj ON tasks(cnpj);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT,
  component TEXT,
  message TEXT,
  metadata TEXT,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS heartbeats (
  worker_id TEXT PRIMARY KEY,
  last_seen INTEGER,
  restart_count INTEGER DEFAULT 0,
  quarantined INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS classification_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  correlation_id TEXT,
  classifier TEXT,
  score REAL,
  decision TEXT,
  payload TEXT,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS xml_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT UNIQUE,
  content BLOB,
  schema_ok INTEGER DEFAULT 0,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT UNIQUE,
  path TEXT,
  metadata TEXT,
  created_at INTEGER
);

CREATE TABLE IF NOT EXISTS secrets (
  name TEXT PRIMARY KEY,
  value TEXT,
  created_at INTEGER
);

COMMIT;
