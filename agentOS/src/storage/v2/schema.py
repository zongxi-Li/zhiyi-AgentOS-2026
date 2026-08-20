"""新一代 ACG 六级身份链的独立 Schema。"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_tasks (
    task_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN (
        'created', 'planning', 'ready', 'running', 'completed', 'archived'
    )),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_nodes (
    node_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    parent_node_id TEXT,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    constraints_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (node_id, task_id),
    FOREIGN KEY (task_id) REFERENCES user_tasks(task_id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_node_id, task_id)
        REFERENCES task_nodes(node_id, task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS acg_blueprints (
    blueprint_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    graph_id TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (task_id, version),
    UNIQUE (blueprint_id, task_id),
    FOREIGN KEY (task_id) REFERENCES user_tasks(task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS workflow_runs_v2 (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    blueprint_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'failed', 'succeeded', 'cancelled'
    )),
    graph_version INTEGER NOT NULL CHECK (graph_version >= 1),
    checkpoint_json TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, task_id),
    FOREIGN KEY (task_id) REFERENCES user_tasks(task_id) ON DELETE RESTRICT,
    FOREIGN KEY (blueprint_id, task_id)
        REFERENCES acg_blueprints(blueprint_id, task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'failed', 'succeeded', 'cancelled'
    )),
    started_at TEXT,
    finished_at TEXT,
    failure_reason TEXT,
    resource_binding_json TEXT,
    UNIQUE (run_id, node_id, attempt_number),
    UNIQUE (attempt_id, run_id, node_id),
    FOREIGN KEY (run_id) REFERENCES workflow_runs_v2(run_id) ON DELETE RESTRICT,
    FOREIGN KEY (node_id) REFERENCES task_nodes(node_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS step_executions (
    step_execution_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'failed', 'succeeded', 'cancelled'
    )),
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (attempt_id, run_id, node_id)
        REFERENCES attempts(attempt_id, run_id, node_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_task_nodes_task ON task_nodes(task_id);
CREATE INDEX IF NOT EXISTS idx_blueprints_task ON acg_blueprints(task_id, version);
CREATE INDEX IF NOT EXISTS idx_runs_v2_task ON workflow_runs_v2(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attempts_run ON attempts(run_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_step_executions_attempt ON step_executions(attempt_id);

CREATE TRIGGER IF NOT EXISTS attempts_require_same_task
BEFORE INSERT ON attempts
FOR EACH ROW
WHEN (
    SELECT task_id FROM workflow_runs_v2 WHERE run_id = NEW.run_id
) IS NOT (
    SELECT task_id FROM task_nodes WHERE node_id = NEW.node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Attempt run and TaskNode must belong to the same UserTask');
END;
"""

__all__ = ["SCHEMA_SQL"]
