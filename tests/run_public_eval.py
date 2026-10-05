"""Standalone eval runner for the 5 public test questions.

Invokes `python main.py query ...` as a subprocess (the same way reviewers will) and
checks:
  - stdout is a valid JSON object matching our schema
  - citations include the expected primary-source document(s)
  - for Q5, the answer contains a refusal / escalation signal

No pytest dependency on purpose — keeps the repo deps minimal.

Run from the project root:
    python tests/run_public_eval.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CASES = [
    {
        "id": "Q1",
        "type": "Simple lookup",
        "question": (
            "What documents are required to verify Source of Wealth where a client's "
            "wealth comes from employment income?"
        ),
        "must_cite_any": ["02_source_of_wealth_verification_guidelines.md"],
        "answer_must_include_any": ["payslip", "employer", "bank statement"],
    },
    {
        "id": "Q2",
        "type": "Simple lookup",
        "question": ("How frequently must sanctions screening be repeated for existing medium-risk clients?"),
        "must_cite_any": ["03_sanctions_and_pep_screening_procedure.md"],
        "answer_must_include_any": ["quarterly"],
    },
    {
        "id": "Q3",
        "type": "Multi-document reasoning",
        "question": (
            "A client has been identified as a foreign PEP and also scores 72 on the "
            "risk assessment. What requirements apply?"
        ),
        "must_cite_any": [
            "05_risk_assessment_framework.md",
            "03_sanctions_and_pep_screening_procedure.md",
            "01_customer_due_diligence_policy.md",
        ],
        "must_cite_at_least": 2,
        "answer_must_include_any": ["EDD", "Enhanced Due Diligence", "enhanced due diligence"],
    },
    {
        "id": "Q4",
        "type": "Nuanced lookup",
        "question": (
            "A client submits a passport that expired 4 months ago. Is this acceptable "
            "as a primary identity document?"
        ),
        "must_cite_any": ["04_document_verification_standards.md"],
        "answer_must_include_any": ["6 months", "six months", "10 years", "ten years"],
    },
    {
        "id": "Q5",
        "type": "Hallucination guard",
        "question": (
            "What is the procedure for verifying Source of Wealth where a client's "
            "wealth originates entirely from cryptocurrency trading?"
        ),
        "must_cite_any": ["02_source_of_wealth_verification_guidelines.md"],
        "answer_must_include_any": [
            "MLRO",
            "escalate",
            "not covered",
            "does not cover",
            "not recognised",
            "not recognized",
        ],
    },
]


def run_query(question: str, k: int = 3) -> tuple[str, str, int]:
    proc = subprocess.run(
        [sys.executable, "main.py", "query", "--question", question, "--k", str(k)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.stdout, proc.stderr, proc.returncode


def evaluate(case: dict, response: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []

    if not isinstance(response.get("question"), str):
        failures.append("response.question is not a string")
    if not isinstance(response.get("citations"), list):
        failures.append("response.citations is not a list")
    if not isinstance(response.get("latency_ms"), int):
        failures.append("response.latency_ms is not an int")
    if not isinstance(response.get("timestamp"), str):
        failures.append("response.timestamp is not a string")

    if response.get("error"):
        failures.append(f"error field set: {response['error']}")

    cited_docs = {c.get("document", "") for c in response.get("citations", [])}
    expected = case.get("must_cite_any", [])
    hits = cited_docs & set(expected)
    min_hits = case.get("must_cite_at_least", 1)
    if len(hits) < min_hits:
        failures.append(
            f"citations missing required doc(s); got {sorted(cited_docs)}, "
            f"expected at least {min_hits} of {expected}"
        )

    answer = (response.get("answer") or "").lower()
    needed = [kw.lower() for kw in case.get("answer_must_include_any", [])]
    if needed and not any(kw in answer for kw in needed):
        failures.append(f"answer missing any of {case['answer_must_include_any']!r}")

    return (not failures), failures


def main() -> int:
    print(f"Running {len(CASES)} public eval cases via main.py subprocess...\n")
    fail_count = 0

    for case in CASES:
        print(f"=== {case['id']} ({case['type']}) ===")
        print(f"Q: {case['question']}")

        try:
            stdout, stderr, _rc = run_query(case["question"])
        except subprocess.TimeoutExpired:
            print("  RESULT: FAIL — query timed out\n")
            fail_count += 1
            continue

        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as e:
            print(f"  RESULT: FAIL — stdout not valid JSON ({e})")
            print(f"  STDOUT[:400]: {stdout[:400]!r}")
            print(f"  STDERR[:400]: {stderr[:400]!r}\n")
            fail_count += 1
            continue

        ok, failures = evaluate(case, response)
        cited = sorted({c.get("document", "") for c in response.get("citations", [])})
        answer = response.get("answer", "")
        latency = response.get("latency_ms", "?")

        print(f"  cited: {cited}")
        print(f"  latency_ms: {latency}")
        print(f"  answer: {answer[:240]}{'...' if len(answer) > 240 else ''}")
        if ok:
            print("  RESULT: PASS\n")
        else:
            fail_count += 1
            print("  RESULT: FAIL")
            for f in failures:
                print(f"    - {f}")
            print()

    total = len(CASES)
    passed = total - fail_count
    print(f"=== Summary: {passed}/{total} passed ===")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
