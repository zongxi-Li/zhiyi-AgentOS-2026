"""新一代 ACG 六级身份链的独立 Schema。"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS semantic_tasks (
    task_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    parent_task_id TEXT,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    constraints_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (task_id, mission_id),
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_task_id, mission_id)
        REFERENCES semantic_tasks(task_id, mission_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS task_plans (
    mission_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL CHECK (plan_version >= 1),
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (mission_id, plan_version),
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS task_plan_nodes (
    mission_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    semantic_key TEXT NOT NULL,
    task_id TEXT,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (mission_id, plan_version, semantic_key),
    FOREIGN KEY (mission_id, plan_version)
        REFERENCES task_plans(mission_id, plan_version) ON DELETE RESTRICT,
    FOREIGN KEY (task_id) REFERENCES semantic_tasks(task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS task_plan_relations (
    mission_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    target_key TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN ('parent', 'depends_on')),
    PRIMARY KEY (mission_id, plan_version, source_key, target_key, relation_type),
    FOREIGN KEY (mission_id, plan_version)
        REFERENCES task_plans(mission_id, plan_version) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS acg_blueprints (
    blueprint_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    graph_id TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (mission_id, version),
    UNIQUE (blueprint_id, mission_id),
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS workflow_runs_v2 (
    run_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    blueprint_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'failed', 'succeeded', 'cancelled', 'superseded'
    )),
    graph_version INTEGER NOT NULL CHECK (graph_version >= 1),
    checkpoint_json TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, mission_id),
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE RESTRICT,
    FOREIGN KEY (blueprint_id, mission_id)
        REFERENCES acg_blueprints(blueprint_id, mission_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'failed', 'succeeded', 'cancelled'
    )),
    started_at TEXT,
    finished_at TEXT,
    failure_reason TEXT,
    resource_binding_json TEXT,
    UNIQUE (run_id, task_id, attempt_number),
    UNIQUE (attempt_id, run_id, task_id),
    FOREIGN KEY (run_id) REFERENCES workflow_runs_v2(run_id) ON DELETE RESTRICT,
    FOREIGN KEY (task_id) REFERENCES semantic_tasks(task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS step_executions (
    step_execution_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'failed', 'succeeded', 'cancelled'
    )),
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (attempt_id, run_id, task_id)
        REFERENCES attempts(attempt_id, run_id, task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS task_bindings (
    binding_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    blueprint_id TEXT NOT NULL,
    acg_node_id TEXT NOT NULL,
    binding_type TEXT NOT NULL CHECK (binding_type IN ('primary', 'supporting')),
    created_at TEXT NOT NULL,
    UNIQUE (task_id, blueprint_id, acg_node_id),
    FOREIGN KEY (task_id) REFERENCES semantic_tasks(task_id) ON DELETE RESTRICT,
    FOREIGN KEY (blueprint_id) REFERENCES acg_blueprints(blueprint_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS blueprint_node_bindings (
    binding_id TEXT PRIMARY KEY,
    blueprint_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN (
        'dependency', 'communication', 'control'
    )),
    UNIQUE (blueprint_id, source_node_id, target_node_id, relation_type),
    FOREIGN KEY (blueprint_id) REFERENCES acg_blueprints(blueprint_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS execution_bindings (
    binding_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    acg_node_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS provenance_links (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, relation_type)
);

CREATE TABLE IF NOT EXISTS lifecycle_projection_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'applied', 'failed')),
    attempts INTEGER NOT NULL CHECK (attempts >= 1),
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lifecycle_inbox (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'applied', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_semantic_tasks_mission ON semantic_tasks(mission_id);
CREATE INDEX IF NOT EXISTS idx_blueprints_mission ON acg_blueprints(mission_id, version);
CREATE INDEX IF NOT EXISTS idx_runs_v2_mission ON workflow_runs_v2(mission_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attempts_run ON attempts(run_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_step_executions_attempt ON step_executions(attempt_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_step_execution_attempt ON step_executions(attempt_id);
CREATE INDEX IF NOT EXISTS idx_task_bindings_task ON task_bindings(task_id, blueprint_id);
CREATE INDEX IF NOT EXISTS idx_task_bindings_acg ON task_bindings(acg_node_id, blueprint_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_task_bindings_primary_acg
    ON task_bindings(blueprint_id, acg_node_id)
    WHERE binding_type = 'primary';
CREATE INDEX IF NOT EXISTS idx_execution_bindings_attempt ON execution_bindings(attempt_id);
CREATE INDEX IF NOT EXISTS idx_provenance_links_target ON provenance_links(target_id);
CREATE INDEX IF NOT EXISTS idx_projection_events_status
    ON lifecycle_projection_events(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_lifecycle_inbox_status
    ON lifecycle_inbox(status, updated_at);

CREATE TRIGGER IF NOT EXISTS attempts_require_same_mission
BEFORE INSERT ON attempts
FOR EACH ROW
WHEN (
    SELECT mission_id FROM workflow_runs_v2 WHERE run_id = NEW.run_id
) IS NOT (
    SELECT mission_id FROM semantic_tasks WHERE task_id = NEW.task_id
)
BEGIN
    SELECT RAISE(ABORT, 'Attempt run and SemanticTask must belong to the same Mission');
END;

CREATE TRIGGER IF NOT EXISTS task_binding_requires_same_mission
BEFORE INSERT ON task_bindings
FOR EACH ROW
WHEN (
    SELECT mission_id FROM semantic_tasks WHERE task_id = NEW.task_id
) IS NOT (
    SELECT mission_id FROM acg_blueprints WHERE blueprint_id = NEW.blueprint_id
)
BEGIN
    SELECT RAISE(ABORT, 'TaskBinding identities must belong to the same Mission');
END;

CREATE TRIGGER IF NOT EXISTS execution_binding_requires_realization
BEFORE INSERT ON execution_bindings
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM attempts a
    JOIN workflow_runs_v2 r ON r.run_id = a.run_id
    JOIN task_bindings b
      ON b.task_id = a.task_id
     AND b.blueprint_id = r.blueprint_id
     AND b.acg_node_id = NEW.acg_node_id
    WHERE a.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'ExecutionBinding requires a matching TaskBinding');
END;
"""

__all__ = ["SCHEMA_SQL"]
