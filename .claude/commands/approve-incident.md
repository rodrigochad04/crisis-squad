---
description: Submit a Human-in-the-Loop decision for a run paused at the governance gate
argument-hint: [run_id] [APPROVED|REJECTED]
allowed-tools: Bash(curl:*), Read
---

Record a human decision for the run in `$ARGUMENTS`.

Parse `$ARGUMENTS` as `<run_id> <APPROVED|REJECTED>`. If either part is missing,
stop and ask me — never guess a decision.

## Steps

1. Show me what I am about to approve before doing anything:

   ```bash
   curl -sS http://localhost:8000/incidents/<run_id>
   curl -sS http://localhost:8000/incidents/<run_id>/playbook
   ```

   Summarise the pending action, its risk level, and the rollback procedure.
   If `approval_status` is not `PENDING`, stop: the run either has not reached
   the gate or has already been decided.

2. Submit the decision:

   ```bash
   curl -sS -X POST http://localhost:8000/incidents/<run_id>/approve \
     -H "Content-Type: application/json" \
     -d '{"decision": "<DECISION>", "decided_by": "<my name>", "notes": "<why>"}'
   ```

3. Report the resulting audit entry.

## Expected failures

These are the gate working, not bugs — report them as such:

- **409 "has not reached the Human-in-the-Loop gate"** — the run is still executing.
- **409 "already decided"** — decisions are immutable; the first one stands.
- **401** — the API requires a bearer token.
