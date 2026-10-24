"""Intake safety gate (SRS-005, AT-002, AT-041): detect real media type from bytes, bound sizes, and
reject encrypted / macro-bearing / archive-bomb / path-traversal / XXE-bearing files BEFORE parsing.
Nothing here executes file content.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

import defusedxml.ElementTree as DET
from defusedxml import DefusedXmlException

MAX_BYTES = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ZIP_RATIO = 100  # per-entry uncompressed/compressed
MAX_XML_PART_BYTES = 50 * 1024 * 1024

OOXML = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
MACRO_MARKERS = ("vbaproject.bin", "vbadata.xml", "macrosheets/", "xl/macrosheets", "activex/", "embeddings/")
MACRO_CT = ("macroenabled", "vnd.ms-office.vbaproject")


class Rejected(Exception):
    """Upload refused; `code` is machine-readable, message is actionable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Detected:
    kind: str                       # text|csv|docx|xlsx|pptx|pdf|image
    media_type: str
    notes: list[str] = field(default_factory=list)


def _looks_text(b: bytes) -> bool:
    if b"\x00" in b[:4096]:
        return False
    try:
        b[:65536].decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        # tolerate a multibyte char cut at the sample boundary only
        return e.start >= len(b[:65536]) - 3 and len(b) > 65536


def _check_zip(b: bytes) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
    except zipfile.BadZipFile as e:
        raise Rejected("MALFORMED", f"corrupt archive: {e}")
    infos = z.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise Rejected("ARCHIVE_LIMIT", f"too many archive entries ({len(infos)} > {MAX_ZIP_ENTRIES})")
    total = 0
    for i in infos:
        name = i.filename
        if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or ":" in name.split("/")[0]:
            raise Rejected("PATH_TRAVERSAL", f"unsafe archive entry name: {name!r}")
        if i.flag_bits & 0x1:
            raise Rejected("ENCRYPTED", "password-protected/encrypted archive is not supported; remove the password and re-upload")
        total += i.file_size
        if i.file_size > MAX_XML_PART_BYTES:
            raise Rejected("ARCHIVE_LIMIT", f"entry {name!r} too large when expanded")
        if i.compress_size > 0 and i.file_size / i.compress_size > MAX_ZIP_RATIO and i.file_size > 1_000_000:
            raise Rejected("ARCHIVE_BOMB", f"suspicious compression ratio in {name!r}")
        if total > MAX_ZIP_UNCOMPRESSED:
            raise Rejected("ARCHIVE_LIMIT", "archive expands beyond the allowed size")
    return z


def _check_macros(z: zipfile.ZipFile) -> None:
    names = [n.lower() for n in z.namelist()]
    if any(any(m in n for m in MACRO_MARKERS[:4]) for n in names):
        raise Rejected("MACROS", "file contains macros/VBA; macros are never run. Re-save without macros (e.g. .docx/.xlsx)")
    if "[Content_Types].xml" in z.namelist():
        ct = z.read("[Content_Types].xml").decode("utf-8", "ignore").lower()
        if any(m in ct for m in MACRO_CT):
            raise Rejected("MACROS", "macro-enabled content type is not accepted")
    if any(n.startswith("ppt/embeddings/") and n.endswith((".exe", ".dll", ".bat", ".js", ".vbs")) for n in names):
        raise Rejected("EMBEDDED_EXECUTABLE", "embedded executable content refused")


def _check_xml_safe(z: zipfile.ZipFile) -> None:
    """Parse every XML part with defusedxml: DTD/entity (XXE, billion laughs) are refused."""
    for n in z.namelist():
        if n.endswith((".xml", ".rels")):
            try:
                DET.fromstring(z.read(n), forbid_dtd=True)
            except DefusedXmlException:
                raise Rejected("XML_UNSAFE", f"unsafe XML construct (DTD/entity) in {n}")
            except Exception as e:
                raise Rejected("MALFORMED", f"malformed XML part {n}: {type(e).__name__}")


def detect(data: bytes, declared_name: str) -> Detected:
    """Return detected type or raise Rejected. Extension is only a hint; bytes decide."""
    if len(data) == 0:
        raise Rejected("EMPTY", "file is empty")
    if len(data) > MAX_BYTES:
        raise Rejected("TOO_LARGE", f"file exceeds {MAX_BYTES // (1024 * 1024)} MB limit")
    ext = declared_name.rsplit(".", 1)[-1].lower() if "." in declared_name else ""
    head = data[:8]
    if head.startswith(b"%PDF"):
        if b"/Encrypt" in data[-4096:] or b"/Encrypt" in data[:4096]:
            raise Rejected("ENCRYPTED", "encrypted PDF is not supported; upload an unencrypted copy")
        return Detected("pdf", "application/pdf")
    if head.startswith(b"\x89PNG"):
        return Detected("image", "image/png")
    if head[:3] == b"\xff\xd8\xff":
        return Detected("image", "image/jpeg")
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return Detected("image", "image/tiff")
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise Rejected("UNSUPPORTED_LEGACY_OR_ENCRYPTED",
                       "legacy OLE Office file (.doc/.xls/.ppt) or encrypted Office file is not supported; save as .docx/.xlsx/.pptx")
    if head.startswith(b"PK\x03\x04"):
        z = _check_zip(data)
        _check_macros(z)
        names = set(z.namelist())
        for kind, marker in OOXML.items():
            if marker in names:
                _check_xml_safe(z)
                mt = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}[kind]
                notes = [] if ext in ("", kind) else [f"declared extension .{ext} differs from detected {kind}"]
                return Detected(kind, mt, notes)
        raise Rejected("UNSUPPORTED_ARCHIVE", "ZIP archive is not a supported Office document")
    if head.startswith((b"MZ", b"\x7fELF", b"#!")):
        raise Rejected("EXECUTABLE", "executable content is refused")
    if _looks_text(data):
        kind = "csv" if ext in ("csv", "tsv") else "text"
        return Detected(kind, "text/csv" if kind == "csv" else "text/plain",
                        [] if ext in ("", "txt", "md", "csv", "tsv", "markdown") else
                        [f"declared extension .{ext} treated as plain text"])
    raise Rejected("UNSUPPORTED_TYPE", "unrecognized or binary file type; supported: text/Markdown, CSV, DOCX, XLSX, PPTX, PDF, PNG/JPEG/TIFF")
