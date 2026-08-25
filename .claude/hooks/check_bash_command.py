#!/usr/bin/env python3
"""PreToolUse hook for the Bash tool.

Blocks two categories of command:

1. Destructive operations (schema drops/downgrades, force pushes, rm -rf, hard resets).
2. Anything that reads, copies, or exfiltrates a secret/credential file's *contents*.

Category 2 deliberately distinguishes reading a secret path from writing/creating
one: `echo "X=1" > .env` or `cat > .env <<EOF` are allowed (the file's own new
content isn't a leak of anything), while `cat .env`, `cp .env dst`, `grep X .env`,
or piping/curling it anywhere are blocked. This exists because a blanket
"any mention of .env is blocked" rule also blocks legitimate bootstrap file
creation, which in turn invites agents to route around it instead of asking —
that is worse than the narrow rule this replaces. If a command is blocked and
there is no permitted way to accomplish the same legitimate goal (e.g. via the
Write tool, which is not gated by this hook), the correct response is to stop
and tell the user, never to construct a workaround.
"""
import json
import re
import sys

SECRET_PATTERN = re.compile(
    r'(\.env(?!\.(?:example|sample|template))\b|secrets/|credentials/|\.pem\b|\.key\b|\.aws/credentials|kubeconfig)',
    re.IGNORECASE,
)
DESTRUCTIVE_PATTERN = re.compile(
    r'(alembic\s+downgrade|drop\s+table|drop\s+database|truncate\s+table|git\s+push\s+(?:--force|-f)\b|rm\s+-rf|reset\s+--hard)',
    re.IGNORECASE,
)
OPERATOR_PATTERN = re.compile(r'(>>|>|\||;|&&)')
WRITE_OPERATORS = ('>', '>>')


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        sys.exit(0)

    if DESTRUCTIVE_PATTERN.search(cmd):
        deny(
            "Blocked: command appears destructive (schema drop/downgrade, force "
            "push, rm -rf, or hard reset). Get explicit user confirmation and run "
            "it manually if it is truly needed."
        )

    for match in SECRET_PATTERN.finditer(cmd):
        before = cmd[:match.start()]
        ops = OPERATOR_PATTERN.findall(before)
        nearest_op = ops[-1] if ops else None
        if nearest_op not in WRITE_OPERATORS:
            deny(
                "Blocked: command appears to read or access a secret/credential "
                "path (.env, secrets/, credentials/, .pem, .key, .aws/credentials, "
                "kubeconfig) other than as a plain write target. Creating a file "
                "via `> path` or `>> path` is allowed; reading, copying, piping, "
                "or grepping one is not. Use the Write tool to create secret "
                "files instead of Bash. Do not attempt to route around this "
                "check — if you have no permitted way to do what you need, stop "
                "and tell the user."
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
