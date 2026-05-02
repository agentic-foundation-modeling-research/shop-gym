"""Tests for `shop_arena.probe.bench` (web_probe_patch.md).

Covers:

* In-memory loader returns a validated :class:`Bench`.
* Filesystem loader reads + validates.
* Schema errors propagate as :class:`BenchLoadError`.
* The packaged ``benchmark.example.yaml`` shipped with the module loads cleanly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shop_arena.probe.bench import BenchLoadError, load_bench, load_bench_bytes
from shop_arena.probe.targets import Bench

_PACKAGED_BENCH: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "shop_arena"
    / "probe"
    / "benchmark.example.yaml"
)


def test_load_bench_bytes_validates_minimal() -> None:
    yaml = b"""
version: "0.1"
sandboxes:
  - { name: shop_alpha, base_url: http://localhost:4000, label: sandbox }
reals:
  - { name: real_a, base_url: https://real-a.example.invalid, label: real }
"""
    bench = load_bench_bytes(yaml)
    assert isinstance(bench, Bench)
    assert bench.version == "0.1"
    assert len(bench.sandboxes) == 1
    assert len(bench.reals) == 1


def test_load_bench_bytes_rejects_malformed_yaml() -> None:
    with pytest.raises(BenchLoadError, match="failed to parse"):
        load_bench_bytes(b": : :\n")


def test_load_bench_bytes_rejects_non_mapping() -> None:
    with pytest.raises(BenchLoadError, match="must be a mapping"):
        load_bench_bytes(b"- 1\n- 2\n")


def test_load_bench_bytes_rejects_invalid_label() -> None:
    yaml = b"""
version: "0.1"
sandboxes:
  - { name: shop_a, base_url: http://localhost, label: real }
"""
    with pytest.raises(BenchLoadError, match="failed schema validation"):
        load_bench_bytes(yaml)


def test_load_bench_bytes_rejects_duplicate_name() -> None:
    yaml = b"""
version: "0.1"
sandboxes:
  - { name: dup, base_url: http://localhost, label: sandbox }
reals:
  - { name: dup, base_url: https://real.example, label: real }
"""
    with pytest.raises(BenchLoadError, match="duplicate target name"):
        load_bench_bytes(yaml)


def test_load_bench_reads_filesystem(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bench.yaml"
    yaml_path.write_bytes(
        b'version: "0.1"\n'
        b"sandboxes:\n"
        b"  - { name: a, base_url: http://x, label: sandbox }\n"
        b"reals:\n"
        b"  - { name: r, base_url: https://r.example, label: real }\n"
    )
    bench = load_bench(yaml_path)
    assert bench.sandboxes[0].name == "a"
    assert bench.reals[0].name == "r"


def test_load_bench_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_bench(tmp_path / "nope.yaml")


def test_packaged_benchmark_example_yaml_loads() -> None:
    bench = load_bench(_PACKAGED_BENCH)
    assert bench.version == "0.1"
    # Three sandboxes + three reals, names unique across groups.
    names = [t.name for t in (*bench.sandboxes, *bench.reals)]
    assert len(set(names)) == len(names)
