"""Body metadata and content-addressed files; execution_values retains receipt identity."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

DEFAULT_INLINE_BYTES = 256 * 1024
BODY_MAGIC = b"ZHIYI-EXECUTION-BODY-V1\n"


def initialize(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS execution_value_storage (
            reference TEXT PRIMARY KEY, run_id TEXT NOT NULL, byte_length INTEGER NOT NULL,
            checksum TEXT NOT NULL, content_type TEXT NOT NULL, binary_bytes INTEGER NOT NULL,
            content_ref TEXT, state TEXT NOT NULL DEFAULT 'online'
                CHECK(state IN ('online','archived','deletable')),
            archived_at REAL, pins_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS execution_values_run_age ON execution_values(run_id,created_at);
        CREATE INDEX IF NOT EXISTS execution_values_run_kind_ref ON execution_values(run_id,kind,reference);
        CREATE INDEX IF NOT EXISTS execution_values_run_step_ref ON execution_values(run_id,step_id,reference);
        CREATE INDEX IF NOT EXISTS execution_value_storage_run ON execution_value_storage(run_id,state);
        CREATE INDEX IF NOT EXISTS execution_value_storage_run_checksum ON execution_value_storage(run_id,checksum);
        CREATE INDEX IF NOT EXISTS execution_value_storage_body ON execution_value_storage(content_ref);
        CREATE TABLE IF NOT EXISTS execution_value_files (
            reference TEXT NOT NULL, content_ref TEXT NOT NULL, stored_bytes INTEGER NOT NULL,
            role TEXT NOT NULL, PRIMARY KEY(reference,content_ref)
        );
        CREATE INDEX IF NOT EXISTS execution_value_files_content ON execution_value_files(content_ref);
        CREATE INDEX IF NOT EXISTS acg_node_executions_run ON acg_node_executions(run_id,operation_id);
        CREATE INDEX IF NOT EXISTS acg_node_commits_run ON acg_node_commits(run_id,commit_id);
    """)


def body_root(connection):
    database = next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main")
    return Path(database).with_suffix(".bodies")


def body_path(connection, content_ref):
    # No paths from payloads, absolute paths, or symlink traversal.
    parts = str(content_ref).split("/")
    if len(parts) != 2 or any(len(p) != 64 or any(c not in "0123456789abcdef" for c in p) for p in parts):
        raise ValueError("invalid execution content reference")
    root = body_root(connection)
    target = root.joinpath(*parts)
    if any(is_link(path) for path in (target, *target.parents)):
        raise ValueError("execution content path must not follow links")
    return target


