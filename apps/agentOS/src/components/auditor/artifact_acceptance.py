"""Independent content checks and bounded excerpts of committed artifacts.

No model, filesystem path, executor claim or arbitrary reference authorizes a read.
The caller supplies an artifact descriptor from a previously validated node commit.
"""

import codecs
import json

from contracts.content import ContentKind
from contracts.artifacts import ArtifactCheck, ArtifactEvidence

def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


EXCERPT_BYTES = 2048
OBSERVATION_EXCERPT_BYTES = 8192
JSON_CHECK_BYTES = 262144


def inspect_artifact(*, store, artifact: dict, owner_id: str, commit_id: str,
                     excerpt_budget: int, review_resolved: bool) -> tuple[ArtifactEvidence, int]:
    manifest = store.get_manifest(artifact["manifestId"])
    if (manifest.owner_type != "run" or manifest.owner_id != owner_id
            or manifest.kind != ContentKind.ARTIFACT or not manifest.sealed
            or manifest.checksum != artifact.get("checksum")):
        raise ValueError("artifact manifest ownership or integrity does not match its commit")
    media = manifest.media_type.split(";", 1)[0].strip().lower()
    is_json = media == "application/json" or media.endswith("+json")
    is_text = media.startswith("text/") or is_json
    limit = min(EXCERPT_BYTES, max(0, excerpt_budget)) if is_text and review_resolved else 0
    preview = bytearray()
    json_body = bytearray() if is_json and manifest.byte_length <= JSON_CHECK_BYTES else None
    decoder = codecs.getincrementaldecoder("utf-8")("strict") if is_text else None
    valid_utf8, has_content, length = True, False, 0
    # Always drain the stream: its final checksum check cannot be skipped after
    # obtaining a preview. Only the preview/JSON buffers retain content.
    for chunk in store.stream_assembly(manifest.manifest_id):
        length += len(chunk)
        if len(preview) < limit:
            preview.extend(chunk[:limit - len(preview)])
        if json_body is not None:
            if length <= JSON_CHECK_BYTES:
                json_body.extend(chunk)
            else:
                json_body = None
        if decoder is not None and valid_utf8:
            try:
                has_content |= bool(decoder.decode(chunk).strip())
            except UnicodeDecodeError:
                valid_utf8 = False
        elif not is_text:
            has_content |= bool(chunk)
    if length != manifest.byte_length:
        raise ValueError("artifact byte length does not match its manifest")
    if decoder is not None and valid_utf8:
        try:
            has_content |= bool(decoder.decode(b"", final=True).strip())
        except UnicodeDecodeError:
            valid_utf8 = False
    checks = [ArtifactCheck(check="content_integrity", outcome="passed"),
              ArtifactCheck(check="nonempty_content", outcome="passed" if has_content else "failed")]
    if is_text:
        checks.append(ArtifactCheck(check="utf8_text", outcome="passed" if valid_utf8 else "failed"))
    if is_json:
        outcome = "unverified"
        if not valid_utf8:
            outcome = "failed"
        elif json_body is not None:
            try:
                json.loads(json_body.decode("utf-8"), parse_constant=_reject_json_constant)
                outcome = "passed"
            except (ValueError, UnicodeDecodeError):
                outcome = "failed"
            except RecursionError:
                pass  # Parser depth limit is not proof of invalid JSON.
        checks.append(ArtifactCheck(check="json_syntax", outcome=outcome))
    status = ("review_pending" if not review_resolved else "not_text" if not is_text
              else "invalid_encoding" if not valid_utf8 else "budget_exhausted" if not limit else "included")
    excerpt = bytes(preview).decode("utf-8", errors="ignore") if status == "included" else ""
    used = len(excerpt.encode("utf-8"))
    return ArtifactEvidence(
        sourceRunId=owner_id, commitId=commit_id, manifestId=manifest.manifest_id,
        checksum=manifest.checksum, mediaType=manifest.media_type, byteLength=length,
        checks=tuple(checks), excerpt=excerpt, excerptTruncated=used < length,
        excerptStatus=status,
    ), used
