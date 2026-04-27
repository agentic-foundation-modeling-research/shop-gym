"""``copy_seed_manual`` — Phase 1 single-seed shortcut (spec §5.2).

When ``len(seeds) == 1`` the manual-merge sub-DAG collapses to a single
deterministic copy: the seed's ``capabilities.json``, ``manual.md``, and
``stats.json`` are copied verbatim into ``<out_dir>/manual/``. No LLM
calls, no merge logic — this step is the byte-for-byte pass-through
documented in spec §5.2 ("With a single seed, the manual files are
copied verbatim into ``<out_dir>/manual/`` and Phase 1 is a no-op.").

Step contract (spec §5.7.1):

* ``id``: ``copy_seed_manual``.
* ``phase``: ``manual_merge``.
* ``inputs``: one :class:`~shop_gen.steps.base.FileInput` per seed
  artifact file (``capabilities.json``, ``manual.md``, ``stats.json``).
* ``outputs``: ``manual/capabilities.json``, ``manual/manual.md``,
  ``manual/stats.json``.
* ``depends_on``: empty (the only inputs are seed files on disk).

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from shop_gen.steps.base import FileInput, InputRef, StepContext

_PHASE: Final[str] = "manual_merge"
_STEP_ID: Final[str] = "copy_seed_manual"
_STEP_VERSION: Final[int] = 1

# Seed artifact files that map 1:1 onto the published ``manual/``
# layout. Order is fixed so :class:`CopySeedManualStep.inputs` and
# :class:`CopySeedManualStep.outputs` are deterministic across runs
# (the runner hashes inputs in declaration order; spec §5.7).
_ARTIFACT_FILES: Final[tuple[str, ...]] = (
    "capabilities.json",
    "manual.md",
    "stats.json",
)

_MANUAL_DIR: Final[Path] = Path("manual")
_SEED_ARTIFACT_DIR: Final[str] = "artifact"


class CopySeedManualStep:
    """Phase 1 single-seed ``copy_seed_manual`` step (spec §5.2).

    Copies the seed's ``capabilities.json``, ``manual.md``, and
    ``stats.json`` verbatim into the run's ``manual/`` directory. The
    multi-seed merge sub-DAG (``merge_capabilities`` / ``merge_manual_prose``
    / ``compute_merge_stats`` / ``write_merge_manifest``) is replaced by
    this one step when ``len(seeds) == 1``.

    Attributes:
        id: Step id (``copy_seed_manual``).
        phase: ``manual_merge``.
        inputs: One :class:`FileInput` per seed artifact file.
        outputs: ``manual/<file>`` for each artifact file.
        depends_on: Empty (the step's only inputs are seed files).
        version: Bumped when the copy behaviour changes (spec §5.7.1).
    """

    def __init__(self, seed_dir: Path | None) -> None:
        """Build the step from the single seed directory.

        Args:
            seed_dir: Seed directory whose ``artifact/`` subdirectory
                contains ``capabilities.json``, ``manual.md``, and
                ``stats.json``. ``None`` registers a placeholder
                instance whose id / phase still surface in
                :func:`shop_gen.pipeline.list_steps` (the listing
                branch is config-free).
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        if seed_dir is None:
            self.inputs: list[InputRef] = []
        else:
            artifact = seed_dir / _SEED_ARTIFACT_DIR
            self.inputs = [FileInput(path=artifact / name) for name in _ARTIFACT_FILES]
        self.outputs: list[Path] = [_MANUAL_DIR / name for name in _ARTIFACT_FILES]
        self.depends_on: list[str] = []
        self.version: int = _STEP_VERSION
        self._seed_dir: Path | None = seed_dir

    def run(self, ctx: StepContext) -> None:
        """Copy the seed artifact files verbatim into ``manual/``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                copy is deterministic and never invokes the LLM.

        Raises:
            ValueError: The step was constructed with ``seed_dir=None``
                (the listing-branch placeholder has no source files).
            FileNotFoundError: The seed's ``artifact/`` directory is
                missing one of the required files.
        """
        if self._seed_dir is None:
            raise ValueError(
                "CopySeedManualStep was constructed without a seed_dir; "
                "this instance is a listing placeholder and cannot run",
            )
        artifact = self._seed_dir / _SEED_ARTIFACT_DIR
        manual_dir = ctx.out_dir / _MANUAL_DIR
        manual_dir.mkdir(parents=True, exist_ok=True)
        for name in _ARTIFACT_FILES:
            source = artifact / name
            if not source.exists():
                raise FileNotFoundError(f"seed artifact file not found: {source}")
            (manual_dir / name).write_bytes(source.read_bytes())


__all__ = [
    "CopySeedManualStep",
]
