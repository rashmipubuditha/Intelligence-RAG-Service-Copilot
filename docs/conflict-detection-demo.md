# Demo fixtures

These files are **not part of the compliance corpus**. They exist to demonstrate and test
behaviour that the supplied corpus cannot exercise on its own, and they are deliberately kept
outside `policies/` so that `python main.py ingest --docs ./policies` never picks them up and
no evaluation run is skewed by them.

| File | Demonstrates |
|---|---|
| `01_customer_due_diligence_policy_v1.9.md` | **Conflict detection.** A genuine earlier version of the CDD Policy whose review-frequency and EDD rules contradict v2.1. Ingesting it alongside the real corpus makes the system surface both positions with their versions and effective dates instead of silently answering from one. |

To see conflict detection in action:

```bash
python main.py ingest --docs ./policies            # the real corpus (v2.1)
python main.py ingest --docs ./fixtures            # adds the superseded v1.9
python main.py query --question "How often must a high-risk client relationship be reviewed?"
```

The response will carry a populated `conflicts` array. Remove it again with
`python main.py documents` to find the id, then `DELETE /api/documents/{id}` or re-ingest the
corpus from scratch.

**Honest note:** structural conflict detection (same document family, different version or
effective date) is exact — it is arithmetic over metadata. Semantic conflict detection, where
two documents disagree without declaring different versions, is left to the prompt to surface
and is labelled best-effort in the UI.
