"""Text cleaning.

Fixes README D10: 36 of 46 chunks in the v1 index carried a trailing `---` horizontal rule,
which is pure noise to both the embedder and the LLM. PDF extraction adds its own artefacts
— hyphenated line breaks and repeated page headers/footers — which are removed here so they
never reach a chunk or a citation.
"""

from __future__ import annotations

import re
from collections import Counter

_HORIZONTAL_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$", re.MULTILINE)
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_NBSP = re.compile(r"[   ]")
_PAGE_NUMBER_LINE = re.compile(r"^\s*(page\s+)?\d+\s*(/\s*\d+)?\s*$", re.IGNORECASE | re.MULTILINE)


def clean_text(text: str, *, is_pdf: bool = False) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _NBSP.sub(" ", text)
    if is_pdf:
        text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
        text = _remove_repeated_boilerplate(text)
        text = _PAGE_NUMBER_LINE.sub("", text)
    text = _HORIZONTAL_RULE.sub("", text)
    text = _TRAILING_SPACE.sub("", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def _remove_repeated_boilerplate(text: str, min_repeats: int = 3) -> str:
    """Drop short lines that repeat on most pages — i.e. running headers and footers.

    Only applied to PDFs, and only to lines short enough to be chrome rather than content.
    """
    lines = text.split("\n")
    candidates = Counter(stripped for line in lines if 3 < len(stripped := line.strip()) <= 80)
    boilerplate = {line for line, count in candidates.items() if count >= min_repeats}
    if not boilerplate:
        return text
    return "\n".join(line for line in lines if line.strip() not in boilerplate)


def normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~1.3 tokens per word for English + BERT-family tokenisers).

    Deliberately an estimate, not a tokenizer call: it is used for context budgeting where
    being within ~10% is sufficient, and loading a tokenizer per chunk is not.
    """
    return int(len(text.split()) * 1.3) + 1
