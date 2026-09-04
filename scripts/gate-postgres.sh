#!/usr/bin/env bash
#
# Run the gate's test step against a real PostgreSQL, the way CI runs it.
#
# The parity gap this closes is documented at length in `docs/development.md`
# ("The parity gap between local runs and the gate"): local runs use sqlite, the
# gate uses `postgres:17`, and sqlite accepts schemas and queries PostgreSQL
# rejects. A failure that reproduces only in CI is the expected behaviour of that
# trade -- this script is how you reproduce it before pushing rather than after.
#
# It is deliberately a script and not a `cmd` in `pixi.toml`. Pixi runs task
# commands through `deno_task_shell`, which implements a subset of POSIX shell
# with no `for`, no `if` and no command substitution, so the readiness loop below
# cannot be expressed there. The pixi task is the entry point; this file is what
# it runs.
#
# Scope is `test-cov` rather than the whole gate on purpose. `precommit`,
# `build`, `typecheck` and `lint` never open a database connection, so running
# them a second time under a different backend proves nothing and costs a minute.
# Everything a backend can change lives in the suite.
set -uo pipefail

CONTAINER="pg-local"
# Deliberately not 5432: that one is often already taken by a local PostgreSQL,
# and binding over it is how this script would silently test the wrong database.
PORT="55432"
DB_URL="postgres://gateuser:gatepass@localhost:${PORT}/gatedb"
READY_TIMEOUT_SECONDS=30

if ! docker info >/dev/null 2>&1; then
    echo "docker is not running; this check needs it to start ${CONTAINER}" >&2
    exit 1
fi

docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
# `--rm` so the container disposes of itself on stop, whatever happens below.
docker run -d --rm --name "${CONTAINER}" \
    -e POSTGRES_USER=gateuser \
    -e POSTGRES_PASSWORD=gatepass \
    -e POSTGRES_DB=gatedb \
    -p "${PORT}:5432" \
    postgres:17 >/dev/null

# `-h localhost` is load-bearing rather than decoration, for the same reason
# `.github/workflows/ci.yml` spells it out on the service's health check: the
# postgres image's entrypoint runs initdb against a temporary server started with
# `listen_addresses=''`, so a bare `pg_isready` -- which defaults to the local
# unix socket -- reports success during that window while TCP is still closed.
ready=""
for _ in $(seq "${READY_TIMEOUT_SECONDS}"); do
    if docker exec "${CONTAINER}" pg_isready -h localhost -U gateuser -d gatedb >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done

# Whether the loop succeeded is recorded rather than assumed. Falling out of it
# after the timeout and running anyway would test against a database that never
# came up, producing a connection-refused failure that looks nothing like the one
# you came here to reproduce.
if [ -n "${ready}" ]; then
    DATABASE_URL="${DB_URL}" pixi run test-cov
    status=$?
else
    echo "${CONTAINER} never became ready in ${READY_TIMEOUT_SECONDS}s; see 'docker logs ${CONTAINER}'" >&2
    status=1
fi

docker stop "${CONTAINER}" >/dev/null 2>&1 || true

if [ "${status}" -eq 0 ]; then
    echo "gate-postgres: the suite passed against postgres:17"
else
    echo "gate-postgres: the suite failed against postgres:17 (exit ${status})" >&2
fi
exit "${status}"
