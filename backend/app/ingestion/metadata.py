"""Document metadata extraction.

Fixes README D2. Every policy in the corpus opens with a block the v1 pipeline threw away:

    # Customer Due Diligence (CDD) Policy
    **Version:** 2.1
    **Effective Date:** 1 January 2025
    **Owner:** MLRO
    **Review Cycle:** Annual

Four features depend on these fields — metadata filtering, version-aware answers, conflict
detection, and human-readable citations — so they are parsed into typed values here.
Anything absent stays null; nothing is inferred that the document does not state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.models import DocumentType

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
# Matches "**Version:** 2.1", "Version: 2.1", "**Effective Date**: 1 January 2025"
_FIELD = re.compile(
    r"^\s*(?:\*\*)?(?P<key>[A-Za-z][A-Za-z /]{2,30}?)(?:\*\*)?\s*:\s*(?:\*\*)?(?P<value>.+?)(?:\*\*)?\s*$",
    re.MULTILINE,
)
_VERSION_IN_NAME = re.compile(r"[_\-\s]v(?P<v>\d+(?:\.\d+)*)", re.IGNORECASE)

_DATE_FORMATS = (
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
)

_TYPE_KEYWORDS: list[tuple[str, DocumentType]] = [
    ("procedure", "procedure"),
    ("guideline", "guideline"),
    ("guidelines", "guideline"),
    ("standard", "standard"),
    ("standards", "standard"),
    ("framework", "framework"),
    ("policy", "policy"),
]


@dataclass
class DocumentMetadata:
    title: str
    doc_type: DocumentType = "other"
    version: str | None = None
    effective_date: date | None = None
    publication_date: date | None = None
    owner: str | None = None
    review_cycle: str | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)

    @property
    def family_key(self) -> str:
        """Identifies 'the same document, different version' for conflict detection."""
        base = re.sub(r"\s+v?\d+(\.\d+)*$", "", self.title.strip(), flags=re.IGNORECASE)
        return base.strip().lower()


def parse_date(value: str) -> date | None:
    cleaned = value.strip().strip("*").strip()
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", cleaned, flags=re.IGNORECASE)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    match = re.search(r"(19|20)\d{2}", cleaned)
    if match:
        try:
            return date(int(match.group(0)), 1, 1)
        except ValueError:
            return None
    return None


def infer_doc_type(title: str, filename: str) -> DocumentType:
    haystack = f"{title} {filename}".lower()
    for keyword, doc_type in _TYPE_KEYWORDS:
        if keyword in haystack:
            return doc_type
    return "other"


def title_from_filename(filename: str) -> str:
    """Fallback when the document has no H1: '02_source_of_wealth.md' → 'Source Of Wealth'."""
    stem = Path(filename).stem
    stem = re.sub(r"^\d+[_\-\s]*", "", stem)
    return re.sub(r"[_\-]+", " ", stem).strip().title() or filename


def extract_metadata(text: str, filename: str, *, header_scan_chars: int = 2500) -> DocumentMetadata:
    """Parse the document header. Only the first `header_scan_chars` are scanned so a
    `**Version:**` mentioned in the body cannot be mistaken for the document's own version."""
    header = text[:header_scan_chars]

    h1 = _H1.search(header)
    title = h1.group(1).strip() if h1 else title_from_filename(filename)
    title = re.sub(r"\s+", " ", title)

    fields: dict[str, str] = {}
    for match in _FIELD.finditer(header):
        key = match.group("key").strip().lower().replace(" ", "_")
        value = match.group("value").strip().strip("*").strip()
        if value and key not in fields:
            fields[key] = value

    version = fields.get("version")
    if version:
        version = version.lstrip("vV").strip()
    if not version:
        name_match = _VERSION_IN_NAME.search(Path(filename).stem)
        if name_match:
            version = name_match.group("v")

    effective = fields.get("effective_date") or fields.get("effective")
    published = (
        fields.get("publication_date")
        or fields.get("published")
        or fields.get("date")
        or fields.get("issue_date")
    )

    return DocumentMetadata(
        title=title,
        doc_type=infer_doc_type(title, filename),
        version=version,
        effective_date=parse_date(effective) if effective else None,
        publication_date=parse_date(published) if published else None,
        owner=fields.get("owner"),
        review_cycle=fields.get("review_cycle") or fields.get("review"),
        raw_fields=fields,
    )
