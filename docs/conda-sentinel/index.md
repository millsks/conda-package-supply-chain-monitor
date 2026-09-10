# Conda-Sentinel

Evidence-based health, vulnerability and currency monitoring for a Conda/Python
package inventory.

!!! note "This section is being written"

    `CPM-DOCS-S03` and `CPM-DOCS-S04` fill in what the product does and how to run
    it. What is here today is the material that already existed, moved out of the
    platform's documentation where it had been mixed in.

## Where to start

| If you are… | Read |
|---|---|
| working on the product's screens, API or reports | [Developing Conda-Sentinel](development.md) |
| deploying it, or wondering why it sees nothing | [Operating Conda-Sentinel](operations.md) |

## The one thing to know first

**Every collector ships inert.** None of them names an upstream, a channel, a
catalogue or an advisory source, and none invents one — so a fresh deployment observes
nothing until somebody declares where to look.

That is deliberate rather than unfinished. This product's central rule is that nothing
is presented as clean without evidence, and a collector that guessed at a source would
be manufacturing the evidence the rule exists to require. The consequence is that a
new deployment's screens are full of `unknown`, and `unknown` is a finding — it is the
product saying nobody established anything here yet.

[Operating Conda-Sentinel](operations.md) says what each collector needs.

## The platform underneath

The service platform — settings, authentication, logging, the process model, the
harness — is [the accelerator's](../accelerator/index.md) and is documented
separately.
