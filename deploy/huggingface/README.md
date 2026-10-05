---
title: Compliance Intelligence Copilot
emoji: 📑
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Grounded, cited answers over AML/KYC policy documents
---

# Compliance Intelligence Copilot

A retrieval-augmented assistant that answers questions about AML/KYC compliance
policies and shows exactly which document, version and section each claim comes
from.

- **Citations cannot be fabricated** — the server resolves them against the
  passages it actually retrieved and drops anything else.
- **Out-of-scope questions are refused in code**, not by asking the model nicely.
- **Conflicting policy versions are surfaced**, with both positions.
- **Retrieval quality is measured** on a 45-question golden set (recall@5 0.989).

## Using this demo

Ask a question on the Chat page, for example:

- *What documents are required for customer due diligence?*
- *When is enhanced due diligence required?*
- *How often must sanctions screening be repeated for medium-risk clients?*

The demo is **read-only**: anyone can ask questions and browse the five sample
policies. Uploading, deleting and changing settings need an API key.

The Space sleeps when idle, so the first visit after a while takes a minute or
two to wake. Storage is not persistent: conversations reset when it restarts.

## Configuration

Set under **Settings → Variables and secrets**:

| Secret | Purpose |
|---|---|
| `GROQ_API_KEY` | Required. The LLM provider key. |
| `API_KEY` | Optional. Enables uploads and other write operations for whoever holds it. |
