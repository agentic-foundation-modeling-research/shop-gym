"""Developer-facing inspection utilities for harness artefacts.

Modules under this package are exposed as project console scripts via
``[project.scripts]`` in ``packages/harness/pyproject.toml``. They are
deliberately separate from the runtime/loop code so they can be
imported from tests and invoked from anywhere in the workspace.
"""

from __future__ import annotations
