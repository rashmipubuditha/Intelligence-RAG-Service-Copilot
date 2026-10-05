"""Markdown-section-aware chunker.

Splits each policy on level-2 (`##`) headings — these match exactly how the test questions
reference policies ("Policy 02, Section 3.1"), so a chunk is a self-contained rule and a
citation is a natural unit of provenance.

If a section is too large for the embedding model's effective context (BGE-small handles
~512 tokens), it is further split on `###` sub-headings, then on paragraph boundaries with
a small overlap. The Document/Section header is prepended to every chunk so the LLM sees
provenance inline.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.schemas import Chunk

H2_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
H3_SPLIT_PATTERN = re.compile(r"(?=^###\s+)", re.MULTILINE)

# BGE-small truncates at 512 tokens. Aim for chunks comfortably below that.
# ~1.3 BERT tokens per English word, so 300 words ≈ 390 tokens — leaves headroom for the
# Document/Section prefix and any list formatting.
MAX_CHUNK_WORDS = 300
OVERLAP_WORDS = 60


def _word_count(text: str) -> int:
    return len(text.split())


def _paragraph_split_with_overlap(text: str, max_words: int, overlap_words: int) -> list[str]:
    """Pack paragraphs into chunks under max_words, with trailing-paragraph overlap.

    Overlap preserves continuity across rule boundaries so a question like "what counts as
    consistent across the three documents" doesn't fall in the seam between two chunks.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for p in paragraphs:
        p_words = _word_count(p)
        if current and current_words + p_words > max_words:
            chunks.append("\n\n".join(current))
            # build overlap from the tail of the current chunk
            overlap: list[str] = []
            overlap_count = 0
            for prev in reversed(current):
                pw = _word_count(prev)
                if overlap_count + pw <= overlap_words:
                    overlap.insert(0, prev)
                    overlap_count += pw
                else:
                    break
            current = overlap + [p]
            current_words = sum(_word_count(x) for x in current)
        else:
            current.append(p)
            current_words += p_words

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_long_section(section_body: str, max_words: int = MAX_CHUNK_WORDS) -> list[str]:
    """Split a section that exceeds max_words. Prefer ### sub-headings, then paragraphs."""
    if _word_count(section_body) <= max_words:
        return [section_body]

    subsections = [s.strip() for s in H3_SPLIT_PATTERN.split(section_body) if s.strip()]
    if len(subsections) > 1:
        out: list[str] = []
        for sub in subsections:
            if _word_count(sub) <= max_words:
                out.append(sub)
            else:
                out.extend(_paragraph_split_with_overlap(sub, max_words, OVERLAP_WORDS))
        return out

    return _paragraph_split_with_overlap(section_body, max_words, OVERLAP_WORDS)


def _format_chunk_text(document: str, section: str, body: str) -> str:
    return f"Document: {document} | Section: {section}\n\n{body.strip()}"


def chunk_document(doc_path: Path) -> list[Chunk]:
    """Chunk a single markdown policy. `chunk_id` is set to -1 here and assigned globally
    by chunk_corpus()."""
    text = doc_path.read_text(encoding="utf-8")
    filename = doc_path.name

    matches = list(H2_PATTERN.finditer(text))
    if not matches:
        body = text.strip()
        if not body:
            return []
        return [
            Chunk(
                chunk_id=-1,
                document=filename,
                section="(whole document)",
                text=_format_chunk_text(filename, "(whole document)", body),
            )
        ]

    chunks: list[Chunk] = []
    for i, m in enumerate(matches):
        section_header = m.group(1).strip()
        section_start = m.end()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_body = text[section_start:section_end].strip()
        if not section_body:
            continue

        for part in _split_long_section(section_body):
            chunks.append(
                Chunk(
                    chunk_id=-1,
                    document=filename,
                    section=section_header,
                    text=_format_chunk_text(filename, section_header, part),
                )
            )

    return chunks


def chunk_corpus(policies_dir: Path) -> list[Chunk]:
    """Chunk every *.md file under policies_dir. Assigns globally unique chunk_ids."""
    if not policies_dir.exists() or not policies_dir.is_dir():
        raise FileNotFoundError(f"Policies directory not found: {policies_dir}")

    md_files = sorted(policies_dir.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md files found in {policies_dir}")

    all_chunks: list[Chunk] = []
    for md in md_files:
        all_chunks.extend(chunk_document(md))

    for idx, chunk in enumerate(all_chunks):
        chunk.chunk_id = idx

    return all_chunks
