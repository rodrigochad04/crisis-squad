# AI Enablement Workshop Guide

> **Purpose:** A practical 90-minute session for engineering teams who have access to AI
> coding tools but are using them inconsistently — or not at all.
>
> This is not a demo session. By the end, every participant will have used the tools on
> real work from their current sprint.

---

## Before the session

**Facilitator prep (30 min)**

- [ ] Clone the repo and verify `DEMO_MODE=true` works in 3 commands
- [ ] Confirm the team has access to Claude Code, Cursor, GitHub Copilot, or similar
- [ ] Ask the tech lead for 2–3 real tasks from the current sprint
- [ ] Read the team's recent pull requests to understand their current patterns

**What you need to know about this team (fill in before)**

| Question | Answer |
|---|---|
| Primary language | |
| Current AI tools available | |
| Typical ticket type (feature / bug / infra) | |
| Biggest pain point right now | |
| Sceptic to watch for | |

---

## Session structure

### Part 1 — Calibration (15 min)

**Goal:** Understand where people actually are, not where they think they should be.

Ask the room (show of hands or sticky notes):

1. Who uses an AI coding assistant daily?
2. Who uses it for writing code? For understanding code? For writing tests?
3. Who has had it confidently produce something completely wrong?
4. Who has a prompt or workflow they use consistently?

**Why this matters:** You need to know whether you're dealing with non-users, casual users,
or inconsistent power users. Each group needs a different conversation.

---

### Part 2 — Live contrast (20 min)

**Goal:** Show the gap between "using AI" and "using AI effectively."

Pick one real task from the team's current sprint. Show two versions:

**Version A — typical usage:**
> "Write a function that parses a JSON response and extracts the user ID."

**Version B — specification-first:**
> Use `/generate-spec` or the SpecificationAgent to produce a structured spec first,
> then hand the spec to the LLM for implementation.

Show the difference in output quality. Let the team compare the two results.

**Key point to land:** The bottleneck is rarely the LLM's capability. It's the quality of
the intent you give it. A 30-second spec prevents 20 minutes of back-and-forth.

---

### Part 3 — Hands-on exercise (35 min)

**Goal:** Every person leaves having done this themselves, not just watched.

Split into pairs. Each pair picks one real task from their sprint.

**Exercise (25 min):**

1. Write the task as a user story: "As a [role], I want [feature] so that [outcome]"
2. Run it through `/generate-spec` (or `POST /spec/generate`)
3. Review the output:
   - Do the acceptance criteria match what you actually want?
   - Are there clarifying questions you hadn't thought of?
   - Are the task estimates reasonable?
4. Use the spec as the prompt to your AI coding tool
5. Compare the implementation to what you'd have gotten from step 1 directly

**Debrief (10 min):**

- Which pairs got clearer acceptance criteria than they started with?
- Which clarifying questions were genuinely important?
- What would you change about how you wrote the user story?

---

### Part 4 — Quality gates conversation (10 min)

**Goal:** Introduce the idea that AI-generated code needs the same review discipline as
human-written code — and that hooks + evaluation can automate part of this.

Demonstrate the pre-commit hook:

```bash
python src/hooks/pre_commit_hook.py --install
# Make a small change, stage it, attempt a commit
git add . && git commit -m "test"
```

Show:
1. Secret scanning (non-negotiable)
2. Ruff lint (fast, no LLM)
3. Optional Groq review (advisory, never blocks)

**Key point:** Hooks are not about distrust. They're about making the safe path the easy
path, so no one has to remember to check.

---

### Part 5 — Next steps (10 min)

Don't leave the room without concrete commitments.

**For each participant, agree on one of:**

| Commitment | Who | By when |
|---|---|---|
| Use `/generate-spec` on next ticket before touching code | | |
| Install pre-commit hook on one repo | | |
| Write one evaluation test for a tool they already use | | |
| Share a prompt/workflow that works with the team | | |

**For the team:**

- [ ] Agree on one shared AI-enabled process to try for the next sprint
- [ ] Book a 20-min retro in 2 weeks to check: what worked, what didn't

---

## Common objections and responses

| Objection | Response |
|---|---|
| "The AI is often wrong" | Correct — which is why we have the HitL gate, the eval harness, and the pre-commit hook. The goal isn't blind trust, it's structured oversight. |
| "I'm faster without it" | Probably true for tasks you've done 100 times. The question is: what about the next task type? And: are you faster, or just more comfortable? |
| "It doesn't understand our codebase" | Feed it the spec and the relevant file. It doesn't need to understand everything — it needs to understand the task. |
| "Our code is too sensitive to share with an LLM" | DEMO_MODE=true — everything here runs locally. Groq sends the playbook text, not your production secrets. |
| "We already tried this and it didn't work" | What specifically didn't work? (Usually: no spec, no eval, no hook. The tool was good; the workflow wasn't.) |

---

## What success looks like (2 weeks later)

- At least 2 people are using spec-first consistently
- Pre-commit hook installed on at least 1 repo
- At least 1 evaluation test written for a real tool
- 1 team retro item about AI process (not just AI tool)

If none of these happened, the session failed — regardless of how good the demo was.
The goal is adoption, not demonstration.

---

## Facilitator notes

**For sceptical engineers:** Don't try to convince them. Give them the exercise and let the
output do the work. Sceptics who produce a genuinely better spec in 5 minutes become the
loudest advocates.

**For executives in the room:** The DORA metrics dashboard (`/metrics`) speaks their
language. MTTR, approval rate, cost per incident — these are business outcomes, not demos.

**For the team lead:** The most important thing you can do after this session is ask about
it in the next sprint review. If it never comes up, it never happened.
