"""The component's own declaration: `component.toml`, read (AD-28).

A cross-cutting concern with several independent consumers and no natural owner,
so it lives under `src/config/<concern>/` beside `observability/`, `startup/` and
`authorization/`. The three consumers are readiness (Story 5.3), AD-14's two-way
gate test (Story 5.2) and Epic 9's settings composition, and none of them owns
the file the other two read.

`load_component_declaration` is the whole public surface, plus the four frozen
records it returns. The parsing, the closed key set and every refusal live in
`loader.py`; nothing here imports `django.conf`, because Epic 9 has the settings
module importing this package while it is still being composed.
"""

from __future__ import annotations

from config.component.loader import COMPONENT_DECLARATION_PATH
from config.component.loader import SELECTABLE_FEATURES
from config.component.loader import TOP_LEVEL_KEYS
from config.component.loader import AdminProcessDeclaration
from config.component.loader import ComponentDeclaration
from config.component.loader import DatabaseDeclaration
from config.component.loader import ProcessDeclaration
from config.component.loader import load_component_declaration

__all__ = [
    "COMPONENT_DECLARATION_PATH",
    "SELECTABLE_FEATURES",
    "TOP_LEVEL_KEYS",
    "AdminProcessDeclaration",
    "ComponentDeclaration",
    "DatabaseDeclaration",
    "ProcessDeclaration",
    "load_component_declaration",
]
