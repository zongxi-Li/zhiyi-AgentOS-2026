"""Bounded strategy registry for P0 text-consumable documents."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from zipfile import ZipFile
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field


class DocumentExtractionError(ValueError):
    pass


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    text: str
    character_count: int = Field(alias="characterCount", ge=0)
    parser: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentTextExtractor(Protocol):
    extensions: tuple[str, ...]

    def extract(self, content: bytes, filename: str) -> ExtractedDocument: ...


class PlainTextExtractor:
    extensions = (".txt", ".md")

    def extract(self, content: bytes, filename: str) -> ExtractedDocument:
        if b"\x00" in content:
            raise DocumentExtractionError("text document contains binary NUL bytes")
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = content.decode(encoding)
                return ExtractedDocument(
                    text=text,
                    characterCount=len(text),
                    parser=f"plain-text:{encoding}",
                    metadata={"encoding": encoding, "format": Path(filename).suffix.lower()},
                )
            except UnicodeDecodeError:
                continue
        raise DocumentExtractionError("text document encoding is not supported")


class PdfTextExtractor:
    extensions = (".pdf",)

    def __init__(self, *, max_pages: int = 500) -> None:
        self.max_pages = max_pages

    def extract(self, content: bytes, filename: str) -> ExtractedDocument:
        if not content.startswith(b"%PDF-"):
            raise DocumentExtractionError("PDF signature is invalid")
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(BytesIO(content), strict=True)
            if len(reader.pages) > self.max_pages:
                raise DocumentExtractionError("PDF page limit exceeded")
            pages = [(page.extract_text() or "") for page in reader.pages]
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError("PDF parsing failed") from exc
        text = "\n\n".join(part for part in pages if part.strip())
        if not text.strip():
            raise DocumentExtractionError("PDF contains no extractable text; OCR is not supported")
        return ExtractedDocument(
            text=text,
            characterCount=len(text),
            parser="PyPDF2",
            metadata={"pages": len(pages), "format": "pdf"},
        )


class DocxTextExtractor:
    extensions = (".docx",)

    def __init__(
        self,
        *,
        max_uncompressed_bytes: int | None = None,
        max_members: int | None = None,
        max_compression_ratio: int | None = None,
    ) -> None:
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_members = max_members
        self.max_compression_ratio = max_compression_ratio

    def extract(self, content: bytes, filename: str) -> ExtractedDocument:
        if not content.startswith(b"PK"):
            raise DocumentExtractionError("DOCX ZIP signature is invalid")
        try:
            with ZipFile(BytesIO(content)) as archive:
                members = archive.infolist()
                if self.max_members is not None and len(members) > self.max_members:
                    raise DocumentExtractionError("DOCX archive member limit exceeded")
                total = sum(item.file_size for item in members)
                compressed = sum(max(1, item.compress_size) for item in members)
                names = {item.filename for item in members}
                if self.max_uncompressed_bytes is not None and total > self.max_uncompressed_bytes:
                    raise DocumentExtractionError("DOCX uncompressed size limit exceeded")
                if self.max_compression_ratio is not None and total > compressed * self.max_compression_ratio:
                    raise DocumentExtractionError("DOCX compression ratio limit exceeded")
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise DocumentExtractionError("DOCX package structure is invalid")
            # Read the document XML directly so parsing remains available when
            # python-docx is absent or the package contains unsupported parts.
            with ZipFile(BytesIO(content)) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            parts: list[str] = []
            for paragraph in root.iter(f"{namespace}p"):
                value = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
                if value:
                    parts.append(value)
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError("DOCX parsing failed") from exc
        text = "\n".join(parts)
        if not text.strip():
            raise DocumentExtractionError("DOCX contains no extractable text")
        return ExtractedDocument(
            text=text,
            characterCount=len(text),
            parser="python-docx",
            metadata={"paragraphs": len(parts), "format": "docx"},
        )


class DocumentTextExtractorRegistry:
    def __init__(self, extractors: tuple[DocumentTextExtractor, ...]) -> None:
        self._by_extension = {
            extension: extractor
            for extractor in extractors
            for extension in extractor.extensions
        }

    @property
    def supported_extensions(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_extension))

    def extract(self, content: bytes, filename: str) -> ExtractedDocument:
        extension = Path(filename).suffix.lower()
        extractor = self._by_extension.get(extension)
        if extractor is None:
            raise DocumentExtractionError(f"unsupported file type: {extension or '<none>'}")
        return extractor.extract(content, filename)


__all__ = [
    "DocumentExtractionError",
    "DocumentTextExtractor",
    "DocumentTextExtractorRegistry",
    "DocxTextExtractor",
    "ExtractedDocument",
    "PdfTextExtractor",
    "PlainTextExtractor",
]
