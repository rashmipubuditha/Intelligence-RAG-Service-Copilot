"""Structure-aware chunking.

The v1 strategy was already right for this corpus — split on `##`, sub-split on `###`, then
on paragraphs with overlap — and it is preserved. What changes is provenance.

v1 defect (README D1): when a long `##` section was sub-split on `###`, every child kept the
*parent* H2 as its section. Verified against the v1 index, chunks 11–15 of Policy 02 all
reported "3. Documentation Requirements by Category" while their bodies were §3.1–§3.5. The
labelled answer for the employment-income question is "Section 3.1", so the system could not
cite what the corpus actually supports.

Here each chunk carries the full heading path (H1 → H2 → H3), so a citation can read
"Source of Wealth Verification Guidelines v1.3 — §3.1 Employment / Salary".

Chunk identity (README D4) is content-derived rather than positional, so re-ingesting one
document does not renumber the corpus and saved citations stay valid.
"""

from __future__ import annotations

import hashlib
import re

from app.ingestion.cleaning import estimate_tokens
from app.ingestion.extractors import ExtractedDocument
from app.ingestion.metadata import DocumentMetadata
from app.models import Chunk, ChunkMetadata

H2_PATTERN = re.compile(r"^##\s+(?!#)(.+?)\s*$", re.MULTILINE)
H3_PATTERN = re.compile(r"^###\s+(?!#)(.+?)\s*$", re.MULTILINE)

# BGE-small truncates at 512 tokens. ~1.3 tokens per English word, so 300 words ≈ 390
# tokens — leaves headroom for the provenance header prepended to every chunk.
MAX_CHUNK_WORDS = 300
OVERLAP_WORDS = 60

# A subsection smaller than this is merged into its preceding sibling rather than becoming a
# chunk of its own: a 20-word fragment is a poor retrieval unit, and splitting that finely
# costs recall without buying useful provenance.
MIN_SUBSECTION_WORDS = 35


def _word_count(text: str) -> int:
    return len(text.split())


