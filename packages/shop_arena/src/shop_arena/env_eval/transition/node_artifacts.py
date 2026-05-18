"""Per-node transition artifacts.

The transition graph's ``graph.json`` is compact by design: it stores node ids,
representative URLs, and edges, but not the browser state behind each node.
This module owns the richer debug artifact layout under ``transition/node/``:

* one folder per graph node;
* ``home`` is the folder for the homepage node ``/``;
* URL nodes contain a screenshot plus the page axtree;
* state nodes contain pre/post screenshots plus pre/post axtrees and the
  state-namer metadata that used to live only under ``transition/states/``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "NODE_ARTIFACT_VERSION",
    "NODE_DIRNAME",
    "NODE_INDEX_FILENAME",
    "NodeIndex",
    "NodeIndexEntry",
    "StateNodeArtifact",
    "UrlNodeArtifact",
    "node_folder_name",
    "node_json_path",
    "write_node_index",
    "write_state_node_artifact",
    "write_url_node_artifact",
]

#: Version of the per-node artifact JSON contracts. This is independent from
#: ``metrics.version`` because these files are debug artifacts, not published
#: cohort-comparison schema.
NODE_ARTIFACT_VERSION: Final[str] = "0.1"

#: Directory under ``transition/`` that contains one folder per graph node.
NODE_DIRNAME: Final[str] = "node"

#: Byte-stable listing of the graph-node-to-folder mapping.
NODE_INDEX_FILENAME: Final[str] = "index.json"

_CAPTURE_STATUS = Literal["ok", "error"]
_NODE_KIND = Literal["url", "state"]


class UrlNodeArtifact(BaseModel):
    """Closed JSON schema for a URL-node folder's ``node.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_version: str = Field(default=NODE_ARTIFACT_VERSION, min_length=1)
    canonical_id: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    kind: Literal["url"] = "url"
    representative_url: str = Field(min_length=1)
    capture_status: _CAPTURE_STATUS
    http_status: int | None = None
    error: str | None = None
    screenshot: str | None = None
    axtree_json: str | None = None
    axtree_text: str | None = None


class StateNodeArtifact(BaseModel):
    """Closed JSON schema for a state-node folder's ``node.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_version: str = Field(default=NODE_ARTIFACT_VERSION, min_length=1)
    canonical_id: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    kind: Literal["state"] = "state"
    representative_url: str = Field(min_length=1)
    state_name: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0.0)
    rule_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    expected_state: str = Field(min_length=1)
    state: str = Field(min_length=1)
    raw_response: str
    parse_errors: tuple[str, ...] = ()
    pre_screenshot: str = Field(min_length=1)
    post_screenshot: str = Field(min_length=1)
    pre_axtree_json: str = Field(min_length=1)
    pre_axtree_text: str = Field(min_length=1)
    post_axtree_json: str = Field(min_length=1)
    post_axtree_text: str = Field(min_length=1)


class NodeIndexEntry(BaseModel):
    """One ``transition/node/index.json`` entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    kind: _NODE_KIND
    node_json: str = Field(min_length=1)


