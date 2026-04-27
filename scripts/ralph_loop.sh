#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<EOF
Usage: $(basename "$0") [AGENT] [PLAN]

Ralph-style loop: have AGENT drain unchecked tasks from PLAN.

Arguments:
    AGENT   Agent CLI: pi | claude-code   (default: pi)
    PLAN    Path to impl plan markdown    (default: docs/impl/shop_explore_implementation.md)

Options:
    -h, --help   Show this help and exit.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

AGENT="${1}"
PLAN="${2}"

case "$AGENT" in
    pi)          AGENT_CMD=(pi -p) ;;
    claude-code) AGENT_CMD=(claude -p --dangerously-skip-permissions) ;;
    *) echo "Error: unsupported agent: $AGENT (expected: pi | claude-code)" >&2; exit 2 ;;
esac

if [[ ! -f "$PLAN" ]]; then
    echo "Error: plan file not found: $PLAN" >&2
    exit 2
fi

PROMPT=$(cat <<EOF
Pick the most important task from @$PLAN
do it end-to-end (edit code, run tests)
then mark it "- [x]" in @$PLAN and commit with a summary.

If no unchecked tasks remain, print exactly "ALL TASKS ARE DONE" and stop.
otherwise NEVER put "ALL TASKS ARE DONE" in your response.
EOF
)

for i in {1..50}; do
    echo "=== Ralph iteration $i ($AGENT) ==="
    out=$("${AGENT_CMD[@]}" "$PROMPT" 2>&1 | tee /dev/tty)
    if grep -q "ALL TASKS ARE DONE" <<< "$out"; then
        echo "✅ task list drained"; break
    fi
    # safety: stop if no checkbox progress was made
    if ! git diff --quiet -- "$PLAN"; then git add -- "$PLAN"; fi
done
