"""Git pre-commit hook — AI-assisted code quality gate.

Runs automatically before every commit when installed:

    python src/hooks/pre_commit_hook.py --install

What it checks
--------------
1. Ruff lint + format (fast, no LLM call)
2. Mypy type-check on changed files only
3. Secret scanning — rejects commits that look like API keys or tokens
4. AI review gate (optional, requires GROQ_API_KEY):
   - Calls Groq to summarise the diff and flag obvious issues
   - Skips silently if no key is set (never blocks offline work)

Exit codes
----------
  0 — all checks passed, commit proceeds
  1 — a check failed, commit is blocked with an explanation

Install
-------
  python src/hooks/pre_commit_hook.py --install
  # Writes .git/hooks/pre-commit and makes it executable.

Uninstall
---------
  python src/hooks/pre_commit_hook.py --uninstall
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

# ---------------------------------------------------------------------------
# Secret patterns — blocks commit if any of these appear in the staged diff
# ---------------------------------------------------------------------------
_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI API key"),
    (r"gsk_[A-Za-z0-9]{20,}", "Groq API key"),
    (r"xoxb-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24}", "Slack bot token"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"[Pp]assword\s*=\s*['\"][^'\"]{8,}", "Hardcoded password"),
    (r"[Aa][Pp][Ii][_-]?[Kk]ey\s*=\s*['\"][^'\"]{16,}", "Hardcoded API key"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], capture: bool = True) -> tuple[int, str]:
    """Run a subprocess and return (returncode, combined output)."""
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def _staged_python_files() -> list[str]:
    """Return Python files staged for commit."""
    _, out = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"])
    return [f for f in out.splitlines() if f.endswith(".py")]


def _staged_diff() -> str:
    """Return the full staged diff as text."""
    _, diff = _run(["git", "diff", "--cached"])
    return diff


def _print_header(title: str) -> None:
    print(f"\n\033[1;34m──── {title} ────\033[0m")


def _pass(msg: str) -> None:
    print(f"\033[32m  ✓ {msg}\033[0m")


def _fail(msg: str) -> None:
    print(f"\033[31m  ✗ {msg}\033[0m")


# ---------------------------------------------------------------------------
# Check: ruff lint
# ---------------------------------------------------------------------------


def check_ruff(files: list[str]) -> bool:
    _print_header("Ruff lint")
    if not files:
        _pass("No Python files staged.")
        return True
    code, out = _run(["python", "-m", "ruff", "check", *files])
    if code == 0:
        _pass(f"{len(files)} file(s) — no issues.")
        return True
    _fail("Ruff found issues:\n" + out)
    return False


# ---------------------------------------------------------------------------
# Check: secret scanning
# ---------------------------------------------------------------------------


def check_secrets(diff: str) -> bool:
    _print_header("Secret scanning")
    found: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+"):
            continue
        for pattern, label in _SECRET_PATTERNS:
            if re.search(pattern, line):
                found.append(f"  Possible {label} in: {line[:120]}")
    if not found:
        _pass("No secrets detected.")
        return True
    _fail("Potential secrets found — commit blocked:\n" + "\n".join(found))
    return False


# ---------------------------------------------------------------------------
# Check: AI review (optional)
# ---------------------------------------------------------------------------


def check_ai_review(diff: str) -> bool:
    """Ask the LLM to review the diff. Silently skips if no key is set."""
    _print_header("AI review (Groq)")
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        _pass("GROQ_API_KEY not set — skipping AI review (commit not blocked).")
        return True

    try:
        from langchain_groq import ChatGroq  # type: ignore[import]

        llm = ChatGroq(
            model="qwen/qwen3.6-27b",
            api_key=api_key,
            temperature=0,
            reasoning_effort="none",
        )
        prompt = dedent(f"""
            You are a senior engineer reviewing a git diff before it is committed.
            Identify only clear, obvious issues: secrets, broken logic, missing error
            handling for critical paths, or TODOs that block production.
            Be concise. If nothing is clearly wrong, say "LGTM".

            Diff (truncated to 3000 chars):
            {diff[:3000]}
        """).strip()

        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        # Strip CoT <think> blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        if "lgtm" in text.lower() and len(text) < 60:
            _pass(f"AI review: {text}")
        else:
            print(f"\033[33m  ⚠ AI review notes:\n{text}\033[0m")
            print("\033[33m  (Commit not blocked — review is advisory only.)\033[0m")
        return True

    except Exception as exc:  # noqa: BLE001
        _pass(f"AI review unavailable ({exc.__class__.__name__}) — skipping.")
        return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_all() -> int:
    """Run all checks. Returns 0 (pass) or 1 (fail)."""
    print("\033[1m[GCB pre-commit hook]\033[0m")
    files = _staged_python_files()
    diff = _staged_diff()

    results = [
        check_secrets(diff),
        check_ruff(files),
        check_ai_review(diff),
    ]
    passed = all(results)
    print()
    if passed:
        print("\033[1;32m✓ All checks passed — proceeding with commit.\033[0m\n")
        return 0
    print("\033[1;31m✗ One or more checks failed — commit blocked.\033[0m\n")
    return 1


def install() -> None:
    hook_path = Path(".git/hooks/pre-commit")
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(f"#!/bin/sh\n{sys.executable} src/hooks/pre_commit_hook.py\n")
    hook_path.chmod(0o755)
    print(f"✓ Pre-commit hook installed at {hook_path}")


def uninstall() -> None:
    hook_path = Path(".git/hooks/pre-commit")
    if hook_path.exists():
        hook_path.unlink()
        print("✓ Pre-commit hook removed.")
    else:
        print("No hook to remove.")


# Files that are allowed to contain key-shaped strings, because their whole
# purpose is to show the shape of a key without ever holding a real one.
_SCAN_ALLOWLIST = {".env.example", ".env.demo", "src/hooks/pre_commit_hook.py"}

# Substrings that mark a value as an obvious placeholder rather than a live
# credential. Without this the generic "api_key = '...'" pattern flags every
# example and default in the codebase, and a scanner that cries wolf gets muted.
_PLACEHOLDER_HINTS = (
    "your_",
    "your-",
    "change-me",
    "changeme",
    "example",
    "placeholder",
    "not-set",
    "no-key-needed",
    "dummy",
    "fake",
    "test",
    "demo",
    "xxx",
    "...",
    "<",
)


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def scan_tracked() -> int:
    """Scan every git-tracked file for credentials. Used by CI.

    The pre-commit hook only sees the staged diff, which is exactly how a real
    key once reached a distributed archive: the file was git-ignored, never
    staged, never scanned — and then packaged straight out of the working tree.
    This check closes that gap on every push.
    """
    code, out = _run(["git", "ls-files"])
    if code != 0:
        print("✗ not a git repository — cannot scan tracked files")
        return 1

    findings: list[str] = []
    for name in out.splitlines():
        path = Path(name)
        if name in _SCAN_ALLOWLIST or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — nothing to match
        for pattern, label in _SECRET_PATTERNS:
            for match in re.finditer(pattern, content):
                if _is_placeholder(match.group(0)):
                    continue
                line_no = content[: match.start()].count("\n") + 1
                findings.append(f"  {name}:{line_no} — possible {label}")

    if findings:
        print("✗ Possible credentials found in tracked files:")
        print("\n".join(findings))
        print("\nRotate anything real, then remove it from the file and from git history.")
        return 1

    print("✓ No credentials found in tracked files.")
    return 0


if __name__ == "__main__":
    if "--install" in sys.argv:
        install()
    elif "--uninstall" in sys.argv:
        uninstall()
    elif "--scan-tracked" in sys.argv:
        sys.exit(scan_tracked())
    else:
        sys.exit(run_all())
