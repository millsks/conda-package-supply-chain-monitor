#!/usr/bin/env bash
#
# Take the local stack down, whatever state it was left in.
#
# `Ctrl-C` in the honcho terminal is the ordinary way, and it works. This script is
# for the other way the stack ends: the terminal closed, `kill -9` on honcho, a
# session hook tearing the shell down. Then honcho dies without forwarding SIGINT,
# its children are reparented to PID 1, and gunicorn keeps 8000, flower keeps 5555,
# and the worker keeps draining the queues -- for days, with nothing in `pixi.toml`
# that knows how to find them. The next `local-stack` then fails on the two bound
# ports, and the two containers it also brought up look like the cause because
# they are what `docker ps` shows.
#
# So this finds the stragglers by what they unambiguously are: a gunicorn or celery
# started from **this checkout's** dev environment. The match is on the interpreter
# path, not on the command name, so a worker from another repository's stack -- the
# sibling `django-python-generate-sbom` runs one with the same `-A config.celery_app`
# -- is left alone.
#
# It is deliberately a script and not a `cmd` in `pixi.toml`, on the same terms as
# `scripts/gate-redis.sh`: pixi runs task commands through `deno_task_shell`, which
# has no `for`, no `if` and no command substitution, and the escalation below needs
# all three. The pixi task is the entry point; this file is what it runs.
#
# `pkill -f` is macOS and Linux only, which is the same reach as the honcho line
# itself: `Procfile` runs gunicorn, and gunicorn is Unix-only.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# What the stack's processes have in common and nothing else does. `Procfile`
# runs every one of them with `-e dev`, so this is the only prefix they can have.
STRAGGLER="${REPO_ROOT}/.pixi/envs/dev/bin/(gunicorn|celery)"
# Celery's warm shutdown waits for in-flight tasks, and a collector mid-fetch can
# hold that for a while. The wait is long enough for an idle worker's ordinary
# exit and short enough that a stuck one does not make this command feel broken.
TERM_GRACE_SECONDS=10

# The pixi task above this script has already put us in the dev environment, so
# `docker compose` is the same one `docker-down` runs.

if ! pgrep -f "${STRAGGLER}" >/dev/null; then
    echo "local-stack-down: no stack processes running"
else
    # The gunicorn master forwards TERM to its worker and celery's main process to
    # its pool, so signalling every match is at worst redundant, never harmful.
    pkill -TERM -f "${STRAGGLER}"
    for _ in $(seq "${TERM_GRACE_SECONDS}"); do
        if ! pgrep -f "${STRAGGLER}" >/dev/null; then
            break
        fi
        sleep 1
    done

    # Recorded rather than assumed: a worker that is still here after the grace
    # period is one whose warm shutdown did not finish, and the two ports it does
    # not hold are not the reason this script was run. KILL is what actually
    # frees the machine, and saying so is what tells the developer a task was
    # interrupted mid-flight.
    if pgrep -f "${STRAGGLER}" >/dev/null; then
        echo "local-stack-down: still running after ${TERM_GRACE_SECONDS}s, sending KILL" >&2
        pkill -KILL -f "${STRAGGLER}"
        sleep 1
    fi

    if pgrep -f "${STRAGGLER}" >/dev/null; then
        echo "local-stack-down: could not stop these:" >&2
        pgrep -fl "${STRAGGLER}" >&2
        exit 1
    fi
    echo "local-stack-down: stack processes stopped"
fi

# The containers, last: a worker that loses its broker before it is told to stop
# spends its grace period reconnecting instead of exiting. `docker-down` keeps
# the data, as it does when run on its own; `docker-down-v` remains the way to
# discard it.
pixi run docker-down
