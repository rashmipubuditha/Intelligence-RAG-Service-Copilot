"""Tests for the system's central invariant and its guardrails.

`TestCitationFabrication` is the most important test file in the project: it proves that a
citation can only ever point at a passage the retriever actually returned, which is the claim
the whole product rests on (README DR-4 / DR-10).
"""

from __future__ import annotations

from datetime import date

import pytest
from app.core.config import Settings
from app.models import Chunk, ChunkMetadata, RetrievedChunk
from app.rag.citations import (
    CitationResolver,
    MarkerStreamParser,
    resolve_markers,
    resolve_used_ids,
)
from app.rag.context import select_context, truncate_at_paragraph
from app.rag.guardrails import (
    compute_evidence,
    detect_conflicts,
    has_sufficient_evidence,
    is_refusal,
)
from app.rag.query_processing import expand_acronyms, looks_like_followup, normalise_question
from app.rag.retrieval import deduplicate, reciprocal_rank_fusion


def make_chunk(
    faiss_id: int,
    text: str = "Body text for the passage.",
    *,
    document: str = "01_policy.md",
    title: str = "Test Policy",
    section: str | None = "1. Section",
    subsection: str | None = None,
    version: str | None = "1.0",
    effective: date | None = None,
    document_id: str = "doc_1",
) -> Chunk:
    return Chunk(
        chunk_uid=f"uid{faiss_id}",
        faiss_id=faiss_id,
        text=text,
        metadata=ChunkMetadata(
            document_id=document_id,
            document_name=document,
            document_title=title,
            section=section,
            subsection=subsection,
            version=version,
            effective_date=effective,
            content_sha256=f"sha{faiss_id}",
        ),
    )


def retrieved(*faiss_ids: int, score: float = 0.9) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(chunk=make_chunk(i), score=score, rrf_score=score, rerank_score=score)
        for i in faiss_ids
    ]


# ---------------------------------------------------------------------------


class TestCitationFabrication:
    """The core invariant: the model cannot cite what was not retrieved."""

    def test_unknown_ids_are_dropped_in_json_mode(self):
        citations, fabricated = resolve_used_ids([10, 999, 11], retrieved(10, 11, 12))
        assert [c.chunk_uid for c in citations] == ["uid10", "uid11"]
        assert fabricated == [999]

    def test_unknown_markers_are_dropped_and_removed_from_text(self):
        text = "Claim one [[cid:10]] and a fabricated claim [[cid:777]] here."
        display, citations, fabricated = resolve_markers(text, retrieved(10, 11))
        assert fabricated == [777]
        assert len(citations) == 1
        assert "[1]" in display
        assert "777" not in display and "cid" not in display

    def test_every_citation_text_comes_from_the_retrieved_chunk(self):
        """Even if the model writes its own passage text, the citation body is ours."""
        chunks = retrieved(10)
        chunks[0].chunk.text = "AUTHORITATIVE indexed text"
        _display, citations, _ = resolve_markers("Invented quote [[cid:10]]", chunks)
        assert citations[0].chunk == "AUTHORITATIVE indexed text"

    def test_duplicate_references_collapse_to_one_citation(self):
        _display, citations, _ = resolve_markers("A [[cid:10]] B [[cid:10]]", retrieved(10))
        assert len(citations) == 1

    def test_display_indices_follow_order_of_first_appearance(self):
        display, citations, _ = resolve_markers("First [[cid:12]] then [[cid:10]]", retrieved(10, 11, 12))
        assert display.index("[1]") < display.index("[2]")
        assert citations[0].chunk_uid == "uid12"
        assert citations[1].chunk_uid == "uid10"

    def test_empty_retrieval_means_no_citations_are_possible(self):
        _display, citations, fabricated = resolve_markers("Claim [[cid:5]]", [])
        assert citations == []
        assert fabricated == [5]

    def test_citation_carries_full_provenance(self):
        chunk = make_chunk(10, subsection="3.1 Employment", version="1.3", effective=date(2025, 3, 1))
        rc = RetrievedChunk(chunk=chunk, score=0.9, rrf_score=0.9)
        _display, citations, _ = resolve_markers("Claim [[cid:10]]", [rc])
        citation = citations[0]
        assert citation.subsection == "3.1 Employment"
        assert citation.version == "1.3"
        assert citation.effective_date == date(2025, 3, 1)
        assert "§3.1 Employment" in citation.label


