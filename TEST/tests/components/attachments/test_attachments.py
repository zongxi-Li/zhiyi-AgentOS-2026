from __future__ import annotations

from io import BytesIO

import pytest

from components.attachments import (
    AttachmentError,
    AttachmentLimits,
    DocumentTextExtractorRegistry,
    DocxTextExtractor,
    InputAttachmentService,
    LocalAttachmentStorage,
    PdfTextExtractor,
    PlainTextExtractor,
)
from components.content import SQLiteContentManifestStore
from components.content import ContentWorksetSession
from components.planner.task_decomposer import TaskDecomposer
from contracts.attachments import InputAttachmentStatus
from support.acg.models import ComplexityLevel, TaskSemanticProfile, build_default_capability_catalog
from storage.v2 import SQLiteV2Repositories, SQLiteV2Storage


def _service(tmp_path, *, max_file_bytes=1024 * 1024, max_total_bytes=2 * 1024 * 1024):
    repositories = SQLiteV2Repositories(SQLiteV2Storage(tmp_path / "identity.sqlite3"))
    content = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    storage = LocalAttachmentStorage(tmp_path / "attachments")
    service = InputAttachmentService(
        repository=repositories.input_attachments,
        storage=storage,
        extractors=DocumentTextExtractorRegistry((
            PlainTextExtractor(), PdfTextExtractor(), DocxTextExtractor(),
        )),
        content_store=content,
        limits=AttachmentLimits(
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
            max_context_characters=120,
        ),
    )
    return service, repositories, content, storage


def test_local_storage_put_read_delete_and_rejects_escape(tmp_path):
    storage = LocalAttachmentStorage(tmp_path / "files")
    storage.put("aa/att.bin", b"payload")
    assert storage.read("aa/att.bin") == b"payload"
    assert storage.exists("aa/att.bin")
    storage.delete("aa/att.bin")
    assert not storage.exists("aa/att.bin")
    with pytest.raises(ValueError):
        storage.put("../escape.bin", b"no")


@pytest.mark.parametrize(("filename", "content", "parser_prefix"), [
    ("notes.txt", "甲方：星河科技".encode(), "plain-text:"),
    ("readme.md", "# 合同\n金额 800000 元".encode(), "plain-text:"),
])
def test_text_and_markdown_upload_create_ready_identity_and_material(
    tmp_path, filename, content, parser_prefix
):
    service, repositories, manifest_store, storage = _service(tmp_path)
    attachment = service.upload(
        content=content,
        filename=f"../../{filename}",
        mime_type="text/plain",
        owner_user_id="user-1",
    )
    assert attachment.status is InputAttachmentStatus.READY
    assert attachment.original_filename == filename
    assert attachment.parser.startswith(parser_prefix)
    assert attachment.extracted_content_ref
    assert manifest_store.assemble(attachment.extracted_content_ref).decode() == content.decode()
    assert storage.read(attachment.storage_key) == content
    assert repositories.input_attachments.get(attachment.attachment_id) == attachment


def test_duplicate_files_receive_independent_stable_identities(tmp_path):
    service, *_ = _service(tmp_path)
    first = service.upload(content=b"same", filename="a.txt", mime_type="text/plain", owner_user_id="u")
    second = service.upload(content=b"same", filename="a.txt", mime_type="text/plain", owner_user_id="u")
    assert first.attachment_id != second.attachment_id
    assert first.sha256 == second.sha256


def test_pdf_and_docx_extractors(tmp_path):
    from PyPDF2 import PdfWriter
    from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject

    pdf_bytes = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    page = writer.pages[0]
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (contract amount 800000) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(pdf_bytes)

    from docx import Document
    document = Document()
    document.add_paragraph("payment 30 percent after signing")
    docx_bytes = BytesIO()
    document.save(docx_bytes)

    service, *_ = _service(tmp_path)
    pdf = service.upload(
        content=pdf_bytes.getvalue(), filename="contract.pdf", mime_type="application/pdf", owner_user_id="u"
    )
    word = service.upload(
        content=docx_bytes.getvalue(), filename="terms.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        owner_user_id="u",
    )
    assert pdf.status is InputAttachmentStatus.READY
    assert pdf.metadata["pages"] == 1
    assert word.status is InputAttachmentStatus.READY
    assert word.parser == "python-docx"


@pytest.mark.parametrize(("filename", "mime_type", "content"), [
    ("broken.pdf", "application/pdf", b"%PDF-not-a-real-document"),
    ("broken.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PKbroken"),
])
def test_corrupt_documents_persist_failed_status(tmp_path, filename, mime_type, content):
    service, repositories, *_ = _service(tmp_path)
    attachment = service.upload(
        content=content, filename=filename, mime_type=mime_type, owner_user_id="u"
    )
    assert attachment.status is InputAttachmentStatus.FAILED
    assert attachment.parse_error
    assert repositories.input_attachments.get(attachment.attachment_id).status is InputAttachmentStatus.FAILED


