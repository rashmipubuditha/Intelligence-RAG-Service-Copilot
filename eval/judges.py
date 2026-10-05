"""LLM-as-judge for faithfulness and answer relevance.

README DR-12 governs how these are used: judged scores are **indicative, never ground truth**.
The judge runs at temperature 0 with a versioned prompt, its per-claim reasoning is persisted
so a score can be inspected rather than trusted, and the deterministic metrics in metrics.py
remain the headline numbers. Judged metrics are always labelled as LLM-judged in reports.

Faithfulness is measured by claim decomposition rather than a holistic 1–5 score: "which of
these 6 claims is supported by the context" is a question a model answers far more reliably
than "rate this answer's groundedness", and the output can be audited claim by claim.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

JUDGE_PROMPT_VERSION = "v1"


class ClaimVerdict(BaseModel):
    claim: str
    supported: bool
    reason: str = ""


class FaithfulnessVerdict(BaseModel):
    claims: list[ClaimVerdict] = Field(default_factory=list)

    @property
    def score(self) -> float:
        if not self.claims:
            return 0.0
        return round(sum(1 for c in self.claims if c.supported) / len(self.claims), 4)


class RelevanceVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str = ""

    @property
    def normalised(self) -> float:
        return round((self.score - 1) / 4, 4)


FAITHFULNESS_SYSTEM_PROMPT = f"""You are a strict evaluator of grounding in retrieval-augmented answers. Prompt version: {JUDGE_PROMPT_VERSION}

You are given CONTEXT passages and an ANSWER. Decompose the ANSWER into individual factual claims, then decide for each claim whether it is supported by the CONTEXT.

A claim is supported ONLY if the CONTEXT states it. Being true in general, or plausible, or standard practice is NOT support. Numbers, thresholds and time limits must match the CONTEXT exactly to count as supported.

Ignore sentences that make no factual claim (greetings, hedging, statements about what the documents do not cover).

Return ONLY a single JSON object:

{{"claims": [{{"claim": "<the claim>", "supported": true|false, "reason": "<brief reason>"}}]}}
"""


RELEVANCE_SYSTEM_PROMPT = f"""You are a strict evaluator of answer relevance. Prompt version: {JUDGE_PROMPT_VERSION}

You are given a QUESTION, a REFERENCE ANSWER written by a domain expert, and a CANDIDATE ANSWER. Score how well the CANDIDATE answers the QUESTION, using the REFERENCE as the standard for completeness and correctness.

5 = fully answers the question; matches the reference on every material point
4 = answers the question; omits a minor detail
3 = partially answers; omits a material requirement or condition
2 = largely fails to answer, or is mostly off-target
1 = does not answer the question, or contradicts the reference

A correct refusal, when the reference says the corpus does not cover the question, scores 5.

Return ONLY a single JSON object:

{{"score": <1-5>, "reason": "<one sentence>"}}
"""


def judge_faithfulness(provider: Any, *, answer: str, context: str, timeout: int = 60) -> FaithfulnessVerdict:
    user_prompt = f"CONTEXT:\n{context}\n\n---\n\nANSWER:\n{answer}"
    raw = provider.generate_json(FAITHFULNESS_SYSTEM_PROMPT, user_prompt, timeout=timeout, temperature=0.0)
    return FaithfulnessVerdict.model_validate(raw)


def judge_relevance(
    provider: Any, *, question: str, reference: str, candidate: str, timeout: int = 60
) -> RelevanceVerdict:
    user_prompt = (
        f"QUESTION:\n{question}\n\n---\n\nREFERENCE ANSWER:\n{reference}\n\n---\n\n"
        f"CANDIDATE ANSWER:\n{candidate}"
    )
    raw = provider.generate_json(RELEVANCE_SYSTEM_PROMPT, user_prompt, timeout=timeout, temperature=0.0)
    return RelevanceVerdict.model_validate(raw)
