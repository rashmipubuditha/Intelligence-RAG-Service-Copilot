"""Chunking and metadata extraction tests.

The headline case is `test_subsection_provenance_is_preserved`, which is the regression test
for README D1 — the defect that capped citation precision in v1.
"""

from __future__ import annotations

from datetime import date

from app.ingestion.chunking import (
    MAX_CHUNK_WORDS,
    _merge_tiny_subsections,
    _paragraph_split_with_overlap,
    chunk_document,
)
from app.ingestion.cleaning import clean_text, estimate_tokens
from app.ingestion.extractors import ExtractedDocument
from app.ingestion.metadata import extract_metadata, infer_doc_type, parse_date, title_from_filename

POLICY = """# Source of Wealth Verification Guidelines
**Version:** 1.3
**Effective Date:** 1 March 2025
**Owner:** MLRO
**Review Cycle:** Annual

---

## 1. Purpose

Source of Wealth verification establishes how a client accumulated their assets.

---

## 3. Documentation Requirements by Category

### 3.1 Employment / Salary

Payslips for the most recent three consecutive months are required, issued by the employer and
showing gross and net pay. A letter from the employer confirming role and salary is also
required, along with bank statements for three months showing matching salary credits.

### 3.2 Business Ownership or Sale

A certificate of incorporation or equivalent is required for current business ownership, plus
the most recent two years of audited or accountant-certified financial statements, confirmation
of the client's ownership percentage and role from a director or shareholder register, and bank
statements for the business showing regular income activity. Where the client is the sole or
majority owner of a cash-intensive business, additional scrutiny applies and the case must be
escalated for enhanced due diligence regardless of the composite risk score.
"""


def _chunk(text: str = POLICY, filename: str = "02_source_of_wealth.md"):
    cleaned = clean_text(text)
    meta = extract_metadata(cleaned, filename)
    return chunk_document(
        document_id="doc_test",
        filename=filename,
        extracted=ExtractedDocument(text=text),
        cleaned_text=cleaned,
        metadata=meta,
        starting_faiss_id=1,
    )


class TestSubsectionProvenance:
    def test_subsection_provenance_is_preserved(self):
        """README D1 regression.

        v1 labelled every child of a sub-split section with the PARENT heading, so a rule in
        §3.1 could only ever be cited as §3. Each H3 child must now carry its own subsection.
        """
        chunks = _chunk()
        by_subsection = {c.metadata.subsection: c for c in chunks if c.metadata.subsection}

        assert "3.1 Employment / Salary" in by_subsection
        assert "3.2 Business Ownership or Sale" in by_subsection

        employment = by_subsection["3.1 Employment / Salary"]
        assert employment.metadata.section == "3. Documentation Requirements by Category"
        assert "Payslips" in employment.text
        # The business-ownership rule must NOT have leaked into the employment chunk.
        assert "certificate of incorporation" not in employment.text.lower()

    def test_structure_split_happens_even_when_section_is_small(self):
        """v1 only sub-split oversized sections, so compact sections kept a parent-only label.

        Splitting on structure rather than size is what lifted section accuracy from 0.78 to
        0.95 on the golden set.
        """
        # Subsections sized like the real corpus (60-200 words). Anything under
        # MIN_SUBSECTION_WORDS is intentionally merged instead — see
        # test_tiny_subsections_are_merged.
        small = """# Doc
**Version:** 1.0

## 2. Definitions

### 2.1 Sanctions

A sanction is a legal prohibition or restriction imposed by a government or international body
against a person, entity, or jurisdiction. The platform screens against the UK HM Treasury
Consolidated List, the US OFAC Specially Designated Nationals list, the EU Consolidated
Sanctions List, and the UN Security Council Consolidated List. Screening must be conducted
against all active lists simultaneously, and a client is considered sanctioned if they appear
on any list regardless of which jurisdiction imposed the measure.

### 2.2 Politically Exposed Person

A politically exposed person holds, or has held within the last twelve months, a prominent
public function. The platform recognises domestic, foreign, and international organisation
tiers. Close associates and family members of a PEP are subject to the same screening and
enhanced diligence requirements as the PEP themselves, including spouses, children and their
spouses, parents, and known business partners.
"""
        chunks = _chunk(small, "03_defs.md")
        subsections = {c.metadata.subsection for c in chunks}
        assert "2.1 Sanctions" in subsections
        assert "2.2 Politically Exposed Person" in subsections

    def test_heading_path_and_citation_label(self):
        chunks = _chunk()
        employment = next(c for c in chunks if c.metadata.subsection == "3.1 Employment / Salary")
        assert employment.metadata.heading_path == [
            "Source of Wealth Verification Guidelines",
            "3. Documentation Requirements by Category",
            "3.1 Employment / Salary",
        ]
        label = employment.metadata.citation_label
        assert label == ("Source of Wealth Verification Guidelines v1.3 — §3.1 Employment / Salary")

    def test_provenance_header_is_inline_in_chunk_text(self):
        """The model should see provenance in the passage, not only in the prompt scaffold."""
        chunks = _chunk()
        employment = next(c for c in chunks if c.metadata.subsection == "3.1 Employment / Salary")
        assert employment.text.startswith("[Source of Wealth Verification Guidelines > 3.")


