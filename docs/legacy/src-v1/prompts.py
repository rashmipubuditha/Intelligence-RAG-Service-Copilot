"""LLM prompt templates.

The system prompt enforces three things that drive eval quality:
  1. Grounding — answer only from the supplied context.
  2. Explicit refusal — when the answer is not in the context, say so and point to the
     documented escalation path. This is the lever that passes Q5 (cryptocurrency SoW).
  3. Citation IDs only — the model returns a list of integer chunk IDs it relied on.
     We assemble the citation objects ourselves from the retriever output, which makes
     citation fabrication structurally impossible (see DR-4 in the README).
"""

from __future__ import annotations

from src.schemas import RetrievedChunk


SYSTEM_PROMPT = """You are a compliance assistant for an AML/KYC platform. You answer compliance questions using ONLY the policy excerpts provided to you in the user message.

Follow these rules exactly:

1. Use ONLY the information in the numbered CONTEXT CHUNKS below. Do not use outside knowledge, training data, or assumptions.
2. If the context does not contain enough information to answer the question, say so explicitly. If the policies prescribe an escalation path (for example, escalate to the MLRO), state it. Do NOT invent a procedure.
3. Never invent or guess policy section numbers, document names, numeric thresholds, document names, or rules. Only reference what appears in the context.
4. Be concise, factual, and specific. Where the context gives a list of requirements, list them. Where it gives a threshold, state it.
5. Respond with a SINGLE JSON object — nothing before it, nothing after it — matching this schema exactly:

{
  "answer": "<your answer as plain prose>",
  "used_chunk_ids": [<integer chunk IDs from the context that you actually relied on>]
}

6. `used_chunk_ids` must contain only integer IDs that appear in the CONTEXT CHUNKS below. Do not invent IDs. If you could not answer from the context, return an empty list.
"""


REPAIR_SYSTEM_PROMPT = """Your previous response was not valid JSON in the required schema. Return ONLY a single JSON object, with no markdown fences, no prose before or after, matching exactly:

{
  "answer": "<plain text answer>",
  "used_chunk_ids": [<integer chunk IDs>]
}
"""


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        context_block = "(No context chunks were retrieved for this question.)"
    else:
        parts: list[str] = []
        for rc in chunks:
            parts.append(f"[CHUNK {rc.chunk.chunk_id}]\n{rc.chunk.text}")
        context_block = "\n\n---\n\n".join(parts)

    return (
        "CONTEXT CHUNKS:\n\n"
        f"{context_block}\n\n"
        "---\n\n"
        f"QUESTION:\n{question}\n\n"
        "Respond with a single JSON object as specified in the system message."
    )
