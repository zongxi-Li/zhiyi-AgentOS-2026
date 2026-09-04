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
    semantic_key TEXT,
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

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    origin_run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    semantic_task_key TEXT NOT NULL,
    artifact_key TEXT NOT NULL,
    acg_node_id TEXT NOT NULL,
    producer_attempt_id TEXT NOT NULL,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    media_type TEXT NOT NULL,
    content_ref TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE RESTRICT,
    FOREIGN KEY (origin_run_id) REFERENCES workflow_runs_v2(run_id) ON DELETE RESTRICT,
    FOREIGN KEY (task_id) REFERENCES semantic_tasks(task_id) ON DELETE RESTRICT,
    FOREIGN KEY (producer_attempt_id, origin_run_id, task_id)
        REFERENCES attempts(attempt_id, run_id, task_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS run_artifact_bindings (
    binding_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    semantic_task_key TEXT NOT NULL,
    artifact_key TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('GENERATED', 'REUSED')),
    source_run_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, semantic_task_key, artifact_key),
    FOREIGN KEY (run_id) REFERENCES workflow_runs_v2(run_id) ON DELETE RESTRICT,
    FOREIGN KEY (task_id) REFERENCES semantic_tasks(task_id) ON DELETE RESTRICT,
    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_run_id) REFERENCES workflow_runs_v2(run_id) ON DELETE RESTRICT
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_semantic_tasks_mission_key
    ON semantic_tasks(mission_id, semantic_key)
    WHERE semantic_key IS NOT NULL;
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
CREATE INDEX IF NOT EXISTS idx_artifacts_mission ON artifacts(mission_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_origin_run ON artifacts(origin_run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, artifact_key, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_attempt ON artifacts(producer_attempt_id);
CREATE INDEX IF NOT EXISTS idx_run_artifact_bindings_run
    ON run_artifact_bindings(run_id, semantic_task_key, artifact_key);
CREATE INDEX IF NOT EXISTS idx_run_artifact_bindings_artifact
    ON run_artifact_bindings(artifact_id, created_at);
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

CREATE TRIGGER IF NOT EXISTS task_plan_node_requires_same_mission
BEFORE INSERT ON task_plan_nodes
FOR EACH ROW
WHEN NEW.task_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM semantic_tasks t
    WHERE t.task_id = NEW.task_id
      AND t.mission_id = NEW.mission_id
)
BEGIN
    SELECT RAISE(ABORT, 'TaskPlan node and SemanticTask must belong to the same Mission');
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

CREATE TRIGGER IF NOT EXISTS artifact_requires_complete_identity
BEFORE INSERT ON artifacts
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM attempts a
    JOIN workflow_runs_v2 r ON r.run_id = a.run_id
    JOIN semantic_tasks t ON t.task_id = a.task_id
    JOIN execution_bindings eb ON eb.attempt_id = a.attempt_id
    JOIN task_bindings tb
      ON tb.task_id = a.task_id
     AND tb.blueprint_id = r.blueprint_id
     AND tb.acg_node_id = NEW.acg_node_id
    WHERE a.attempt_id = NEW.producer_attempt_id
      AND a.run_id = NEW.origin_run_id
      AND a.task_id = NEW.task_id
      AND r.mission_id = NEW.mission_id
      AND t.mission_id = NEW.mission_id
      AND t.semantic_key = NEW.semantic_task_key
      AND eb.acg_node_id = NEW.acg_node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Artifact producer identity does not match Attempt, Run, SemanticTask and ACG binding');
END;

CREATE TRIGGER IF NOT EXISTS artifact_immutable_update
BEFORE UPDATE ON artifacts
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Artifact is immutable');
END;

CREATE TRIGGER IF NOT EXISTS run_artifact_binding_requires_consistency
BEFORE INSERT ON run_artifact_bindings
FOR EACH ROW
WHEN (
    NOT EXISTS (
        SELECT 1
        FROM workflow_runs_v2 r
        JOIN artifacts a ON a.artifact_id = NEW.artifact_id
        JOIN semantic_tasks t ON t.task_id = NEW.task_id
        WHERE r.run_id = NEW.run_id
          AND r.mission_id = a.mission_id
          AND t.mission_id = r.mission_id
          AND t.semantic_key = NEW.semantic_task_key
          AND a.task_id = NEW.task_id
          AND a.semantic_task_key = NEW.semantic_task_key
          AND a.artifact_key = NEW.artifact_key
    )
    OR (NEW.disposition = 'GENERATED' AND NEW.source_run_id IS NOT NULL)
    OR (NEW.disposition = 'REUSED' AND NEW.source_run_id IS NULL)
    OR (NEW.disposition = 'REUSED' AND NEW.source_run_id = NEW.run_id)
    OR (
        NEW.disposition = 'GENERATED'
        AND NEW.run_id <> (SELECT origin_run_id FROM artifacts WHERE artifact_id = NEW.artifact_id)
    )
    OR (
        NEW.disposition = 'REUSED'
        AND NOT EXISTS (
            SELECT 1
            FROM run_artifact_bindings prior
            WHERE prior.run_id = NEW.source_run_id
              AND prior.semantic_task_key = NEW.semantic_task_key
              AND prior.artifact_key = NEW.artifact_key
              AND prior.artifact_id = NEW.artifact_id
        )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'RunArtifactBinding identity or disposition is inconsistent');
END;

CREATE TRIGGER IF NOT EXISTS run_artifact_binding_immutable_update
BEFORE UPDATE ON run_artifact_bindings
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'RunArtifactBinding is immutable');
END;
"""

__all__ = ["SCHEMA_SQL"]
