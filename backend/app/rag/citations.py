"""Citation resolution — the system's most important invariant.

**A citation can only ever point at a chunk the retriever actually returned.** The model
never authors citation text; it emits references into a set the server controls, and the
server discards anything it does not recognise. That makes fabricated citations structurally
impossible rather than merely discouraged (README DR-4, DR-10).

Two input forms, one validator:

  * **JSON mode** (CLI, non-streaming API): the model returns `used_chunk_ids: [int]`.
  * **Marker mode** (streaming): the model emits inline `[[cid:17]]` markers. Markers are
    parsed incrementally as tokens arrive, resolved against the retrieved set, and rendered
    as `[1]`, `[2]`, … in order of first appearance.

`MarkerStreamParser` handles the awkward part of streaming: a marker can be split across
token boundaries, so a tail that could still become a marker is held back until it either
completes or is proven not to be one.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.models import Citation, RetrievedChunk

log = get_logger("citations")

MARKER_PATTERN = re.compile(r"\[\[cid:(\d+)\]\]")

# Any suffix that is still a proper prefix of a complete marker, and must therefore be held
# back rather than emitted. Covers every stage: "[", "[[", "[[c", "[[ci", "[[cid", "[[cid:",
# "[[cid:12", and — the case a naive version misses — "[[cid:12]" with only one closing
# bracket so far. Missing that last form leaks a raw marker whenever a token boundary falls
# between the two closing brackets.
_PARTIAL_MARKER = re.compile(r"\[(?:\[(?:c(?:i(?:d(?::(?:\d*\]?)?)?)?)?)?)?$")
_CODE_FENCE = re.compile(r"```")


class CitationResolver:
    """Maps model-emitted chunk ids onto display indices, dropping anything fabricated."""

    def __init__(self, retrieved: list[RetrievedChunk]) -> None:
        self._by_faiss_id = {rc.chunk.faiss_id: rc for rc in retrieved}
        self._order: list[int] = []
        self.fabricated: list[int] = []

    def resolve(self, chunk_id: int) -> int | None:
        """Return the 1-based display index for a chunk id, or None if it was not retrieved."""
        if chunk_id not in self._by_faiss_id:
            if chunk_id not in self.fabricated:
                self.fabricated.append(chunk_id)
            return None
        if chunk_id not in self._order:
            self._order.append(chunk_id)
        return self._order.index(chunk_id) + 1

    def citations(self) -> list[Citation]:
        return [
            Citation.from_retrieved(self._by_faiss_id[cid], index=i + 1) for i, cid in enumerate(self._order)
        ]

    @property
    def cited_count(self) -> int:
        return len(self._order)


def resolve_used_ids(
    used_chunk_ids: list[int], retrieved: list[RetrievedChunk]
) -> tuple[list[Citation], list[int]]:
    """JSON-mode resolution. Returns (citations, fabricated_ids)."""
    resolver = CitationResolver(retrieved)
    for chunk_id in used_chunk_ids:
        resolver.resolve(chunk_id)
    if resolver.fabricated:
        log.warning("citations.fabricated_dropped", ids=resolver.fabricated)
    return resolver.citations(), resolver.fabricated


def resolve_markers(text: str, retrieved: list[RetrievedChunk]) -> tuple[str, list[Citation], list[int]]:
    """Marker-mode resolution over a complete string.

    Returns (display_text, citations, fabricated_ids). Unknown markers are removed from the
    text entirely so a fabricated reference leaves no trace in the answer.
    """
    resolver = CitationResolver(retrieved)

    def replace(match: re.Match[str]) -> str:
        index = resolver.resolve(int(match.group(1)))
        return f"[{index}]" if index else ""

    display = MARKER_PATTERN.sub(replace, text)
    display = re.sub(r" +([.,;:])", r"\1", display)
    display = re.sub(r"[ \t]{2,}", " ", display)
    if resolver.fabricated:
        log.warning("citations.fabricated_dropped", ids=resolver.fabricated)
    return display.strip(), resolver.citations(), resolver.fabricated


class MarkerStreamParser:
    """Incrementally converts `[[cid:n]]` markers into `[n]` as tokens arrive.

    Holds back any trailing text that could still become a marker, so a marker split across
    two tokens is never emitted as literal text. Markers inside fenced code blocks are left
    untouched — a code sample that happens to contain the syntax is content, not a citation.
    """

    def __init__(self, resolver: CitationResolver) -> None:
        self.resolver = resolver
        self._buffer = ""
        self._in_code_fence = False

    def feed(self, token: str) -> str:
        self._buffer += token
        emit = ""

        while True:
            match = MARKER_PATTERN.search(self._buffer)
            if not match:
                break
            before = self._buffer[: match.start()]
            self._in_code_fence ^= bool(len(_CODE_FENCE.findall(before)) % 2)
            if self._in_code_fence:
                emit += before + match.group(0)
            else:
                index = self.resolver.resolve(int(match.group(1)))
                emit += before + (f"[{index}]" if index else "")
            self._buffer = self._buffer[match.end() :]

        # Hold back a possible partial marker; emit everything definitely safe.
        partial = _PARTIAL_MARKER.search(self._buffer)
        if partial:
            emit += self._buffer[: partial.start()]
            self._buffer = self._buffer[partial.start() :]
        else:
            emit += self._buffer
            self._buffer = ""
        return emit

    def flush(self) -> str:
        """Emit whatever is left once the stream ends (an unterminated marker is literal)."""
        remaining, self._buffer = self._buffer, ""
        return remaining