class TestChunkIdentity:
    def test_chunk_uid_is_stable_across_reruns(self):
        """README D4: ids must be content-derived, so re-ingest does not invalidate saved
        citations or audit references."""
        first = {c.chunk_uid for c in _chunk()}
        second = {c.chunk_uid for c in _chunk()}
        assert first == second

    def test_chunk_uid_differs_between_documents(self):
        a = _chunk(filename="a.md")
        b = chunk_document(
            document_id="doc_other",
            filename="a.md",
            extracted=ExtractedDocument(text=POLICY),
            cleaned_text=clean_text(POLICY),
            metadata=extract_metadata(clean_text(POLICY), "a.md"),
            starting_faiss_id=1,
        )
        assert {c.chunk_uid for c in a}.isdisjoint({c.chunk_uid for c in b})

    def test_faiss_ids_start_at_offset(self):
        chunks = chunk_document(
            document_id="doc_test",
            filename="x.md",
            extracted=ExtractedDocument(text=POLICY),
            cleaned_text=clean_text(POLICY),
            metadata=extract_metadata(clean_text(POLICY), "x.md"),
            starting_faiss_id=500,
        )
        assert [c.faiss_id for c in chunks] == list(range(500, 500 + len(chunks)))


class TestChunkSizing:
    def test_every_chunk_respects_the_word_budget(self):
        """Chunks must stay inside BGE-small's 512-token window with headroom."""
        for chunk in _chunk():
            body = chunk.text.split("\n\n", 1)[-1]
            assert len(body.split()) <= MAX_CHUNK_WORDS + 20

    def test_paragraph_split_overlaps(self):
        text = "\n\n".join(f"Paragraph {i} " + "word " * 90 for i in range(5))
        parts = _paragraph_split_with_overlap(text, max_words=120, overlap_words=40)
        assert len(parts) > 1
        # Consecutive parts must share text, otherwise a rule split at the seam is lost.
        assert any(set(parts[i].split()) & set(parts[i + 1].split()) for i in range(len(parts) - 1))

    def test_tiny_subsections_are_merged(self):
        subsections = [
            ("4.1 Main", "word " * 120, 0),
            ("4.2 Tiny", "short note", 100),
        ]
        merged = _merge_tiny_subsections(subsections)
        assert len(merged) == 1
        assert "short note" in merged[0][1]
        assert "4.2 Tiny" in merged[0][1]

    def test_empty_and_headingless_documents_do_not_crash(self):
        assert _chunk("", "empty.md") == []
        chunks = _chunk("Just a sentence with no headings at all in it.", "plain.md")
        assert len(chunks) == 1
        assert chunks[0].metadata.section is None


class TestCleaning:
    def test_horizontal_rules_are_stripped(self):
        """README D10: 36 of 46 v1 chunks carried a trailing `---`."""
        cleaned = clean_text("Text above.\n\n---\n\nText below.")
        assert "---" not in cleaned
        assert "Text above." in cleaned and "Text below." in cleaned

    def test_pdf_hyphenated_linebreaks_are_rejoined(self):
        assert "requirements" in clean_text("require-\nments apply", is_pdf=True)

    def test_repeated_pdf_boilerplate_is_removed(self):
        page = "ACME Confidential\nBody one\nACME Confidential\nBody two\nACME Confidential\nBody three"
        cleaned = clean_text(page, is_pdf=True)
        assert "ACME Confidential" not in cleaned
        assert "Body one" in cleaned

    def test_token_estimate_is_proportional(self):
        assert estimate_tokens("one two three four five") > estimate_tokens("one two")


class TestMetadata:
    def test_front_matter_is_parsed(self):
        """README D2: v1 discarded all of this."""
        meta = extract_metadata(POLICY, "02_source_of_wealth.md")
        assert meta.title == "Source of Wealth Verification Guidelines"
        assert meta.version == "1.3"
        assert meta.effective_date == date(2025, 3, 1)
        assert meta.owner == "MLRO"
        assert meta.review_cycle == "Annual"
        assert meta.doc_type == "guideline"

    def test_missing_metadata_yields_null_not_a_crash(self):
        meta = extract_metadata("# Bare Title\n\n## 1. Only Section\n\nBody.", "bare.md")
        assert meta.title == "Bare Title"
        assert meta.version is None
        assert meta.effective_date is None

    def test_version_falls_back_to_filename(self):
        meta = extract_metadata("## 1. Section\n\nBody text.", "cdd_policy_v2.1.md")
        assert meta.version == "2.1"

    def test_family_key_groups_versions_together(self):
        a = extract_metadata("# CDD Policy\n**Version:** 1.9\n", "a.md")
        b = extract_metadata("# CDD Policy\n**Version:** 2.1\n", "b.md")
        assert a.family_key == b.family_key

    def test_header_block_is_not_indexed_as_content(self):
        """Version/owner lines are metadata; indexing them as prose pollutes retrieval."""
        chunks = _chunk()
        assert not any("Review Cycle" in c.text for c in chunks)

    @staticmethod
    def test_date_formats():
        assert parse_date("1 March 2025") == date(2025, 3, 1)
        assert parse_date("2025-03-01") == date(2025, 3, 1)
        assert parse_date("1st March 2025") == date(2025, 3, 1)
        assert parse_date("not a date") is None

    @staticmethod
    def test_doc_type_inference():
        assert infer_doc_type("Sanctions Screening Procedure", "x.md") == "procedure"
        assert infer_doc_type("Risk Assessment Framework", "x.md") == "framework"
        assert infer_doc_type("Something Else", "x.md") == "other"

    @staticmethod
    def test_title_from_filename():
        assert title_from_filename("02_source_of_wealth.md") == "Source Of Wealth"


class TestPageMapping:
    def test_pages_are_populated_only_when_the_format_has_them(self):
        """Markdown has no pages; a fabricated page number in a citation would be a lie."""
        chunks = _chunk()
        assert all(c.metadata.page_start is None for c in chunks)

    def test_page_offsets_map_to_page_numbers(self):
        extracted = ExtractedDocument(text="a" * 100, page_count=2, page_offsets=[(0, 1), (50, 2)])
        assert extracted.page_for_offset(10) == 1
        assert extracted.page_for_offset(75) == 2
