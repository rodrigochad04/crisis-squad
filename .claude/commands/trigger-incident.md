---
description: Run the incident response graph for an Instana incident, up to the HitL gate
argument-hint: [incident_id]
allowed-tools: Bash(curl:*), Bash(python:*), Read
---

Trigger an incident response run for incident `$ARGUMENTS`.
If `$ARGUMENTS` is empty, use the built-in demo incident `QKTtAivDTAaKvCGqvQOWpA`.

## Steps

1. Check whether the API is already running:

   ```bash
   curl -sf http://localhost:8000/health || echo "not running"
   ```

   If it is not running, start it in the background:

   ```bash
   uvicorn src.api.server:app --port 8000 &
   ```

2. Trigger the run and capture the `run_id` from the response:

   ```bash
   curl -sS -X POST http://localhost:8000/incidents \
     -H "Content-Type: application/json" \
     -d "{\"incident_id\": \"$ARGUMENTS\"}"
   ```

   If the API returns 401, it has `API_AUTH_ENABLED=true`. Add
   `-H "Authorization: Bearer $API_SECRET_KEY"`.

3. Follow the run until it reaches the gate:

   ```bash
   curl -N --max-time 120 http://localhost:8000/incidents/<run_id>/stream
   ```

4. Report back to me, in this order:
   - the failure pattern and the metrics with their baselines
   - the Jira precedent and its historical MTTR
   - which knowledge base backend answered (`faiss` or `keyword-fallback`)
   - whether the playbook came from the LLM or the static fallback
   - the `approval_id` and the exact action awaiting approval

Do not call `/approve`. The run stops at the governance gate by design; approving
is a separate, deliberate act — use `/approve-incident` once I have read the playbook.