def _paragraph_split_with_overlap(
    text: str, max_words: int = MAX_CHUNK_WORDS, overlap_words: int = OVERLAP_WORDS
) -> list[str]:
    """Pack paragraphs up to max_words, carrying the tail of each chunk into the next.

    Overlap keeps a rule that straddles a paragraph boundary retrievable from either side.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = _word_count(para)
        if current and current_words + para_words > max_words:
            chunks.append("\n\n".join(current))
            overlap: list[str] = []
            overlap_words_count = 0
            for previous in reversed(current):
                pw = _word_count(previous)
                if overlap_words_count + pw <= overlap_words:
                    overlap.insert(0, previous)
                    overlap_words_count += pw
                else:
                    break
            current = [*overlap, para]
            current_words = sum(_word_count(x) for x in current)
        else:
            current.append(para)
            current_words += para_words

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_sections(text: str, pattern: re.Pattern[str]) -> list[tuple[str | None, str, int]]:
    """Split on a heading pattern.

    Returns (heading, body, offset). A preamble before the first heading is returned with
    heading=None so no content is ever dropped.
    """
    matches = list(pattern.finditer(text))
    if not matches:
        return [(None, text, 0)] if text.strip() else []

    out: list[tuple[str | None, str, int]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        out.append((None, preamble, 0))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            out.append((heading, body, start))
    return out


def format_chunk_text(heading_path: list[str], body: str) -> str:
    """Prepend provenance so the model sees where a passage came from, inline.

    This is also why a fabricated citation is doubly unlikely: the model is reading the real
    document and section name in the same block as the text.
    """
    trail = " > ".join(p for p in heading_path if p)
    header = f"[{trail}]" if trail else ""
    return f"{header}\n\n{body.strip()}".strip()


def chunk_document(
    *,
    document_id: str,
    filename: str,
    extracted: ExtractedDocument,
    cleaned_text: str,
    metadata: DocumentMetadata,
    starting_faiss_id: int,
) -> list[Chunk]:
    """Chunk one document into retrievable units with full provenance."""
    chunks: list[Chunk] = []
    index = 0

    def emit(body: str, section: str | None, subsection: str | None, offset: int) -> None:
        nonlocal index
        body = body.strip()
        if not body:
            return
        heading_path = [p for p in (metadata.title, section, subsection) if p]
        text = format_chunk_text(heading_path, body)
        page = extracted.page_for_offset(offset)
        chunk_uid = hashlib.sha256(
            f"{document_id}|{section or ''}|{subsection or ''}|{index}|{body[:200]}".encode()
        ).hexdigest()[:16]
        chunks.append(
            Chunk(
                chunk_uid=chunk_uid,
                faiss_id=starting_faiss_id + index,
                text=text,
                metadata=ChunkMetadata(
                    document_id=document_id,
                    document_name=filename,
                    document_title=metadata.title,
                    document_type=metadata.doc_type,
                    version=metadata.version,
                    effective_date=metadata.effective_date,
                    publication_date=metadata.publication_date,
                    owner=metadata.owner,
                    review_cycle=metadata.review_cycle,
                    section=section,
                    subsection=subsection,
                    heading_path=heading_path,
                    page_start=page,
                    page_end=page,
                    chunk_index=index,
                    char_count=len(body),
                    token_estimate=estimate_tokens(text),
                    content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                ),
            )
        )
        index += 1

    # Strip the metadata header block so it is not re-indexed as content; the title and
    # version it contains are already attached to every chunk as metadata.
    body_text = _strip_header_block(cleaned_text)

    for section, section_body, section_offset in _split_sections(body_text, H2_PATTERN):
        subsections = _split_sections(section_body, H3_PATTERN)
        has_subsections = any(heading is not None for heading, _, _ in subsections)

        # Split on H3 whenever sub-headings exist — not only when the section is oversized.
        #
        # v1 split only on size, so a compact section like "2. Definitions" (containing
        # "2.1 Sanctions" and "2.2 PEP") stayed one chunk labelled §2. The text was
        # retrievable but the citation could only say "Section 2", and the evaluation harness
        # scored it as a miss against the §2.1 ground truth. Splitting on structure means a
        # citation names the subsection a compliance officer would actually quote.
        if has_subsections:
            for subsection, sub_body, sub_offset in _merge_tiny_subsections(subsections):
                absolute = section_offset + sub_offset
                if _word_count(sub_body) <= MAX_CHUNK_WORDS:
                    emit(sub_body, section, subsection, absolute)
                else:
                    for part in _paragraph_split_with_overlap(sub_body):
                        emit(part, section, subsection, absolute)
        elif _word_count(section_body) <= MAX_CHUNK_WORDS:
            emit(section_body, section, None, section_offset)
        else:
            for part in _paragraph_split_with_overlap(section_body):
                emit(part, section, None, section_offset)

    return chunks


def _merge_tiny_subsections(
    subsections: list[tuple[str | None, str, int]],
) -> list[tuple[str | None, str, int]]:
    """Fold subsections below MIN_SUBSECTION_WORDS into the preceding sibling.

    Keeps the heading text of the merged fragment inside the body so nothing is lost, while
    avoiding chunks too small to retrieve well.
    """
    merged: list[tuple[str | None, str, int]] = []
    for heading, body, offset in subsections:
        if merged and _word_count(body) < MIN_SUBSECTION_WORDS:
            prev_heading, prev_body, prev_offset = merged[-1]
            addition = f"### {heading}\n\n{body}" if heading else body
            merged[-1] = (prev_heading, f"{prev_body}\n\n{addition}", prev_offset)
        else:
            merged.append((heading, body, offset))
    return merged


def _strip_header_block(text: str) -> str:
    """Remove the leading `# Title` + `**Key:** value` block, keeping body content."""
    lines = text.split("\n")
    cut = 0
    for i, line in enumerate(lines[:12]):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") or re.match(r"^\*{0,2}[A-Za-z][A-Za-z /]{2,30}\*{0,2}\s*:", stripped):
            cut = i + 1
        elif stripped.startswith("##") or (cut and i > cut + 1):
            break
    return "\n".join(lines[cut:]).strip() if cut else text
