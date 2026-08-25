---
name: generate-spec
description: Turn a feature description into a structured implementation spec with tasks
metadata:
  user-invocable: true
  disable-model-invocation: true
---

Turn this feature description into an implementation spec: `$ARGUMENTS`

## Steps

1. Call the spec agent:

   ```bash
   curl -sS -X POST http://localhost:8000/spec/generate \
     -H "Content-Type: application/json" \
     -d "{\"description\": \"$ARGUMENTS\"}"
   ```

   A 503 means no LLM is configured — this endpoint has no static fallback,
   unlike the playbook node. Tell me to set `GROQ_API_KEY` and stop.

2. Present the result as: intent, acceptance criteria, constraints, then the
   task list with dependencies.

3. Review the output critically before handing it to me. Flag any acceptance
   criterion that is not verifiable, and any task you would not be able to
   implement from its description alone. The point of a spec is that it can be
   executed without a follow-up conversation.