class TestMarkerStreamParser:
    def test_marker_split_across_token_boundaries(self):
        """A marker arriving in pieces must never leak as literal text."""
        resolver = CitationResolver(retrieved(10))
        parser = MarkerStreamParser(resolver)
        out = "".join(parser.feed(piece) for piece in ["Claim ", "[[c", "id:1", "0]]", " done."])
        out += parser.flush()
        assert "[[cid" not in out
        assert "[1]" in out
        assert out.startswith("Claim [1]")

    @pytest.mark.parametrize(
        "pieces",
        [
            ["Claim [[cid:10]] done."],  # whole marker in one token
            ["Claim ", "[[cid:10]]", " done."],  # marker aligned to a token
            ["Claim ", "[[cid:1", "0]]", " done."],  # split inside the digits
            ["Claim ", "[[cid:10]", "]", " done."],  # split between closing brackets
            ["Claim ", "[", "[", "c", "i", "d", ":", "1", "0", "]", "]", "."],  # char by char
            ["Claim [[cid:10", "]] done."],
        ],
    )
    def test_marker_survives_every_split_position(self, pieces):
        """Regression: a token boundary between the two closing brackets leaked a raw marker.

        The partial-marker guard held back "[[cid:1" but not "[[cid:10]", so the latter was
        flushed as literal text while the citation still resolved — a visible break in the
        answer. Found by an integration test, fixed in the parser, pinned here across every
        split position.
        """
        resolver = CitationResolver(retrieved(10))
        parser = MarkerStreamParser(resolver)
        out = "".join(parser.feed(piece) for piece in pieces) + parser.flush()
        assert "[[cid" not in out, f"raw marker leaked for split {pieces!r}"
        assert "[1]" in out
        assert len(resolver.citations()) == 1

    def test_unresolvable_marker_leaves_no_trace_when_split(self):
        resolver = CitationResolver(retrieved(10))
        parser = MarkerStreamParser(resolver)
        out = "".join(parser.feed(p) for p in ["Fake ", "[[cid:9999", "9]", "] end."]) + parser.flush()
        assert "9999" not in out and "cid" not in out
        assert resolver.citations() == []

    def test_text_streams_through_unchanged_when_no_markers(self):
        parser = MarkerStreamParser(CitationResolver(retrieved(10)))
        out = "".join(parser.feed(c) for c in "Plain prose answer.") + parser.flush()
        assert out == "Plain prose answer."

    def test_unterminated_marker_is_flushed_not_swallowed(self):
        parser = MarkerStreamParser(CitationResolver(retrieved(10)))
        out = parser.feed("Answer [[cid:1") + parser.flush()
        assert out.startswith("Answer ")
        assert "[[cid:1" in out

    def test_bracket_text_that_is_not_a_marker_survives(self):
        parser = MarkerStreamParser(CitationResolver(retrieved(10)))
        out = parser.feed("See table [a] and [b].") + parser.flush()
        assert out == "See table [a] and [b]."


class TestRRF:
    def test_known_fusion_arithmetic(self):
        fused = reciprocal_rank_fusion([([1, 2], 1.0), ([2, 1], 1.0)], rrf_k=60)
        assert fused[1] == pytest.approx(1 / 60 + 1 / 61)
        assert fused[2] == pytest.approx(1 / 61 + 1 / 60)

    def test_agreement_between_legs_outranks_single_leg(self):
        fused = reciprocal_rank_fusion([([1, 3], 1.0), ([1, 4], 1.0)], rrf_k=60)
        assert fused[1] > fused[3] and fused[1] > fused[4]

    def test_single_leg_degrades_gracefully(self):
        fused = reciprocal_rank_fusion([([1, 2], 1.0), ([], 1.0)], rrf_k=60)
        assert list(fused) == [1, 2]

    def test_zero_weight_disables_a_leg(self):
        fused = reciprocal_rank_fusion([([1], 1.0), ([2], 0.0)], rrf_k=60)
        assert 2 not in fused


class TestDeduplication:
    def test_exact_duplicates_are_dropped(self):
        chunks = retrieved(10, 11)
        chunks[1].chunk.metadata.content_sha256 = chunks[0].chunk.metadata.content_sha256
        kept, dropped = deduplicate(chunks)
        assert len(kept) == 1 and dropped == 1

    def test_near_duplicates_are_collapsed(self):
        a = RetrievedChunk(chunk=make_chunk(1, "alpha beta gamma delta epsilon"), score=0.9)
        b = RetrievedChunk(chunk=make_chunk(2, "alpha beta gamma delta epsilon zeta"), score=0.8)
        kept, dropped = deduplicate([a, b], threshold=0.8)
        assert len(kept) == 1 and dropped == 1
        assert kept[0].chunk.faiss_id == 1  # better-ranked copy survives

    def test_distinct_passages_are_both_kept(self):
        a = RetrievedChunk(chunk=make_chunk(1, "passport expiry rules apply"), score=0.9)
        b = RetrievedChunk(chunk=make_chunk(2, "sanctions screening frequency quarterly"), score=0.8)
        kept, dropped = deduplicate([a, b])
        assert len(kept) == 2 and dropped == 0


class TestContextSelection:
    def test_token_budget_is_respected(self):
        chunks = [RetrievedChunk(chunk=make_chunk(i, "word " * 300), score=0.9) for i in range(10)]
        selected = select_context(chunks, max_tokens=500)
        assert selected.total_tokens <= 600  # budget plus the mandatory top chunk

    def test_top_chunk_is_always_included_even_if_oversized(self):
        chunks = [RetrievedChunk(chunk=make_chunk(1, "word " * 5000), score=0.9)]
        selected = select_context(chunks, max_tokens=100)
        assert len(selected.chunks) == 1
        assert selected.truncated_chunks == 1

    def test_truncation_marks_itself(self):
        text = "\n\n".join("para " * 50 for _ in range(10))
        assert "truncated" in truncate_at_paragraph(text, 100)


