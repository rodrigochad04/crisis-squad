---
description: Run the evaluation harness and summarise what passed, failed, or skipped
allowed-tools: Bash(pytest:*), Bash(python:*), Read
---

Run the evaluation suite and interpret the results.

## Steps

1. Run everything:

   ```bash
   pytest evaluation/ -v --tb=short
   ```

2. Break the results down by what each group actually proves:

   | Group | What it proves | Needs an LLM |
   |---|---|---|
   | `test_governance.py` | The HitL gate cannot be bypassed, decisions are immutable, auth is wired | no |
   | `TestInstanaClient` | FAIL_FAST / SATURATION / LATENCY_DEGRADATION classification | no |
   | `TestJiraTools` | ISO timestamp parsing, ADF text extraction | no |
   | `TestHitLGate` | Approval payloads carry the required NIST-style fields | no |
   | `TestPlaybook` | All six mandatory sections, kubectl commands, numeric criteria | partly |
   | `TestInstanaDiagnosis` | Faithfulness and absence of hallucinated fields | yes |

3. If tests were skipped, say which and why. Skips here mean no `GROQ_API_KEY`
   is set, so the LLM-graded metrics could not run — report that as reduced
   coverage, not as a pass.

4. For any failure, quote the assertion and name the file and line.
