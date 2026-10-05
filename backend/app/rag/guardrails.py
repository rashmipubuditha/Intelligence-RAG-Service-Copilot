"""Guardrails: evidence strength, conflict detection, refusal detection.

Evidence (README DR-11): no LLM-generated confidence score is produced anywhere in this
system. A model asked "how confident are you?" returns an uncalibrated number, and a
well-formatted meaningless number is actively harmful in a compliance tool. What is reported
instead is a set of *observable retrieval signals* plus a discrete band derived from them by
a rule that is published in the README and visible in the UI.

Conflict detection is split by reliability: the structural check is exact (same document
family, different version or effective date — arithmetic on metadata), while semantic
disagreement is left to the prompt to surface and is labelled best-effort.
"""

from __future__ import annotations

import re

from app.core.config import Settings
from app.models import (
    Conflict,
    ConflictingSource,
    Evidence,
    EvidenceSignals,
    RetrievedChunk,
)

REFUSAL_MESSAGE = (
    "I couldn't find sufficient evidence in the available compliance documents to answer this question."
)

# Phrases that indicate the model acknowledged the corpus does not cover the question.
#
# These were widened against the labelled negative cases in the golden set: the first version
# missed "is not one of the five recognised categories", which is the exact phrasing the model
# uses for the out-of-scope cryptocurrency case. Deliberately specific — "escalate to the
# MLRO" alone is NOT a refusal marker, because a perfectly normal answer about red flags
# mentions escalation.
_REFUSAL_MARKERS = (
    "couldn't find sufficient evidence",
    "could not find sufficient evidence",
    "insufficient evidence",
    "does not contain enough information",
    "do not contain enough information",
    "does not cover",
    "do not cover",
    "not covered",
    "is not addressed",
    "not addressed in",
    "no information in the provided",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "cannot provide a complete",
    "not recognised",
    "not recognized",
    "not a recognised",
    "not a recognized",
    "not one of the recognised",
    "not one of the recognized",
    "does not fit any recognised",
    "does not fit any recognized",
    "not fall within any of these categories",
    "no recognised category",
    "not among the",
    "is not listed",
    "are not listed",
    "not defined in the",
    "outside the scope",
    "do not address",
    "does not address",
    "no passages",
)

# "not one of the five recognised categories" — the count varies, so match it structurally.
_REFUSAL_PATTERNS = (
    re.compile(r"not\s+one\s+of\s+the\s+(\w+\s+)?recognis|zed", re.I),
    re.compile(
        r"not\s+(?:a|an|one\s+of\s+the)\s+[\w\s]{0,20}categor(?:y|ies)\s+(?:listed|defined|recognis|recogniz)",
        re.I,
    ),
)


def is_refusal(answer: str) -> bool:
    """Detect a refusal in model prose.

    Used for metrics and evidence banding only — it never rewrites the answer. Pattern-based
    detection is imperfect by nature, which is why refusal accuracy is a reported metric
    (split into correct refusals and over-refusals) rather than an assumed property.
    """
    lowered = answer.lower()
    if any(marker in lowered for marker in _REFUSAL_MARKERS):
        return True
    return any(pattern.search(answer) for pattern in _REFUSAL_PATTERNS)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def has_sufficient_evidence(chunks: list[RetrievedChunk], settings: Settings) -> bool:
    """The retrieval-level refusal gate.

    Refusal must not depend on the model choosing to refuse, so when the best passage scores
    below the floor the question is answered with the refusal response and no answer is
    requested from the model at all.
    """
    if not chunks:
        return False
    return chunks[0].normalised_score >= settings.evidence_refusal_floor


