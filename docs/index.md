# Conda-Sentinel

Evidence-based health, vulnerability and currency monitoring for a Conda/Python
package inventory.

It answers one question per package, and it is careful about the difference between
answering it and being unable to: *is this package current, is it exposed, is its
licence acceptable, is it ready for Python 3.14 — and on whose evidence?*

## The idea worth understanding first

Most monitoring tools have two answers: a problem, or silence. Silence is the
dangerous one, because it looks like health and is usually absence — nobody checked,
the source was down, the package was never identified.

This product has **five** answers, and it says which one it means:

<span class="cs-state ok">current</span>
<span class="cs-state crit">advisories_matched</span>
<span class="cs-state warn">manual_review</span>
<span class="cs-state unknown">unknown</span>
<span class="cs-state unknown">not_found</span>

`unknown` is a **finding**. It is the product saying *nobody established anything
here*, and it is written into the row rather than left as a gap — so it survives into
the API, into a CSV somebody exports, and into a board pack. A package that has never
been looked at and a package that was looked at and is fine do not render the same.

Everything else follows from that. Evidence is append-only, verdicts are recomputed
rather than edited, and a claim nobody has evidence for is not made.

## Where to go

<div class="grid cards" markdown>

- **Using and running it** — what the product concludes, from what, and how to
  operate it.

    [Conda-Sentinel](conda-sentinel/index.md)

- **The platform underneath** — the Django service accelerator this component was
  built from: settings, authentication, logging, deployment.

    [The platform](accelerator/index.md)

</div>

| If you are… | Start at |
|---|---|
| new to the product | [What Conda-Sentinel does](conda-sentinel/index.md) |
| deploying it, or wondering why it sees nothing | [Operating Conda-Sentinel](conda-sentinel/operations.md) |
| working on its screens, API or reports | [Developing Conda-Sentinel](conda-sentinel/development.md) |
| setting up a development environment | [Developing on the platform](accelerator/development.md) |
| wiring up an identity provider | [Authentication](accelerator/authentication.md) |

## Two things that surprise people

**Every collector ships inert.** None names an upstream, a channel, a catalogue or an
advisory source, and none invents one — so a fresh deployment observes nothing until
somebody declares where to look. That is the rule above doing its job: a collector
that guessed at a source would be manufacturing the evidence the product exists to
require. See [Operating Conda-Sentinel](conda-sentinel/operations.md).

**Nothing is derived until a policy run says so.** Collectors write evidence; policy
passes read it and write verdicts; the screens read the verdicts. So a freshly seeded
database shows `unknown` everywhere until a run happens — which is correct, and is the
first thing to check when a screen looks empty.

## This repository is two things

A product, and the accelerator it was generated from. They are documented separately
because a reader asking how package health is decided should not be handed a chapter
on 15-factor process models, and a reader deploying a component should not have to
read about advisory sources.

```text
src/
  config/            # the platform's wiring: settings, urls, celery
  django_service/    # the platform application: users, templates, static
  django_apps/       # the second import root
    conda_sentinel/  # this product: core, identity, collectors, policies,
                     # workflow, surface — one app per domain
```
