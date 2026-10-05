# AI Engineer Take-Home Assignment
## Compliance Document Intelligence

---

### Background

You are building a backend service for a regulated compliance platform. Compliance officers at law firms need to query a library of AML/KYC policy documents and receive grounded, cited answers that are fully auditable.

---

### Materials Provided

- A folder of **5 compliance policy documents** (`.md` files)
- A **public test question set** — 5 questions with expected answers so you can verify your system is working

---

### What You Must Build

A backend service in **any programming language you are comfortable with**, with two commands:

#### Command 1: `ingest`

Reads the provided policy documents, chunks them, embeds them, and stores them in a local vector store of your choice. A simple local persistent store is sufficient — Chroma, FAISS, LanceDB, or a documented in-memory implementation are all acceptable. You do not need to set up a cloud database.

```
<your_entry_point> ingest --docs <path_to_policies_folder>
```

Example:
```bash
python main.py ingest --docs ./policies
node main.js ingest --docs ./policies
```

#### Command 2: `query`

Accepts a natural-language compliance question and returns a structured JSON response.

```
<your_entry_point> query --question "<question text>" [--k <number>]
```

`--k` controls how many chunks are retrieved. If omitted, default to `3`.

Example:
```bash
python main.py query --question "What documents are required for Source of Wealth verification?" --k 3
node main.js query --question "What documents are required for Source of Wealth verification?" --k 3
```

---

### Output Format

The `query` command must print a valid JSON object to **stdout**. The structure must match this schema:

```json
{
  "question": "What documents are required for Source of Wealth verification?",
  "answer": "...",
  "citations": [
    {
      "document": "02_source_of_wealth_verification_guidelines.md",
      "chunk": "..."
    }
  ],
  "model": "claude-3-5-sonnet-20241022",
  "latency_ms": 412,
  "timestamp": "2026-04-05T14:32:00Z"
}
```

All responses must be validated against a **schema** before being returned (Zod, Pydantic, Marshmallow, or equivalent for your language). If the LLM output fails validation, handle the error explicitly — do not silently return malformed data.

On any failure (validation error, API error, empty retrieval result), **always return the same JSON schema** — set `answer` to an empty string or a brief description, `citations` to an empty array, and include an additional `"error"` field with a short description of what went wrong. Never return plain text to stdout or exit with only a stderr message.

---

### Audit Log

Every `query` call — success or failure — must **append** a structured entry to an audit log file in your project root named `audit.log`, using JSON Lines format (one JSON object per line).

Each entry must contain:

- Full question text
- Full structured response (or error details)
- Model used, latency in ms, timestamp
- The exact document chunks passed to the LLM as retrieval context

The goal: a compliance officer must be able to reconstruct *exactly what information the AI was given and what it said* for any past query.

---

### Technical Requirements

a) Use any LLM provider (Anthropic, OpenAI, Google). Document and justify your model choice in the README.  
b) All LLM responses must be validated with a schema. Handle validation failures explicitly — log the failure and return a structured error response, do not crash.  
c) API keys must **never** appear in code or be committed to the repository. Provide a `.env.example` file listing every required environment variable.  
d) Document your chunking strategy (chunk size, overlap, rationale) in the README.  
e) Retrieval must return the top-k most relevant chunks. Pass `--k <number>` to the query command to control this. If `--k` is omitted, default to `3`.  
f) Include query latency in every response (`latency_ms`).  
g) Handle gracefully: missing documents folder, LLM API errors, questions that return no relevant chunks.  
h) For embeddings, any provider is acceptable — OpenAI, Google, Cohere, Voyage, or a local model via SentenceTransformers or equivalent. Document your choice in the README.

---

### Interface Contract (Important)

Because we will test every submission the same way, your implementation **must** honour the following contract exactly:

| Requirement | Detail |
|---|---|
| Entry point | A single file at the project root: `main.py`, `main.js`, `main.ts`, or `main.go` |
| Ingest command | `<entry_point> ingest --docs <folder_path>` |
| Query command | `<entry_point> query --question "<text>" [--k <number>]` — `k` defaults to `3` if omitted |
| Query stdout | A single valid JSON object matching the schema above. No extra text before or after the JSON. |
| Audit log file | Named `audit.log` in the project root, JSON Lines format |
| Environment variables | Defined in `.env.example` at the project root |
| Setup | `README.md` must contain a **Setup** section with the exact commands to install dependencies and run the service |

If your language or framework requires a build step (e.g. TypeScript compilation), document the build command clearly and ensure `main.js` (or equivalent compiled output) is the runnable entry point after the build.

---

### General Guidelines

a) Use any programming language you are comfortable with.  
b) Provide a **README** with: setup instructions, architecture overview, and **at least one written decision record** — a short paragraph explaining a non-trivial choice you made (chunking strategy, vector store selection, retrieval approach, model choice).  
c) Submit via a **public GitHub repository**. The repository must be clean: no committed secrets, no `.env` file.

---

### Evaluation

| Dimension | What We Are Looking For |
|---|---|
| **RAG quality** | Do citations actually support the answers? Are edge cases handled? |
| **Code quality** | Clean structure, proper error handling, no unreviewed shortcuts |
| **Structured output + validation** | Schema defined, validation enforced, failures handled |
| **Audit log** | Complete, structured, genuinely auditable |
| **Documentation** | README clarity + at least one defensible decision record |

---

### Timeline & Submission

- **Deadline:** Complete the assignment before 11.59 PM on Sunday, 17th May 2026.
- Submit early if you finish ahead of time.
- Upload your project to a **public GitHub repository** and reply with the repository link.

Good luck. We look forward to reviewing your submission.