def compute_evidence(
    *,
    chunks: list[RetrievedChunk],
    cited_count: int,
    answer: str,
    settings: Settings,
    refused: bool | None = None,
) -> Evidence:
    """Derive evidence signals and a band from retrieval output."""
    refusal = is_refusal(answer) if refused is None else refused

    if not chunks:
        return Evidence(
            band="insufficient",
            signals=EvidenceSignals(answer_is_refusal=refusal),
            basis="No passages were retrieved from the indexed documents.",
        )

    top = chunks[0].normalised_score
    second = chunks[1].normalised_score if len(chunks) > 1 else 0.0
    distinct_documents = len({rc.chunk.metadata.document_id for rc in chunks})
    cited_fraction = round(cited_count / len(chunks), 3) if chunks else 0.0

    signals = EvidenceSignals(
        top_score=round(top, 4),
        score_margin=round(top - second, 4),
        supporting_chunks=cited_count,
        distinct_documents=distinct_documents,
        cited_fraction_of_context=cited_fraction,
        answer_is_refusal=refusal,
    )

    if refusal or cited_count == 0 or top < settings.evidence_refusal_floor:
        band = "insufficient"
        basis = (
            "The answer is a refusal; no passage met the evidence floor."
            if refusal
            else "No retrieved passage was cited in support of an answer."
        )
    elif top >= settings.evidence_strong_floor and cited_count >= 2:
        band = "strong"
        basis = (
            f"The top passage scored {top:.2f} and {cited_count} passages from "
            f"{distinct_documents} document(s) support the answer."
        )
    elif top >= settings.evidence_moderate_floor:
        band = "moderate"
        basis = (
            f"The top passage scored {top:.2f} with {cited_count} supporting passage(s). "
            "Verify the citations before relying on this."
        )
    else:
        band = "weak"
        basis = (
            f"The best passage scored only {top:.2f}. The answer may be based on partially "
            "relevant text — check the cited sections directly."
        )

    return Evidence(band=band, signals=signals, basis=basis)


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


def detect_conflicts(chunks: list[RetrievedChunk]) -> list[Conflict]:
    """Structural conflict detection: exact, metadata-driven, no model involved.

    Two retrieved passages from the same document family (same title, normalised) with
    different versions or effective dates mean the corpus contains more than one statement of
    the same rule. The system surfaces both rather than silently picking one.
    """
    families: dict[str, dict[str, RetrievedChunk]] = {}
    for rc in chunks:
        meta = rc.chunk.metadata
        fingerprint = f"{meta.version or ''}|{meta.effective_date or ''}"
        families.setdefault(meta.family_key, {}).setdefault(fingerprint, rc)

    conflicts: list[Conflict] = []
    for _family, variants in families.items():
        if len(variants) < 2:
            continue

        sources: list[ConflictingSource] = []
        for rc in variants.values():
            meta = rc.chunk.metadata
            sources.append(
                ConflictingSource(
                    document_id=meta.document_id,
                    document_title=meta.document_title,
                    document_name=meta.document_name,
                    version=meta.version,
                    effective_date=meta.effective_date,
                    section=meta.subsection or meta.section,
                )
            )

        dated = [s for s in sources if s.effective_date]
        if dated:
            newest = max(dated, key=lambda s: s.effective_date)  # type: ignore[arg-type,return-value]
            for source in sources:
                if source.document_id == newest.document_id and source.version == newest.version:
                    source.is_most_recent = True
            recency = (
                f"The most recent is {newest.document_title}"
                f"{f' v{newest.version}' if newest.version else ''} "
                f"(effective {newest.effective_date.isoformat()})."
            )
        else:
            versioned = [s for s in sources if s.version]
            if versioned:
                newest_v = max(versioned, key=lambda s: _version_key(s.version or ""))
                for source in sources:
                    if source.version == newest_v.version:
                        source.is_most_recent = True
                recency = f"The highest version number is v{newest_v.version}."
            else:
                recency = "Neither document states a version or effective date."

        titles = ", ".join(f"{s.document_title}{f' v{s.version}' if s.version else ''}" for s in sources)
        conflicts.append(
            Conflict(
                description=(
                    f"Retrieved passages come from more than one version of the same document "
                    f"({titles}). {recency} Confirm with the policy owner which version applies."
                ),
                sources=sources,
            )
        )

    return conflicts


def _version_key(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    return tuple(int(p) for p in parts) if parts else (0,)
