"""Query preprocessing.

Retrieval quality is bounded above by query quality, and two things degrade it badly in a
chat setting:

  1. **Follow-ups.** "What about entities?" is unanswerable standalone. Rewriting it against
     the last few turns into "What CDD requirements apply to entity clients?" is the
     difference between retrieving the right section and retrieving noise.
  2. **Domain shorthand.** BM25 is literal: a question asking about "EDD" will not match a
     passage that only ever writes "Enhanced Due Diligence". The acronym dictionary is
     applied to the *sparse* query only, so the dense embedding is never perturbed.

The acronym expansion is deliberately a dictionary, not an LLM call: deterministic, free,
instant, and unit-testable.
"""

from __future__ import annotations

import re

from app.core.errors import ValidationError

# AML/KYC shorthand ⇄ expansion. Applied to the BM25 query only.
ACRONYMS: dict[str, str] = {
    "aml": "anti-money laundering",
    "kyc": "know your customer",
    "cdd": "customer due diligence",
    "edd": "enhanced due diligence",
    "sdd": "simplified due diligence",
    "sow": "source of wealth",
    "sof": "source of funds",
    "pep": "politically exposed person",
    "mlro": "money laundering reporting officer",
    "ubo": "ultimate beneficial owner",
    "sar": "suspicious activity report",
    "str": "suspicious transaction report",
    "ofac": "office of foreign assets control sanctions",
    "fatf": "financial action task force",
    "brp": "biometric residence permit",
    "nca": "national crime agency",
    "id": "identity document",
}

# Phrases that signal the question cannot stand on its own.
_FOLLOWUP_MARKERS = (
    "what about",
    "how about",
    "and for",
    "and if",
    "and what",
    "what if",
    "does that",
    "do they",
    "is it",
    "are they",
    "the same",
    "instead",
    "also",
    "then what",
)
_PRONOUN_START = re.compile(r"^\s*(it|they|them|that|this|those|these|he|she|their|its)\b", re.IGNORECASE)
# A question opening with a conjunction is continuing a previous one by construction.
_CONJUNCTION_START = re.compile(r"^\s*(and|but|or|so)\b", re.IGNORECASE)


def normalise_question(question: str, max_chars: int = 4000) -> str:
    if question is None:
        raise ValidationError("A question is required.")
    cleaned = re.sub(r"\s+", " ", question).strip()
    if not cleaned:
        raise ValidationError("A question is required.")
    if len(cleaned) > max_chars:
        raise ValidationError(
            f"The question is {len(cleaned)} characters; the limit is {max_chars}.",
            max_chars=max_chars,
        )
    return cleaned


def expand_acronyms(question: str) -> str:
    """Append expansions for any acronym present. Additive — the original wording stays,
    so a literal match on the acronym itself is not lost."""
    tokens = set(re.findall(r"[A-Za-z]{2,5}", question.lower()))
    additions = [ACRONYMS[t] for t in sorted(tokens) if t in ACRONYMS]
    return f"{question} {' '.join(additions)}" if additions else question


def looks_like_followup(question: str) -> bool:
    """Heuristic, deliberately biased toward false positives.

    A needless rewrite of an already-standalone question is cheap (the rewrite prompt returns
    it unchanged); a missed rewrite silently retrieves against an incomplete query, which is
    the expensive failure. Hence the low bar.
    """
    lowered = question.lower().strip()
    if len(lowered.split()) <= 3:
        return True
    if _PRONOUN_START.match(lowered) or _CONJUNCTION_START.match(lowered):
        return True
    return any(lowered.startswith(marker) or f" {marker} " in lowered for marker in _FOLLOWUP_MARKERS)


def build_rewrite_prompt(question: str, history: list[tuple[str, str]]) -> str:
    """History is [(role, content)] oldest-first. Only user turns and short assistant
    summaries are included to keep the rewrite prompt small and cheap."""
    lines: list[str] = []
    for role, content in history[-4:]:
        snippet = re.sub(r"\s+", " ", content).strip()
        if role == "assistant":
            snippet = snippet[:300]
        lines.append(f"{role.upper()}: {snippet}")
    transcript = "\n".join(lines) if lines else "(no previous turns)"
    return (
        "Conversation so far:\n"
        f"{transcript}\n\n"
        f"Latest user message: {question}\n\n"
        "Rewrite the latest user message as a standalone compliance question that can be "
        "understood without the conversation. Resolve pronouns and implicit references using "
        "the conversation. Do not answer it. Do not add requirements that were not asked for. "
        "If it is already standalone, return it unchanged."
    )
