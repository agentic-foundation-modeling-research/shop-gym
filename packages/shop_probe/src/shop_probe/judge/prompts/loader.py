"""Load + validate + content-hash the pairwise judge prompt template.

Implements the loader half of T4.7 (spec §5.5 step 5 + §8.3 + §5.8).
The shipped prompt template ships as two files per the spec §5.1
package layout::

    judge/prompts/v1/system.md
    judge/prompts/v1/pairwise.md

Both files are the canonical artifacts: the ``content_hash`` we
compute is over their raw UTF-8 bytes joined by a fixed framing
header, not over a re-serialized normalisation. That keeps
reproducibility honest — reviewers re-hash the same files we shipped.

The framing header binds the version string and the file roles into
the digest so that, for example, swapping ``system.md`` and
``pairwise.md`` would produce a different hash even if the byte
content were identical.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from shop_probe.judge.prompts.schema import JudgePromptSet

_DEFAULT_ROOT: Path = Path(__file__).resolve().parent
"""Directory shipped alongside the source — contains ``v1/`` etc."""


class JudgePromptLoadError(ValueError):
    """Raised when the prompt template files are missing or invalid.

    Wraps the underlying filesystem / pydantic error so callers can
    ``except JudgePromptLoadError`` without depending on either
    machinery directly.
    """


def compute_content_hash(version: str, system: bytes, pairwise: bytes) -> str:
    """Compute the canonical content hash for a pair of prompt files.

    The hash binds three inputs in fixed order:

    * the literal version string (so a version bump always re-hashes),
    * the ``system.md`` byte content, and
    * the ``pairwise.md`` byte content.

    Each input is preceded by a fixed framing header that names its
    role; this prevents trivial collisions if the two files ever held
    identical bytes.

    Args:
        version: Prompt template version string, e.g. ``"v1"``.
        system: Raw UTF-8 bytes of ``system.md``.
        pairwise: Raw UTF-8 bytes of ``pairwise.md``.

    Returns:
        Lowercase hex SHA-256 digest (64 chars).
    """
    digest = hashlib.sha256()
    digest.update(b"shop_probe.judge.prompts/v=")
    digest.update(version.encode("utf-8"))
    digest.update(b"\n--- system.md ---\n")
    digest.update(system)
    digest.update(b"\n--- pairwise.md ---\n")
    digest.update(pairwise)
    return digest.hexdigest()


def load_judge_prompts(
    version: str = "v1",
    *,
    root: Path | None = None,
) -> JudgePromptSet:
    """Load and validate the pairwise judge prompt template for a version.

    Args:
        version: Subdirectory name under ``root`` to load (default
            ``"v1"``). Frozen per spec §5.8 — bump on any change.
        root: Directory containing version subdirectories. Defaults to
            the package-shipped ``judge/prompts/`` directory; tests
            override this to load fixtures.

    Returns:
        A validated :class:`JudgePromptSet` with ``content_hash``
        populated.

    Raises:
        JudgePromptLoadError: A required file is missing or fails
            schema validation (e.g. a placeholder is missing from the
            pairwise template).
    """
    base = root if root is not None else _DEFAULT_ROOT
    version_dir = base / version
    if not version_dir.is_dir():
        msg = f"judge prompt directory not found: {version_dir}"
        raise JudgePromptLoadError(msg)
    system_path = version_dir / "system.md"
    pairwise_path = version_dir / "pairwise.md"
    if not system_path.is_file():
        msg = f"missing prompt file: {system_path}"
        raise JudgePromptLoadError(msg)
    if not pairwise_path.is_file():
        msg = f"missing prompt file: {pairwise_path}"
        raise JudgePromptLoadError(msg)

    system_bytes = system_path.read_bytes()
    pairwise_bytes = pairwise_path.read_bytes()
    content_hash = compute_content_hash(version, system_bytes, pairwise_bytes)

    try:
        return JudgePromptSet(
            version=version,
            content_hash=content_hash,
            system_template=system_bytes.decode("utf-8"),
            pairwise_template=pairwise_bytes.decode("utf-8"),
        )
    except ValidationError as err:
        msg = f"judge prompt {version!r} failed schema validation: {err}"
        raise JudgePromptLoadError(msg) from err
