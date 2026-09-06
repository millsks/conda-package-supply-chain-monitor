"""The policy passes: `CPM-AD-8`'s versioned rules over the evidence log.

A pass reads evidence at a run's stated cut-off, writes its own derived table and
contributes rollup columns by returning them. The machinery -- `PolicyPass`, the
registry, the orchestration and the one rollup writer -- is `core`'s;
what lives here is the domain rules themselves, one module per policy, because
`core` holds the machinery and must not grow a domain policy and `collectors`
must not compute a derived status (`CPM-AD-8`).
"""