def is_link(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def receipt_projection(payload):
    projection = {key: payload[key] for key in ("identity", "record", "commitId", "requestHash") if key in payload}
    if isinstance(payload.get("request"), dict):
        projection["request"] = {key: payload["request"][key] for key in
            ("capabilityId", "invocationId") if key in payload["request"]}
    if isinstance(payload.get("response"), dict):
        projection["response"] = {"requestId": payload["response"].get("requestId")}
    return projection


def binary_size(value):
    """Count explicitly encoded binary content, never guess arbitrary strings as base64."""
    if isinstance(value, list):
        return sum(binary_size(item) for item in value)
    if not isinstance(value, dict):
        return 0
    encoded = value.get("encoding") == "base64" or value.get("binary") is True
    count = 0
    for key, item in value.items():
        if isinstance(item, str) and (key in {"base64", "contentBase64", "dataBase64"}
                or encoded and key in {"content", "data", "body"}):
            count += len(item.encode("utf-8"))
        else:
            count += binary_size(item)
    return count


def write_file(connection, run_id, checksum, data, *, verify=True):
    content_ref = hashlib.sha256(run_id.encode()).hexdigest() + "/" + checksum
    target = body_path(connection, content_ref)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if verify and hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
            raise ValueError("execution body part integrity failure")
        return content_ref
    descriptor, temporary = tempfile.mkstemp(prefix=".body-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return content_ref


def read_body(connection, content_ref):
    data = body_path(connection, content_ref).read_bytes()
    if not data.startswith(BODY_MAGIC):
        return data
    manifest = json.loads(data[len(BODY_MAGIC):])
    encoded = manifest["encoded"]
    namespace = content_ref.split("/")[0]
    for part in manifest["parts"]:
        if part["ref"].split("/")[0] != namespace:
            raise ValueError("execution body part owner mismatch")
        chunk = body_path(connection, part["ref"]).read_bytes()
        if hashlib.sha256(chunk).hexdigest() != part["ref"].split("/")[1]:
            raise ValueError("execution body part integrity failure")
        encoded = encoded.replace(part["token"], chunk.decode("utf-8"))
    return encoded.encode("utf-8")


def write_body(connection, run_id, checksum, data):
    content_ref = hashlib.sha256(run_id.encode()).hexdigest() + "/" + checksum
    path = body_path(connection, content_ref)
    if path.exists():
        if read_body(connection, content_ref) != data:
            raise ValueError("execution content checksum mismatch")
        return content_ref
    encoded = data.decode("utf-8")
    strings = set()
    def find(value):
        if isinstance(value, str) and len(value.encode("utf-8")) >= 64*1024:
            strings.add(json.dumps(value, ensure_ascii=False))
            strings.add(json.dumps(value, ensure_ascii=True))
        elif isinstance(value, dict):
            for child in value.values():
                find(child)
        elif isinstance(value, list):
            for child in value:
                find(child)
    find(json.loads(data))
    parts = []
    for text in sorted(strings, key=lambda item: (-len(item), item)):
        if text not in encoded:
            continue
        chunk = text.encode("utf-8")
        digest = hashlib.sha256(chunk).hexdigest()
        token = "$execution-body:" + digest + "$"
        while token in encoded:
            token += "$"
        chunk_ref = write_file(connection, run_id, digest, chunk)
        parts.append({"token": token, "ref": chunk_ref})
        encoded = encoded.replace(text, token)
    packed = BODY_MAGIC + json.dumps({"encoded": encoded, "parts": parts},
        ensure_ascii=False, separators=(",", ":")).encode("utf-8") if parts else data
    write_file(connection, run_id, checksum, packed, verify=False)
    return content_ref


def store_body(connection, *, reference, run_id, encoded, threshold=DEFAULT_INLINE_BYTES):
    """Called in the value insertion transaction. Files precede committed DB pointers."""
    payload = json.loads(encoded)
    data = encoded.encode("utf-8")
    checksum = hashlib.sha256(data).hexdigest()
    binary_bytes = binary_size(payload)
    content_ref = write_body(connection, run_id, checksum, data) if len(data) >= threshold else None
    connection.execute("""INSERT INTO execution_value_storage
        (reference,run_id,byte_length,checksum,content_type,binary_bytes,content_ref)
        VALUES(?,?,?,?,?,?,?)""",
        (reference, run_id, len(data), checksum, "application/json", binary_bytes, content_ref))
    if content_ref is None:
        return encoded
    packed = body_path(connection, content_ref).read_bytes()
    connection.execute("INSERT INTO execution_value_files VALUES(?,?,?,?)",
        (reference, content_ref, len(packed), "manifest"))
    if packed.startswith(BODY_MAGIC):
        for part in json.loads(packed[len(BODY_MAGIC):])["parts"]:
            connection.execute("INSERT OR IGNORE INTO execution_value_files VALUES(?,?,?,?)",
                (reference, part["ref"], body_path(connection, part["ref"]).stat().st_size, "body"))
    # These fields support existing indexed closure/ownership SQL. Full validation
    # always decodes the checksummed body rather than treating this stub as evidence.
    return json.dumps(receipt_projection(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_body(connection, *, run_id, reference, encoded):
    owner = connection.execute("SELECT run_id FROM execution_values WHERE reference=?", (reference,)).fetchone()
    if owner is None or owner[0] != run_id:
        raise ValueError("execution content belongs to another Run")
    # Compatibility with unupgraded read-only database fixtures.
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='execution_value_storage'").fetchone():
        return json.loads(encoded)
    metadata = connection.execute("""SELECT run_id,byte_length,checksum,content_ref
        FROM execution_value_storage WHERE reference=?""", (reference,)).fetchone()
    if metadata is None:
        return json.loads(encoded)
    if metadata[0] != run_id:
        raise ValueError("execution content metadata owner mismatch")
    if metadata[3] and metadata[3] != hashlib.sha256(run_id.encode()).hexdigest() + "/" + metadata[2]:
        raise ValueError("execution content reference does not match its owner or checksum")
    data = read_body(connection, metadata[3]) if metadata[3] else encoded.encode("utf-8")
    if len(data) != metadata[1] or hashlib.sha256(data).hexdigest() != metadata[2]:
        raise ValueError("execution content integrity failure")
    payload = json.loads(data)
    if metadata[3] and json.loads(encoded) != receipt_projection(payload):
        raise ValueError("execution receipt projection does not match its body")
    return payload


def migrate(connection, *, run_id, limit=100, threshold=DEFAULT_INLINE_BYTES):
    """Bounded, restartable backfill. Never decode all Run bodies at startup."""
    if not 1 <= limit <= 10000:
        raise ValueError("migration limit must be 1..10000")
    connection.execute("BEGIN IMMEDIATE")
    try:
        rows = connection.execute("""SELECT v.reference,v.payload_json FROM execution_values v
            LEFT JOIN execution_value_storage s ON s.reference=v.reference
            WHERE v.run_id=? AND s.reference IS NULL ORDER BY v.reference LIMIT ?""",
            (run_id, limit)).fetchall()
        for reference, encoded in rows:
            stub = store_body(connection, reference=reference, run_id=run_id, encoded=encoded, threshold=threshold)
            if stub != encoded:
                connection.execute("UPDATE execution_values SET payload_json=? WHERE reference=? AND run_id=?",
                    (stub, reference, run_id))
        connection.commit()
        return len(rows)
    except BaseException:
        connection.rollback()
        raise


def usage(connection, *, run_id, since=None):
    cutoff = since.timestamp() if since is not None else None
    row = connection.execute("""SELECT COUNT(*),COALESCE(SUM(s.byte_length),0),
        COALESCE(MAX(s.byte_length),0),COALESCE(SUM(s.binary_bytes),0),
        COALESCE(SUM(CASE WHEN v.created_at>=? THEN s.byte_length ELSE 0 END),0)
        FROM execution_value_storage s JOIN execution_values v USING(reference)
        WHERE s.run_id=?""", (cutoff, run_id)).fetchone()
    total = connection.execute("SELECT COUNT(*) FROM execution_values WHERE run_id=?", (run_id,)).fetchone()[0]
    unique = connection.execute("""SELECT COALESCE(SUM(bytes),0) FROM
        (SELECT MAX(byte_length) bytes FROM execution_value_storage WHERE run_id=? GROUP BY checksum)""",
        (run_id,)).fetchone()[0]
    states = dict(connection.execute("SELECT state,COUNT(*) FROM execution_value_storage WHERE run_id=? GROUP BY state",
        (run_id,)).fetchall())
    file_rows = connection.execute("""SELECT f.content_ref,f.stored_bytes,f.role FROM execution_value_files f
        JOIN execution_value_storage s USING(reference) WHERE s.run_id=?""", (run_id,)).fetchall()
    files = {reference: size for reference, size, _ in file_rows}
    body_bytes = sum(size for _, size, role in file_rows if role == "body")
    unique_body_bytes = sum({reference: size for reference, size, role in file_rows if role == "body"}.values())
    largest = connection.execute("""SELECT reference,byte_length,content_type FROM execution_value_storage
        WHERE run_id=? ORDER BY byte_length DESC,reference LIMIT 1""", (run_id,)).fetchone()
    return {"runId": run_id, "records": total, "measuredRecords": row[0], "unmeasuredRecords": total-row[0],
        "logicalBytes": row[1], "largestBytes": row[2], "encodedBinaryBytes": row[3],
        "encodedBinaryRatio": row[3]/row[1] if row[1] else 0,
        "uniquePayloadBytes": unique, "duplicatePayloadBytes": row[1]-unique,
        "growthBytes": row[4] if cutoff is not None else None, "states": states,
        "externalStoredBytes": sum(files.values()), "externalFiles": len(files),
        "duplicateBodyBytes": body_bytes-unique_body_bytes,
        "largestRecord": {"reference": largest[0], "bytes": largest[1], "contentType": largest[2]} if largest else None}


def pin(connection, *, run_id, reference, owner, enabled=True):
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("pin owner is required")
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute("SELECT pins_json FROM execution_value_storage WHERE run_id=? AND reference=?",
            (run_id, reference)).fetchone()
        if row is None:
            raise ValueError("unknown execution content")
        pins = set(json.loads(row[0]))
        pins.add(owner) if enabled else pins.discard(owner)
        connection.execute("""UPDATE execution_value_storage SET pins_json=?,
            state=CASE WHEN ? THEN 'online' ELSE state END WHERE run_id=? AND reference=?""",
            (json.dumps(sorted(pins)), enabled, run_id, reference))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def collect_files(connection):
    """Only unreferenced files; serialize against all writers' DB transactions."""
    deleted = 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        root = body_root(connection)
        if any(is_link(path) for path in (root, *root.parents)):
            raise ValueError("execution body root must not follow links")
        if root.exists():
            retained = {row[0] for row in connection.execute("SELECT DISTINCT content_ref FROM execution_value_files")}
            for folder in root.iterdir():
                if is_link(folder) or not folder.is_dir():
                    continue
                for candidate in folder.iterdir():
                    content_ref = folder.name + "/" + candidate.name
                    if is_link(candidate) or not candidate.is_file():
                        continue
                    if candidate.name.startswith(".body-"):
                        continue  # Interrupted writes are not published content.
                    checked = body_path(connection, content_ref)
                    if content_ref not in retained:
                        checked.unlink()
                        deleted += 1
        connection.commit()
        return deleted
    except BaseException:
        connection.rollback()
        raise


def transition(connection, *, run_id, references, state, protected_refs=(), terminal=False):
    """Lifecycle only; archived bodies remain resolvable and pins veto eligibility."""
    if state not in {"online", "archived", "deletable"}:
        raise ValueError("invalid storage state")
    protected = set(protected_refs)
    connection.execute("BEGIN IMMEDIATE")
    try:
        for reference in set(references):
            row = connection.execute("""SELECT state,pins_json FROM execution_value_storage
                WHERE reference=? AND run_id=?""", (reference, run_id)).fetchone()
            if row is None:
                raise ValueError("unknown execution content")
            if state == "deletable" and (not terminal or row[0] != "archived"
                    or reference in protected or json.loads(row[1])):
                raise ValueError("execution content remains protected")
            connection.execute("""UPDATE execution_value_storage SET state=?,
                archived_at=CASE WHEN ?='archived' THEN COALESCE(archived_at,?) ELSE archived_at END
                WHERE reference=? AND run_id=?""",
                (state, state, datetime.now(timezone.utc).timestamp(), reference, run_id))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
