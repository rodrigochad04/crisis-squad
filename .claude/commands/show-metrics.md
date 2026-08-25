---
description: Show DORA + SPACE metrics and LLM cost for the current session
allowed-tools: Bash(curl:*)
---

Fetch and interpret the engineering metrics for this session.

## Steps

1. Pull both endpoints:

   ```bash
   curl -sS http://localhost:8000/metrics/dora
   curl -sS http://localhost:8000/metrics/cost
   ```

2. Present a short table: MTTR against the 30-minute target, change failure
   rate, approval rate, average agents per incident, and the phase timing
   breakdown for the most recent run.

3. Then state plainly which of these are proxies rather than true DORA
   measurements. In this system "deployment frequency" counts incidents handled
   per demo session, and MTTR measures how long the pipeline itself took, not
   how long a real outage lasted. Say so — a metric presented without its
   definition is worse than no metric.
