-- 风控问数系统 · 运营数据六表
-- 唯一来源：docs/data-model.md §二；字段/约束/索引与文档不一致时以文档为准。
-- SQLite 3，无 migration 框架（schema 变更走 ADR）。

-- ---------- 2.1 query_log：raw log，1 年保留 ----------
CREATE TABLE IF NOT EXISTS query_log (
    qid           TEXT    PRIMARY KEY,
    question      TEXT    NOT NULL,
    sql           TEXT    NOT NULL,
    sql_edited    INTEGER NOT NULL DEFAULT 0,
    result_digest TEXT    NOT NULL,
    user          TEXT    NOT NULL,
    dept          TEXT    NOT NULL,
    ts            TEXT    NOT NULL,
    confirmed_by  TEXT    NOT NULL DEFAULT '[]',
    signature     TEXT
);

CREATE INDEX IF NOT EXISTS idx_ql_ts   ON query_log(ts);
CREATE INDEX IF NOT EXISTS idx_ql_user ON query_log(user);
CREATE INDEX IF NOT EXISTS idx_ql_sig  ON query_log(signature);

-- ---------- 2.2 fact：FactStore 持久化，落库后不可变 ----------
CREATE TABLE IF NOT EXISTS fact (
    fid        TEXT    PRIMARY KEY,
    value      REAL    NOT NULL,
    unit       TEXT    NOT NULL,
    metric     TEXT    NOT NULL,
    segment    TEXT    NOT NULL DEFAULT '',
    source     TEXT    NOT NULL,
    qid        TEXT,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fact_metric ON fact(metric, segment);

-- ---------- 2.3 review_record：人审状态机 ----------
CREATE TABLE IF NOT EXISTS review_record (
    rid         TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id  TEXT NOT NULL,
    level       TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'pending',
    assignee    TEXT NOT NULL,
    decided_by  TEXT,
    decision    TEXT,
    decided_at  TEXT,
    sla_due     TEXT NOT NULL,
    material    TEXT
);

CREATE INDEX IF NOT EXISTS idx_rr_state    ON review_record(state);
CREATE INDEX IF NOT EXISTS idx_rr_assignee ON review_record(assignee);

-- ---------- 2.4 promotion：晋升记录 + evidence 快照 ----------
CREATE TABLE IF NOT EXISTS promotion (
    pid             TEXT    PRIMARY KEY,
    metric          TEXT    NOT NULL,
    signature       TEXT    NOT NULL,
    promoted_at     TEXT    NOT NULL,
    owner           TEXT    NOT NULL,
    evidence        TEXT    NOT NULL,
    aliases_added   TEXT    NOT NULL,
    calc_registered INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_promo_metric ON promotion(metric);

-- ---------- 2.5 audit_entry：旁路审计，只追加 ----------
CREATE TABLE IF NOT EXISTS audit_entry (
    aid       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    target    TEXT,
    detail    TEXT,
    prev_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_ts    ON audit_entry(ts);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_entry(actor);

-- ---------- 2.6 alert：告警发送记录 ----------
CREATE TABLE IF NOT EXISTS alert (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    channel TEXT NOT NULL,
    level   TEXT NOT NULL,
    subject TEXT NOT NULL,
    body    TEXT NOT NULL,
    acked_by TEXT
);

-- ============================================================
-- 不可变约束（P-12）
-- ============================================================

-- query_log：raw log 只允许 signature 从 NULL 回填一次；其余任何字段变化都拒绝。
CREATE TRIGGER IF NOT EXISTS trg_query_log_immutable
BEFORE UPDATE ON query_log
FOR EACH ROW
WHEN NEW.qid IS NOT OLD.qid
  OR NEW.question IS NOT OLD.question
  OR NEW.sql IS NOT OLD.sql
  OR NEW.sql_edited IS NOT OLD.sql_edited
  OR NEW.result_digest IS NOT OLD.result_digest
  OR NEW.user IS NOT OLD.user
  OR NEW.dept IS NOT OLD.dept
  OR NEW.ts IS NOT OLD.ts
  OR NEW.confirmed_by IS NOT OLD.confirmed_by
  OR (OLD.signature IS NOT NULL
      AND (NEW.signature IS NULL OR NEW.signature <> OLD.signature))
BEGIN
    SELECT RAISE(ABORT,
        'P-12：query_log 是不可变 raw log，只允许 signature 从 NULL 回填一次');
END;

CREATE TRIGGER IF NOT EXISTS trg_fact_no_update
BEFORE UPDATE ON fact
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'P-12：fact 落库后不可变，禁止 UPDATE');
END;

CREATE TRIGGER IF NOT EXISTS trg_fact_no_delete
BEFORE DELETE ON fact
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'P-12：fact 落库后不可变，禁止 DELETE');
END;

CREATE TRIGGER IF NOT EXISTS trg_promotion_no_update
BEFORE UPDATE ON promotion
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'P-12/P-13：promotion 只能追加，禁止 UPDATE');
END;

CREATE TRIGGER IF NOT EXISTS trg_promotion_no_delete
BEFORE DELETE ON promotion
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'P-12/P-13：promotion 只能追加，禁止 DELETE');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
BEFORE UPDATE ON audit_entry
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'P-12：audit_entry 只能追加，禁止 UPDATE');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
BEFORE DELETE ON audit_entry
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'P-12：audit_entry 只能追加，禁止 DELETE');
END;