class NodeIndex(BaseModel):
    """Closed schema for ``transition/node/index.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_version: str = Field(default=NODE_ARTIFACT_VERSION, min_length=1)
    nodes: tuple[NodeIndexEntry, ...]


def node_folder_name(canonical_id: str) -> str:
    """Return the deterministic folder name for ``canonical_id``.

    The homepage node is deliberately named ``home`` for readability. Other URL
    nodes use their path segments joined by ``__``; template placeholders such
    as ``<*>`` become ``template``. State nodes are prefixed with ``state__``
    and include both the parent page id and the state name.

    Args:
        canonical_id: Graph node canonical id from ``transition/graph.json``.

    Returns:
        Filesystem-safe folder name.
    """
    if canonical_id == "/":
        return "home"
    if canonical_id.startswith("state:"):
        page_id, state_name = _split_state_id(canonical_id)
        return f"state__{_slugify_path(page_id)}__{_slugify_path(state_name)}"
    return _slugify_path(canonical_id)


def node_json_path(node_root: Path, canonical_id: str) -> Path:
    """Return the ``node.json`` path for ``canonical_id`` under ``node_root``."""
    return node_root / node_folder_name(canonical_id) / "node.json"


def write_url_node_artifact(
    *,
    node_root: Path,
    canonical_id: str,
    representative_url: str,
    screenshot_png: bytes | None,
    axtree_json_path: Path | None,
    axtree_text_path: Path | None,
    http_status: int | None,
    error: str | None,
) -> Path:
    """Write ``node.json`` for a URL node and return its path.

    Binary/text payload files are written by the caller because the pipeline
    already owns screenshot encoding and axtree rendering. This helper writes
    the closed JSON metadata and keeps file names consistent.
    """
    folder = node_root / node_folder_name(canonical_id)
    folder.mkdir(parents=True, exist_ok=True)
    screenshot_name: str | None = None
    if screenshot_png is not None:
        screenshot_name = "screenshot.png"
        (folder / screenshot_name).write_bytes(screenshot_png)
    artifact = UrlNodeArtifact(
        canonical_id=canonical_id,
        folder=folder.name,
        representative_url=representative_url,
        capture_status="error" if error else "ok",
        http_status=http_status,
        error=error,
        screenshot=screenshot_name,
        axtree_json=axtree_json_path.name if axtree_json_path is not None else None,
        axtree_text=axtree_text_path.name if axtree_text_path is not None else None,
    )
    path = folder / "node.json"
    _write_model(artifact, path)
    return path


def write_state_node_artifact(
    *,
    node_root: Path,
    canonical_id: str,
    representative_url: str,
    state_name: str,
    state_artifact_path: Path,
    pre_screenshot_path: Path,
    post_screenshot_path: Path,
    pre_axtree_json_path: Path,
    pre_axtree_text_path: Path,
    post_axtree_json_path: Path,
    post_axtree_text_path: Path,
) -> Path:
    """Write a state node's folder under ``transition/node/``.

    The stateful executor uses a temporary per-attempt JSON file internally;
    this function folds that metadata into the node folder's ``node.json`` and
    copies only the pre/post screenshot + axtree files.
    """
    folder = node_root / node_folder_name(canonical_id)
    folder.mkdir(parents=True, exist_ok=True)

    pre_screenshot = _copy(pre_screenshot_path, folder / "pre.png")
    post_screenshot = _copy(post_screenshot_path, folder / "post.png")
    pre_axtree_json = _copy(pre_axtree_json_path, folder / "pre.axtree.json")
    pre_axtree_text = _copy(pre_axtree_text_path, folder / "pre.axtree.txt")
    post_axtree_json = _copy(post_axtree_json_path, folder / "post.axtree.json")
    post_axtree_text = _copy(post_axtree_text_path, folder / "post.axtree.txt")

    raw_payload = cast("object", json.loads(state_artifact_path.read_text(encoding="utf-8")))
    if not isinstance(raw_payload, dict):
        raise TypeError(f"state artifact must be a JSON object: {state_artifact_path}")
    data = cast("dict[str, Any]", raw_payload)
    artifact = StateNodeArtifact(
        canonical_id=canonical_id,
        folder=folder.name,
        representative_url=representative_url,
        state_name=state_name,
        prompt_version=_required_str(data, "prompt_version"),
        model=_required_str(data, "model"),
        temperature=_required_float(data, "temperature"),
        rule_id=_required_str(data, "rule_id"),
        action=_required_str(data, "action"),
        expected_state=_required_str(data, "expected_state"),
        state=_required_str(data, "state"),
        raw_response=_required_str(data, "raw_response"),
        parse_errors=tuple(str(item) for item in _required_list(data, "parse_errors")),
        pre_screenshot=pre_screenshot.name,
        post_screenshot=post_screenshot.name,
        pre_axtree_json=pre_axtree_json.name,
        pre_axtree_text=pre_axtree_text.name,
        post_axtree_json=post_axtree_json.name,
        post_axtree_text=post_axtree_text.name,
    )
    path = folder / "node.json"
    _write_model(artifact, path)
    return path


def write_node_index(
    *,
    node_root: Path,
    nodes: list[tuple[str, _NODE_KIND]],
) -> Path:
    """Write ``transition/node/index.json`` for the graph's node table."""
    node_root.mkdir(parents=True, exist_ok=True)
    entries = tuple(
        NodeIndexEntry(
            canonical_id=canonical_id,
            folder=node_folder_name(canonical_id),
            kind=kind,
            node_json=f"{node_folder_name(canonical_id)}/node.json",
        )
        for canonical_id, kind in nodes
    )
    path = node_root / NODE_INDEX_FILENAME
    _write_model(NodeIndex(nodes=entries), path)
    return path


def _split_state_id(canonical_id: str) -> tuple[str, str]:
    """Return ``(page_id, state_name)`` for a ``state:<page>:<state>`` id."""
    body = canonical_id.removeprefix("state:")
    page_id, separator, state_name = body.rpartition(":")
    if not separator or not page_id or not state_name:
        return canonical_id, "state"
    return page_id, state_name


#: Cap on the length of a single folder slug. macOS / ext4 limit filenames at
#: 255 bytes; pages with long path segments (e.g. blog post titles inlined into
#: the URL) need to be truncated before they hit ``mkdir``.
_MAX_SLUG_LEN: Final[int] = 200


def _slugify_path(value: str) -> str:
    """Return a filesystem-safe slug for one canonical-id component."""
    if value == "/":
        return "home"
    normalized = value.replace("<*>", "template").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return "home"
    slug = "__".join(_slugify_part(part) for part in parts)
    if len(slug) > _MAX_SLUG_LEN:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
        head = slug[: _MAX_SLUG_LEN - len(digest) - 1].rstrip("-_")
        slug = f"{head}-{digest}"
    return slug


def _slugify_part(value: str) -> str:
    """Return a filesystem-safe slug segment."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value)
    slug = re.sub(r"-+", "-", slug).strip("-_")
    return slug or "node"


def _copy(source: Path, target: Path) -> Path:
    """Copy ``source`` to ``target`` and return ``target``."""
    shutil.copyfile(source, target)
    return target


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError(f"state artifact field {key!r} must be a string")
    return value


def _required_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise TypeError(f"state artifact field {key!r} must be a number")
    return float(value)


def _required_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise TypeError(f"state artifact field {key!r} must be a list")
    return cast("list[Any]", value)


def _write_model(model: BaseModel, path: Path) -> None:
    """Write ``model`` as deterministic JSON with a trailing newline."""
    path.write_text(
        json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