def test_type_and_size_limits_fail_closed(tmp_path):
    service, *_ = _service(tmp_path, max_file_bytes=4)
    with pytest.raises(AttachmentError) as unsupported:
        service.upload(content=b"x", filename="script.exe", mime_type="application/octet-stream", owner_user_id="u")
    assert unsupported.value.code == "UNSUPPORTED_FILE_TYPE"
    with pytest.raises(AttachmentError) as too_large:
        service.upload(content=b"12345", filename="large.txt", mime_type="text/plain", owner_user_id="u")
    assert too_large.value.code == "FILE_TOO_LARGE"

    total_service, *_ = _service(tmp_path / "total", max_file_bytes=4, max_total_bytes=6)
    total_service.upload(content=b"1234", filename="one.txt", mime_type="text/plain", owner_user_id="u")
    with pytest.raises(AttachmentError) as total_too_large:
        total_service.upload(content=b"567", filename="two.txt", mime_type="text/plain", owner_user_id="u")
    assert total_too_large.value.code == "FILE_TOO_LARGE"


def test_context_builder_is_bounded_and_labels_documents_as_sources(tmp_path):
    service, *_ = _service(tmp_path)
    attachment = service.upload(
        content=("contract " * 100).encode(), filename="contract.txt", mime_type="text/plain", owner_user_id="u"
    )
    context = service.context_builder.build([attachment.attachment_id], owner_user_id="u")
    assert context["truncated"] is True
    assert context["includedCharacters"] == 120
    assert "SOURCE" in context["instruction"]
    assert context["documents"][0]["attachmentId"] == attachment.attachment_id
    second = service.upload(
        content=b"second document", filename="second.txt", mime_type="text/plain", owner_user_id="u"
    )
    multi = service.context_builder.build(
        [attachment.attachment_id, second.attachment_id], owner_user_id="u"
    )
    assert [item["attachmentId"] for item in multi["documents"]] == [
        attachment.attachment_id, second.attachment_id
    ]
    assert multi["documents"][1]["content"] == ""
    assert multi["documents"][1]["contentTruncated"] is True


def test_referenced_attachment_cannot_be_deleted(tmp_path):
    service, repositories, *_ = _service(tmp_path)
    attachment = service.upload(content=b"contract", filename="a.txt", mime_type="text/plain", owner_user_id="u")
    mission = __import__("domain.models", fromlist=["Mission"]).Mission(userId="u", goal="review")
    repositories.missions.add(mission)
    repositories.input_attachments.bind_mission(mission.mission_id, [attachment.attachment_id])
    with pytest.raises(AttachmentError) as used:
        service.delete(attachment.attachment_id, owner_user_id="u")
    assert used.value.code == "ATTACHMENT_IN_USE"


def test_attachment_content_enters_planner_and_runtime_workset_without_node_copy(tmp_path):
    service, _, content_store, _ = _service(tmp_path)
    attachment = service.upload(
        content="合同金额：800000 元。验收后支付 70%。".encode("utf-8"),
        filename="contract.txt",
        mime_type="text/plain",
        owner_user_id="u",
    )
    task_input = {
        "attachmentIds": [attachment.attachment_id],
        "materialRefs": [attachment.extracted_content_ref],
        "attachmentContext": service.context_builder.build(
            [attachment.attachment_id], owner_user_id="u"
        ),
    }
    profile = TaskSemanticProfile(
        primaryGoal="审查合同并生成风险报告",
        requiredCapabilities=["task_understanding", "analysis", "artifact_generation"],
        estimatedComplexity=ComplexityLevel.COMPLEX,
    )
    decomposer = TaskDecomposer(build_default_capability_catalog(), None)
    prompt = decomposer.build_prompt(profile=profile, task_input=task_input)
    assert "contract.txt" in prompt
    assert "800000" in prompt
    assert "SOURCE" in prompt

    plan = decomposer.decompose(
        mission_id="mission_0123456789ab",
        profile=profile,
        strategy="dynamic_generation",
        task_input=task_input,
        use_llm=False,
    )
    source_node = next(node for node in plan.nodes if node.workset is not None)
    assert source_node.workset.source_manifest_refs == (attachment.extracted_content_ref,)
    assert "800000" not in source_node.model_dump_json(by_alias=True)

    session = ContentWorksetSession(
        store=content_store,
        spec=source_node.workset,
        run_id="run_0123456789ab",
        step_id=source_node.key,
        commit_id="commit-contract",
    )
    units = list(session.pending_units())
    assert units and "800000" in units[0]["content"]
