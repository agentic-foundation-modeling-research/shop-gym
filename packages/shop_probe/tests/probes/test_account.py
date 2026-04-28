"""Tests for ``probes.account.*`` against the localhost SandboxShop (T7.4).

Asserts the v1.1 ``authenticated: true`` probes pass against the fixture's
``/account/login``, ``/account/register``, and ``/account`` routes.
"""

from __future__ import annotations

from pathlib import Path

from _probe_helpers import run_probe

from shop_probe.probes import account


def test_login_form_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        account.login_form_present,
        base_url=sandbox_url,
        probe_id="account.login.form_present",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_signup_form_present_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        account.signup_form_present,
        base_url=sandbox_url,
        probe_id="account.signup.form_present",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}


def test_page_renders_passes(tmp_path: Path, sandbox_url: str) -> None:
    outcome = run_probe(
        account.page_renders,
        base_url=sandbox_url,
        probe_id="account.page.renders",
        evidence_root=tmp_path / "evidence",
    )
    assert outcome.passed is True, outcome.notes
    assert {e.kind for e in outcome.evidence} == {"dom_snapshot", "screenshot"}
