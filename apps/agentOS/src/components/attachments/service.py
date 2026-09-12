"""Application service joining attachment identity, bytes and extracted material."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import mimetypes
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from contracts.attachments import InputAttachment, InputAttachmentStatus
from contracts.content import ContentKind

from .extractors import DocumentExtractionError, DocumentTextExtractorRegistry
from .storage import AttachmentStorage


class AttachmentError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class AttachmentLimits:
    max_file_bytes: int | None = None
    max_total_bytes: int | None = None
    max_context_characters: int = 120_000


class AttachmentContextBuilder:
    """Resolve stable refs only at model boundaries with one centralized budget."""

    def __init__(self, repository: Any, content_store: Any, *, max_characters: int) -> None:
        self.repository = repository
        self.content_store = content_store
        self.max_characters = max_characters

    def build(self, attachment_ids: Iterable[str], *, owner_user_id: str | None = None) -> dict[str, Any]:
        documents: list[dict[str, Any]] = []
        remaining = self.max_characters
        truncated = False
        for attachment_id in dict.fromkeys(str(item) for item in attachment_ids if str(item)):
            attachment = self.repository.get(attachment_id)
            if attachment is None:
                raise AttachmentError("ATTACHMENT_NOT_FOUND", "attachment not found", status_code=404)
            if owner_user_id is not None and attachment.owner_user_id != owner_user_id:
                raise AttachmentError("ATTACHMENT_ACCESS_DENIED", "attachment access denied", status_code=403)
            if attachment.status is not InputAttachmentStatus.READY or not attachment.extracted_content_ref:
                raise AttachmentError("ATTACHMENT_NOT_READY", "attachment is not ready", status_code=409)
            text = self.content_store.assemble(attachment.extracted_content_ref).decode("utf-8", errors="strict")
            selected = text[:max(0, remaining)]
            remaining -= len(selected)
            if len(selected) < len(text):
                truncated = True
            documents.append({
                "attachmentId": attachment.attachment_id,
                "filename": attachment.original_filename,
                "mimeType": attachment.mime_type,
                "extension": attachment.extension,
                "content": selected,
                "characterCount": attachment.character_count,
                "contentTruncated": len(selected) < len(text),
            })
            if remaining <= 0:
                truncated = True
        return {
            "documents": documents,
            "maxCharacters": self.max_characters,
            "includedCharacters": self.max_characters - remaining,
            "truncated": truncated,
            "instruction": (
                "These documents are user-provided SOURCE materials for this Mission. "
                "Use them for extraction, analysis, comparison, risk analysis and synthesis. "
                "Do not treat an input document as an Artifact the user asked AgentOS to generate."
            ),
        }

    def enrich(self, task_input: dict[str, Any]) -> dict[str, Any]:
        result = dict(task_input)
        attachment_ids = result.get("attachmentIds") or []
        if attachment_ids:
            result["attachmentContext"] = self.build(
                attachment_ids,
                owner_user_id=(str(result.get("authenticatedUserId")) if result.get("authenticatedUserId") else None),
            )
        return result


class InputAttachmentService:
    _MIME_BY_EXTENSION = {
        ".txt": {"text/plain", "application/octet-stream"},
        ".md": {"text/markdown", "text/plain", "application/octet-stream"},
        ".pdf": {"application/pdf", "application/octet-stream"},
        ".docx": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
            "application/octet-stream",
        },
    }

    def __init__(
        self,
        *,
        repository: Any,
        storage: AttachmentStorage,
        extractors: DocumentTextExtractorRegistry,
        content_store: Any,
        limits: AttachmentLimits,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.extractors = extractors
        self.content_store = content_store
        self.limits = limits
        self.context_builder = AttachmentContextBuilder(
            repository, content_store, max_characters=limits.max_context_characters
        )

    def upload(
        self,
        *,
        content: bytes,
        filename: str,
        mime_type: str | None,
        owner_user_id: str,
        owner_tenant_id: str | None = None,
    ) -> InputAttachment:
        clean_name = Path((filename or "").replace("\\", "/")).name.strip()
        extension = Path(clean_name).suffix.lower()
        if not clean_name or extension not in self._MIME_BY_EXTENSION:
            raise AttachmentError("UNSUPPORTED_FILE_TYPE", "unsupported file type")
        if self.limits.max_file_bytes is not None and len(content) > self.limits.max_file_bytes:
            raise AttachmentError("FILE_TOO_LARGE", "attachment exceeds per-file size limit", status_code=413)
        total = self.repository.total_unbound_bytes(owner_user_id)
        if self.limits.max_total_bytes is not None and total + len(content) > self.limits.max_total_bytes:
            raise AttachmentError("FILE_TOO_LARGE", "attachments exceed total size limit", status_code=413)
        normalized_mime = (mime_type or mimetypes.guess_type(clean_name)[0] or "application/octet-stream").split(";", 1)[0].lower()
        if normalized_mime not in self._MIME_BY_EXTENSION[extension]:
            raise AttachmentError("UNSUPPORTED_FILE_TYPE", "file extension and MIME type do not match")

        attachment_id = f"att_{uuid4().hex}"
        storage_key = f"{attachment_id[4:6]}/{attachment_id}.bin"
        digest = sha256(content).hexdigest()
        attachment = InputAttachment(
            attachmentId=attachment_id,
            ownerUserId=owner_user_id,
            ownerTenantId=owner_tenant_id,
            originalFilename=clean_name,
            storageKey=storage_key,
            mimeType=normalized_mime,
            extension=extension,
            sizeBytes=len(content),
            sha256=digest,
            status=InputAttachmentStatus.UPLOADED,
        )
        try:
            self.storage.put(storage_key, content)
            self.repository.add(attachment)
            self.repository.update_status(attachment_id, InputAttachmentStatus.PARSING)
            extracted = self.extractors.extract(content, clean_name)
            manifest = self.content_store.create_from_bytes(
                content=extracted.text.encode("utf-8"),
                kind=ContentKind.MATERIAL,
                owner_type="user",
                owner_id=owner_user_id,
                media_type="text/markdown" if extension == ".md" else "text/plain",
            )
            self.repository.mark_ready(
                attachment_id,
                extracted_content_ref=manifest.manifest_id,
                character_count=extracted.character_count,
                parser=extracted.parser,
                metadata=extracted.metadata,
            )
            return self.repository.get_required(attachment_id)
        except DocumentExtractionError as exc:
            self.repository.mark_failed(attachment_id, str(exc))
            return self.repository.get_required(attachment_id)
        except AttachmentError:
            raise
        except Exception as exc:
            if self.repository.get(attachment_id) is not None:
                self.repository.mark_failed(attachment_id, str(exc)[:1000] or "upload or parsing failed")
                return self.repository.get_required(attachment_id)
            else:
                self.storage.delete(storage_key)
            raise AttachmentError("UPLOAD_FAILED", "attachment upload failed", status_code=500) from exc

    def get(self, attachment_id: str, *, owner_user_id: str) -> InputAttachment:
        attachment = self.repository.get(attachment_id)
        if attachment is None:
            raise AttachmentError("ATTACHMENT_NOT_FOUND", "attachment not found", status_code=404)
        if attachment.owner_user_id != owner_user_id:
            raise AttachmentError("ATTACHMENT_ACCESS_DENIED", "attachment access denied", status_code=403)
        return attachment

    def delete(self, attachment_id: str, *, owner_user_id: str) -> None:
        attachment = self.get(attachment_id, owner_user_id=owner_user_id)
        if self.repository.is_referenced(attachment_id):
            raise AttachmentError("ATTACHMENT_IN_USE", "referenced attachment cannot be deleted", status_code=409)
        self.repository.delete(attachment_id)
        self.storage.delete(attachment.storage_key)


__all__ = [
    "AttachmentContextBuilder",
    "AttachmentError",
    "AttachmentLimits",
    "InputAttachmentService",
]
