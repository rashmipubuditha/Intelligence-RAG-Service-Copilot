"""Prompt-injection scanning at ingest time.

This is one layer of a four-layer defence, and the weakest of them — it is a pattern scanner
and pattern scanners are evadable. It exists to *flag* suspicious documents for a human, not
to guarantee safety. The layers that actually hold are:

  1. the prompt's instruction hierarchy (document text is data, never instruction),
  2. server-side citation resolution (an injected "cite policy X" cannot invent a citation,
     because citations are resolved against the retrieved set — README DR-4/DR-10),
  3. adversarial cases in the golden evaluation set,
  4. this scanner, surfacing a flag in the UI and the document registry.
"""

from __future__ import annotations

import re

SUSPICIOUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions", re.I),
    ),
    (
        "instruction_override",
        re.compile(r"disregard\s+(all\s+|the\s+)?(previous|prior|above|your)\s+\w+", re.I),
    ),
    ("role_hijack", re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.I)),
    ("role_hijack", re.compile(r"\b(system|assistant)\s*:\s*", re.I)),
    (
        "prompt_leak",
        re.compile(r"(reveal|print|repeat|show)\s+(your|the)\s+(system\s+)?(prompt|instructions)", re.I),
    ),
    (
        "citation_forgery",
        re.compile(r"(cite|claim|say)\s+that\s+(this|the)\s+(policy|document|section)", re.I),
    ),
    ("guardrail_bypass", re.compile(r"(do\s+not|don't)\s+(refuse|mention|cite|disclose)", re.I)),
    ("exfiltration", re.compile(r"(send|post|upload)\s+(this|the|all)\s+\w+\s+to\s+https?://", re.I)),
    ("hidden_directive", re.compile(r"<\s*(script|iframe|object)\b", re.I)),
]

MAX_FLAGGED_EXCERPTS = 10


def scan_for_injection(text: str) -> list[str]:
    """Return a de-duplicated list of flag labels, each with a short excerpt for review."""
    flags: list[str] = []
    seen: set[str] = set()
    for label, pattern in SUSPICIOUS_PATTERNS:
        for match in pattern.finditer(text):
            if label in seen and len(flags) >= MAX_FLAGGED_EXCERPTS:
                break
            start = max(0, match.start() - 40)
            excerpt = text[start : match.end() + 40].replace("\n", " ").strip()
            flag = f"{label}: …{excerpt}…"
            if flag not in flags:
                flags.append(flag)
            seen.add(label)
            break  # one excerpt per pattern is enough to prompt a human review
    return flags[:MAX_FLAGGED_EXCERPTS]


def is_suspicious(text: str) -> bool:
    return bool(scan_for_injection(text))
