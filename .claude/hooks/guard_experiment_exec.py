#!/usr/bin/env python3
"""PreToolUse(Bash) safety gate for AI-Scientist experiment execution.

AI-Scientist runs LLM-written code. Upstream's README explicitly warns this is
risky (dangerous packages, uncontrolled net access, runaway processes) and says
to sandbox it. We can't add a container here, so this hook is a focused safety
net: it **denies** a small set of genuinely dangerous shell patterns and stays
neutral on everything else (so your normal Claude Code permissions still apply).

Decision protocol: on a dangerous match we emit a PreToolUse `deny` decision.
Otherwise we exit 0 with no decision (neutral). The hook never hard-fails.
"""

import json
import re
import sys

# (compiled regex, human reason). Patterns run against the raw command string.
RULES = [
    (r"\bsudo\b|\bdoas\b|\bsu\s+-", "privilege escalation (sudo/su/doas) is not allowed in experiments"),
    (r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r",  # rm -rf / -fr / -r -f
     "recursive force-delete — keep deletions inside the run dir, this looks unsafe"),
    (r"\bmkfs\b|\bdd\b[^\n]*\bof=/dev/|>\s*/dev/(sd|disk|nvme)|diskutil\s+.*erase",
     "raw disk / device write"),
    (r"(curl|wget|fetch)\b[^|;&]*[|]\s*(sudo\s+)?(ba|z|c|tc|k)?sh\b",
     "piping a downloaded script straight into a shell"),
    (r"(curl|wget|fetch)\b[^|;&]*[|]\s*python[0-9.]*\b",
     "piping downloaded content into python"),
    (r"(/etc/shadow|/etc/sudoers|~/\.ssh/|/\.ssh/id_|~/\.aws/credentials|\.aws/credentials)",
     "access to credentials / secret material"),
    (r"\bsecurity\s+find-(generic|internet)-password\b|\bkeychain\b.*\bdump",
     "macOS keychain credential extraction"),
    (r"\bcrontab\b|\blaunchctl\s+(load|unload|bootstrap)|/Library/LaunchDaemons|/Library/LaunchAgents",
     "installing a persistence mechanism"),
    (r"(^|[\s;&|])(>|>>)\s*/etc/|tee\s+/etc/", "writing into /etc"),
    (r"\bkillall\b|\bpkill\s+-9\b|\bkill\s+-9\s+-1\b", "broad process kill"),
    (r"\.claude/(settings(\.local)?\.json|hooks/)", "modifying Claude Code config / hooks (guard tamper)"),
    (r"\bchmod\s+-R?\s*0?777\b", "world-writable chmod 777"),
]
COMPILED = [(re.compile(p, re.IGNORECASE), why) for p, why in RULES]


def deny(reason: str):
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"[guard-experiment-exec] Blocked: {reason}. "
                f"Redesign the experiment to stay inside the run directory and "
                f"avoid this action — do not try to bypass the guard."
            ),
        }
    }
    print(json.dumps(out))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        sys.exit(0)

    for rx, why in COMPILED:
        if rx.search(command):
            deny(why)

    sys.exit(0)  # neutral: defer to normal permissions


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
