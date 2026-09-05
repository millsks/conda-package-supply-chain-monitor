#!/usr/bin/env bash
#
# Run the gate's test step against a real Redis, the way the gate job runs it.
#
# The sibling of `scripts/gate-postgres.sh`, and it exists for a sharper reason
# than parity. `core/rate_limit.py` writes `add`-then-`incr` so that two worker
# *processes* racing a new window increment one counter rather than one resetting
# the other. Under the `LocMemCache` a local run uses, each process holds its own
# counter -- so that property cannot fail, every case in the unit suite passes
# against a limiter that loses the race, and the reasoning is unverified prose.
# `tests/integration/django_apps/test_shared_allowance.py` is the case that can
# fail, and it needs this container to run at all.
#
# The variable is the whole mechanism, exactly as `DATABASE_URL` is for the
# PostgreSQL gate: `config/settings/test.py` selects
# `django_redis.cache.RedisCache` when `CPM_TEST_REDIS_URL` is set and the
# in-process substitution when it is not. No settings change is involved.
#
# It is deliberately a script and not a `cmd` in `pixi.toml`. Pixi runs task
# commands through `deno_task_shell`, which implements a subset of POSIX shell
# with no `for`, no `if` and no command substitution, so the readiness loop below
# cannot be expressed there. The pixi task is the entry point; this file is what
# it runs.
#
# Scope is `test-cov` rather than the whole gate, on the same terms as
# `gate-postgres`: `precommit`, `build`, `typecheck` and `lint` never open a
# connection, so running them a second time under a different cache backend
# proves nothing and costs a minute. Everything a backend can change lives in the
# suite -- and running the whole suite against Redis, rather than only the one
# case that needs it, is the same parity argument the PostgreSQL script makes.
set -uo pipefail

CONTAINER="redis-local"
# Deliberately not 6379: that one is often already taken by a local Redis, and
# binding over it is how this script would silently test somebody's development
# cache -- and `cache.clear()` in the suite would then empty it.
PORT="56379"
REDIS_URL="redis://localhost:${PORT}/0"
READY_TIMEOUT_SECONDS=30

if ! docker info >/dev/null 2>&1; then
    echo "docker is not running; this check needs it to start ${CONTAINER}" >&2
    exit 1
fi

docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true

# Stop the container however this script ends, including Ctrl-C. Without it an
# interrupt during the 50-second suite leaves the container running and port
# 56379 bound, and the next run starts by force-removing somebody's container --
# which works, and hides that the first one leaked. `docker stop` is idempotent
# and `--rm` disposes of the container once it stops, so the handler is safe to
# fire on the path where the container was already stopped.
#
# A `trap` is correct here and wrong in `docs/development.md`'s hand-run recipe,
# which is the same reasoning that document already records: pasted into an
# interactive shell a `trap ... EXIT` fires when the *shell* exits rather than
# when the run finishes. This is a script with its own process, so EXIT is the
# end of the run.
cleanup() {
    docker stop "${CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# `--rm` so the container disposes of itself on stop, whatever happens below.
# The exit status is checked rather than assumed: a failed pull -- a rate-limited
# registry, no network, a tag that does not exist -- otherwise surfaces thirty
# seconds later as "never became ready", which points at the readiness loop
# instead of at the pull that actually failed.
if ! docker run -d --rm --name "${CONTAINER}" \
    -p "${PORT}:6379" \
    redis:7 >/dev/null; then
    echo "could not start ${CONTAINER}; see the docker output above (a failed pull is the usual cause)" >&2
    exit 1
fi

# `redis-cli ping` answers PONG only once the server is accepting commands, which
# is the state the suite needs -- the container being *running* is not it. Run
# inside the container for the same reason the PostgreSQL script does: no client
# is assumed on the host.
ready=""
for _ in $(seq "${READY_TIMEOUT_SECONDS}"); do
    if docker exec "${CONTAINER}" redis-cli ping 2>/dev/null | grep -q PONG; then
        ready=1
        break
    fi
    sleep 1
done

# Whether the loop succeeded is recorded rather than assumed. Falling out of it
# after the timeout and running anyway would test against a Redis that never came
# up, producing a connection-refused failure that looks nothing like the one you
# came here to reproduce.
if [ -n "${ready}" ]; then
    CPM_TEST_REDIS_URL="${REDIS_URL}" pixi run test-cov
    status=$?
else
    echo "${CONTAINER} never became ready in ${READY_TIMEOUT_SECONDS}s; see 'docker logs ${CONTAINER}'" >&2
    status=1
fi

cleanup

if [ "${status}" -eq 0 ]; then
    echo "gate-redis: the suite passed against redis:7"
else
    echo "gate-redis: the suite failed against redis:7 (exit ${status})" >&2
fi
exit "${status}"
