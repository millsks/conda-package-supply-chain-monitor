"""Spikes: fitness probes run against a dedicated pixi environment.

A spike is not part of the suite `pixi run ci` runs. It answers one question
about one candidate dependency, records the answer where the dependency is
declared, and is deleted when the question stops mattering. Modules here are
named `spike_*.py` rather than `test_*.py`, which is what keeps them out of
`pytest tests/`: `[tool.pytest.ini_options] python_files` matches `test_*.py`
and `tests.py` only, and pytest collects a non-matching file solely when it is
named on the command line -- which `pixi run spike-storage` does and the gate
never does.

Disposition (spine, Consistency Conventions): `machinery`. A spike is
accelerator work and never travels to a component. Epic 7 Story 7.1's
disposition author should read this directory as machinery in its entirety.
"""
