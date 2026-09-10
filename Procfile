# The local stack, for honcho (`pixi run local-stack`).
#
# **Every line delegates to a pixi task rather than spelling a command.** That is the
# rule this file exists under: `pixi.toml` is where a process's command is declared,
# `component.toml` reconciles the deployed ones against it, and
# `tests/unit/test_process_model.py` reads both. A command written out here would be a
# second spelling of one of those, and the two would disagree the first time somebody
# changed a queue name or a scheduler.
#
# **`-e dev` on every line, and it is load-bearing.** `COMPONENT_RUNTIME=local` comes
# from `[feature.dev.activation.env]` and from nowhere else -- `tests/unit/
# test_locality_declaration.py` fails the gate on any task that declares it. A bare
# `pixi run worker` therefore resolves in `default`, reads *deployed* settings, finds
# no broker URL and falls back to Celery's built-in `amqp://guest@localhost:5672`.
#
# That failure is quiet: the worker starts, prints a banner, drains the right queue
# names and consumes nothing, because it is connected to a RabbitMQ that is not there.
# It was exactly what happened the first time this file was written.
#
# `web` is the **deployed** command -- gunicorn with the draining uvicorn worker, the
# same line `Dockerfile` runs. Deliberately, at the product owner's direction: this
# stack exists to run the product the way it actually runs, and `runserver` hides the
# things worth seeing here. It is a real ASGI server, it exercises
# `config.workers.DrainingUvicornWorker`, and its shutdown is the shutdown
# `CPM-AD-22`'s grace period is about.
#
# Two costs, both accepted rather than overlooked. There is **no autoreload** --
# `--reload` is not on the deployed command and does not belong there, so an edit
# needs a restart. And gunicorn is **Unix-only**, so this line does not run on
# Windows; `pixi run -e dev runserver` remains the cross-platform way to serve one
# process, and the rest of the stack is unaffected.
web: pixi run -e dev web
worker: pixi run -e dev worker
beat: pixi run -e dev beat
flower: pixi run -e dev flower