class TestEvidence:
    def test_refusal_gate_blocks_weak_retrieval(self):
        settings = Settings(evidence_refusal_floor=0.5)
        weak = [RetrievedChunk(chunk=make_chunk(1), score=0.1, rrf_score=0.0001)]
        assert has_sufficient_evidence(weak, settings) is False
        assert has_sufficient_evidence([], settings) is False

    def test_bands_follow_the_documented_rule(self):
        settings = Settings(
            evidence_refusal_floor=0.3, evidence_moderate_floor=0.45, evidence_strong_floor=0.6
        )
        strong = [RetrievedChunk(chunk=make_chunk(i), score=0.9, rerank_score=5.0) for i in (1, 2, 3)]
        evidence = compute_evidence(
            chunks=strong, cited_count=3, answer="Policy requires X.", settings=settings
        )
        assert evidence.band == "strong"
        assert evidence.signals.distinct_documents == 1
        assert evidence.signals.supporting_chunks == 3

    def test_no_citations_means_insufficient(self):
        settings = Settings()
        chunks = [RetrievedChunk(chunk=make_chunk(1), score=0.9, rerank_score=5.0)]
        evidence = compute_evidence(chunks=chunks, cited_count=0, answer="Some prose.", settings=settings)
        assert evidence.band == "insufficient"

    def test_evidence_never_claims_to_be_a_probability(self):
        """README DR-11: the disclaimer is part of the contract, not decoration."""
        evidence = compute_evidence(chunks=retrieved(1), cited_count=1, answer="X.", settings=Settings())
        assert "not a calibrated probability" in evidence.disclaimer

    def test_refusal_detection(self):
        assert is_refusal("I couldn't find sufficient evidence in the available documents.")
        assert is_refusal("Cryptocurrency is not one of the five recognised categories.")
        assert is_refusal("The provided documents do not cover GDPR.")
        assert not is_refusal("Medium-risk clients must be screened quarterly.")
        assert not is_refusal("The officer must escalate to the MLRO where documents conflict.")


class TestConflictDetection:
    def test_same_family_different_version_is_flagged(self):
        old = RetrievedChunk(
            chunk=make_chunk(
                1,
                document="cdd_v1.9.md",
                title="CDD Policy",
                version="1.9",
                effective=date(2024, 1, 1),
                document_id="doc_old",
            ),
            score=0.9,
        )
        new = RetrievedChunk(
            chunk=make_chunk(
                2,
                document="cdd_v2.1.md",
                title="CDD Policy",
                version="2.1",
                effective=date(2025, 1, 1),
                document_id="doc_new",
            ),
            score=0.8,
        )
        conflicts = detect_conflicts([old, new])
        assert len(conflicts) == 1
        assert conflicts[0].detection == "structural"
        most_recent = [s for s in conflicts[0].sources if s.is_most_recent]
        assert len(most_recent) == 1 and most_recent[0].version == "2.1"
        assert "2025-01-01" in conflicts[0].description

    def test_different_documents_are_not_a_conflict(self):
        a = RetrievedChunk(chunk=make_chunk(1, title="CDD Policy", document_id="d1"), score=0.9)
        b = RetrievedChunk(chunk=make_chunk(2, title="Sanctions Procedure", document_id="d2"), score=0.8)
        assert detect_conflicts([a, b]) == []

    def test_same_version_twice_is_not_a_conflict(self):
        chunks = [
            RetrievedChunk(chunk=make_chunk(i, title="CDD Policy", version="2.1"), score=0.9) for i in (1, 2)
        ]
        assert detect_conflicts(chunks) == []

    def test_version_fallback_when_dates_are_absent(self):
        a = RetrievedChunk(chunk=make_chunk(1, title="P", version="1.9", document_id="d1"), score=0.9)
        b = RetrievedChunk(chunk=make_chunk(2, title="P", version="2.10", document_id="d2"), score=0.8)
        conflicts = detect_conflicts([a, b])
        assert len(conflicts) == 1
        # 2.10 > 1.9 numerically, which string comparison would get wrong.
        assert [s.version for s in conflicts[0].sources if s.is_most_recent] == ["2.10"]


class TestQueryProcessing:
    def test_normalisation_and_limits(self):
        assert normalise_question("  what   is  EDD?  ") == "what is EDD?"
        with pytest.raises(Exception):
            normalise_question("")
        with pytest.raises(Exception):
            normalise_question("x" * 100, max_chars=10)

    def test_acronyms_expand_additively(self):
        expanded = expand_acronyms("What triggers EDD for a PEP?")
        assert "enhanced due diligence" in expanded
        assert "politically exposed person" in expanded
        assert "EDD" in expanded  # the literal token must survive for BM25

    def test_followup_detection(self):
        assert looks_like_followup("What about for entity clients?")
        assert looks_like_followup("And if they are self-employed?")
        assert looks_like_followup("Is it acceptable?")
        assert not looks_like_followup(
            "What documents are required to verify source of wealth from employment income?"
        )
