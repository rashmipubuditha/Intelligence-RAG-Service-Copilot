"""Context selection.

Retrieval returns the best candidates; this decides what actually fits in the prompt. Two
reasons it is a separate stage rather than "take top k":

  * **Token budget.** Latency and cost scale with context length, and long contexts degrade
    attention to the middle of the list. A budget bounds both.
  * **Graceful truncation.** When a passage must be shortened it is cut at a paragraph
    boundary, not mid-sentence, so a citation always shows coherent text.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.cleaning import estimate_tokens
from app.models import RetrievedChunk


@dataclass
class SelectedContext:
    chunks: list[RetrievedChunk]
    total_tokens: int
    truncated_chunks: int = 0
    dropped_chunks: int = 0


def truncate_at_paragraph(text: str, max_tokens: int) -> str:
    """Trim to a token budget on a paragraph boundary, falling back to sentences."""
    if estimate_tokens(text) <= max_tokens:
        return text
    paragraphs = text.split("\n\n")
    kept: list[str] = []
    running = 0
    for para in paragraphs:
        cost = estimate_tokens(para)
        if running + cost > max_tokens:
            break
        kept.append(para)
        running += cost
    if kept:
        return "\n\n".join(kept) + "\n\n[…passage truncated…]"

    # Single oversized paragraph: fall back to sentence boundaries.
    sentences = text.replace("\n", " ").split(". ")
    kept_sentences: list[str] = []
    running = 0
    for sentence in sentences:
        cost = estimate_tokens(sentence)
        if running + cost > max_tokens:
            break
        kept_sentences.append(sentence)
        running += cost
    body = ". ".join(kept_sentences) if kept_sentences else " ".join(text.split()[:max_tokens])
    return body.rstrip(". ") + ". […passage truncated…]"


def select_context(
    chunks: list[RetrievedChunk],
    *,
    max_tokens: int = 3000,
    min_chunks: int = 1,
) -> SelectedContext:
    """Fit the highest-ranked chunks into the token budget.

    The top-ranked chunk is always included even if it alone exceeds the budget (truncated to
    fit): returning no context at all because the best passage is long would be worse than
    returning a trimmed version of it.
    """
    selected: list[RetrievedChunk] = []
    total = 0
    truncated = 0
    dropped = 0

    for position, rc in enumerate(chunks):
        cost = estimate_tokens(rc.chunk.text)
        remaining = max_tokens - total

        if cost <= remaining:
            selected.append(rc)
            total += cost
            continue

        # Not enough room: truncate if this is a chunk we must keep, otherwise drop it.
        must_keep = position < min_chunks
        if must_keep or remaining > 200:
            budget = max(150, remaining) if not must_keep else max(300, remaining)
            shortened = truncate_at_paragraph(rc.chunk.text, budget)
            new_chunk = rc.chunk.model_copy(update={"text": shortened})
            selected.append(rc.model_copy(update={"chunk": new_chunk}))
            total += estimate_tokens(shortened)
            truncated += 1
        else:
            dropped += 1

    return SelectedContext(
        chunks=selected, total_tokens=total, truncated_chunks=truncated, dropped_chunks=dropped
    )
