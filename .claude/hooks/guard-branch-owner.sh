#!/usr/bin/env bash
# Refuse a git commit on a branch another Claude session already committed to.
#
# Two sessions sharing one branch -- and, worse, one working directory -- is how
# uncommitted work gets swept into somebody else's commit and how two pipelines
# race the same PR. This is a PreToolUse guard on Bash: it fires before the
# commit, not after, because after is too late to be useful.
#
# Ownership is recorded per branch in the git directory, so it is per clone,
# never committed, and disappears with the checkout it describes. The trailer
# scan is the second signal: it survives a wiped marker file, because the
# evidence is in the commits themselves.
set -uo pipefail

payload=$(cat)
command=$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')
session=$(printf '%s' "$payload" | jq -r '.session_id // ""')

# Only a commit. `git commit-tree`, `git commit --dry-run` and anything that
# merely mentions the word are none of this guard's business.
case "$command" in
    *"git commit"*) ;;
    *) exit 0 ;;
esac
case "$command" in
    *--dry-run*) exit 0 ;;
esac

# The git commit does not necessarily run in this session's working directory.
# `cd <dir> && git commit` and `git -C <dir> ...` both target somewhere else, and a
# linked worktree is on its own branch. Reading HEAD here judged the wrong
# branch: a worktree write was refused for a branch it was not on, naming a
# session that had nothing to do with it. Resolve the directory git will use.
target_dir=""
if [[ "$command" =~ git[[:space:]]+-C[[:space:]]+([^[:space:]]+) ]]; then
    target_dir="${BASH_REMATCH[1]}"
elif [[ "$command" =~ (^|[[:space:]\;\&\|])cd[[:space:]]+([^[:space:]\;\&\|]+) ]]; then
    target_dir="${BASH_REMATCH[2]}"
fi
target_dir="${target_dir%\"}"; target_dir="${target_dir#\"}"
target_dir="${target_dir%\'}"; target_dir="${target_dir#\'}"
{ [ -n "$target_dir" ] && [ -d "$target_dir" ]; } || target_dir="."

git -C "$target_dir" rev-parse --git-dir >/dev/null 2>&1 || exit 0
branch=$(git -C "$target_dir" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
[ "$branch" = "HEAD" ] && exit 0

# The default branch is governed by review, not by this guard, and marking it
# owned would refuse every session that ever touches it.
default_branch=$(git -C "$target_dir" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
default_branch=${default_branch#origin/}
[ -z "$default_branch" ] && default_branch=main
[ "$branch" = "$default_branch" ] && exit 0

deny() {
    jq -n --arg reason "$1" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: $reason
        }
    }'
    exit 0
}

# Second signal first: more than one Claude session already in this branch's own
# commits means the branch is shared whatever the marker file says.
trailers=$(git -C "$target_dir" log --format='%(trailers:key=Claude-Session,valueonly)' \
    "$default_branch..HEAD" 2>/dev/null | sed '/^$/d' | sort -u)
# `printf '%s\n'` and not `printf '%s'`: without the newline the last line is
# unterminated and `wc -l` reports one fewer, so two sessions counted as one and
# the guard stayed silent exactly when it should fire.
trailer_count=$(printf '%s\n' "$trailers" | sed '/^$/d' | wc -l | tr -d ' ')
if [ "${trailer_count:-0}" -gt 1 ]; then
    deny "Branch '$branch' already carries commits from $trailer_count different Claude sessions. Two sessions on one branch is how work gets swept into another session's commit. Create your own branch, or confirm with the user that the other session is finished."
fi

# --git-common-dir, not --git-dir: inside a linked worktree the latter is
# .git/worktrees/<name>, so every worktree kept a private registry and none could
# see what the others owned. Ownership is per clone, so the registry is too.
common_dir=$(git -C "$target_dir" rev-parse --git-common-dir 2>/dev/null) || exit 0
case "$common_dir" in
    /*) ;;
    *) common_dir=$(cd "$target_dir" && cd "$common_dir" && pwd) || exit 0 ;;
esac
owners="$common_dir/claude-branch-owners"
[ -f "$owners" ] || : > "$owners"
recorded=$(awk -F'\t' -v b="$branch" '$1 == b {print $2; exit}' "$owners")

if [ -n "$recorded" ] && [ -n "$session" ] && [ "$recorded" != "$session" ]; then
    deny "Branch '$branch' is already owned by Claude session $recorded, and this is session $session. Two sessions sharing one branch and one working directory is how uncommitted work gets committed by the wrong session. Create your own branch, or confirm with the user that the other session is finished — then clear the entry in $owners."
fi

if [ -z "$recorded" ] && [ -n "$session" ]; then
    printf '%s\t%s\n' "$branch" "$session" >> "$owners"
fi
exit 0
