"""Axis A — ``account`` probes (T7.4 — spec §5.9, §7 M7).

Three v1.1 ``authenticated: true`` probes covering the auth surface that
v1 deliberately leaves out (spec §5.9):

* :func:`login_form_present` — ``/account/login`` exposes an email +
  password form (rubric ``account.login.form_present``).
* :func:`signup_form_present` — ``/account/register`` exposes a signup
  form with at least an email + password input (``account.signup.form_present``).
* :func:`page_renders` — ``/account`` either renders an authenticated
  account page or redirects to the login surface (``account.page.renders``).

These probes never attempt to log in; they exercise the public auth
surfaces only. They are gated behind ``shop-probe run --include-auth``
because most v1 cohort runs intentionally skip the auth slice.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from shop_probe.probes._runner import ProbeContext, ProbeOutcome


def _login_url(base_url: str) -> str:
    """Resolve ``base_url`` + ``/account/login``, robust to trailing-slash drift."""
    return urljoin(base_url.rstrip("/") + "/", "account/login")


def _register_url(base_url: str) -> str:
    """Resolve ``base_url`` + ``/account/register``, robust to trailing-slash drift."""
    return urljoin(base_url.rstrip("/") + "/", "account/register")


def _account_url(base_url: str) -> str:
    """Resolve ``base_url`` + ``/account``, robust to trailing-slash drift."""
    return urljoin(base_url.rstrip("/") + "/", "account")


async def login_form_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """``/account/login`` exposes an email + password form."""
    await page.goto(_login_url(ctx.base_url), wait_until="domcontentloaded")
    email = page.locator(
        'input[type="email"], input[name="customer[email]"], input[name*="email" i]'
    ).first
    password = page.locator(
        'input[type="password"], input[name="customer[password]"], input[name*="password" i]'
    ).first
    has_email = await email.count() > 0
    has_password = await password.count() > 0
    snap = await ctx.snapshot("login-form")
    shot = await ctx.screenshot("login-form")
    passed = has_email and has_password
    note = (
        None if passed else f"login form missing fields: email={has_email}, password={has_password}"
    )
    return ProbeOutcome(passed=passed, evidence=(shot, snap), notes=note)


async def signup_form_present(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """``/account/register`` exposes a signup form with email + password inputs."""
    await page.goto(_register_url(ctx.base_url), wait_until="domcontentloaded")
    email = page.locator(
        'input[type="email"], input[name="customer[email]"], input[name*="email" i]'
    ).first
    password = page.locator(
        'input[type="password"], input[name="customer[password]"], input[name*="password" i]'
    ).first
    has_email = await email.count() > 0
    has_password = await password.count() > 0
    snap = await ctx.snapshot("signup-form")
    shot = await ctx.screenshot("signup-form")
    passed = has_email and has_password
    note = (
        None
        if passed
        else f"signup form missing fields: email={has_email}, password={has_password}"
    )
    return ProbeOutcome(passed=passed, evidence=(shot, snap), notes=note)


async def page_renders(page: Page, ctx: ProbeContext) -> ProbeOutcome:
    """``/account`` renders an account page or redirects to the login surface.

    Storefronts typically either:

    * serve an authenticated account dashboard at ``/account``, or
    * 302 unauthenticated visitors to ``/account/login``.

    Both are valid auth surfaces; the probe accepts either as long as the
    final response is a 2xx HTML document and the URL is one of those two
    routes.
    """
    response = await page.goto(_account_url(ctx.base_url), wait_until="domcontentloaded")
    snap = await ctx.snapshot("account-page")
    shot = await ctx.screenshot("account-page")
    if response is None:
        return ProbeOutcome(passed=False, evidence=(shot, snap), notes="no response from /account")
    status = response.status
    final_path = urlparse(page.url).path.rstrip("/") or "/"
    body_text = (await page.locator("body").text_content()) or ""
    has_body = len(body_text.strip()) > 0
    on_account_or_login = final_path in {"/account", "/account/login"}
    passed = 200 <= status < 400 and has_body and on_account_or_login  # noqa: PLR2004 — HTTP success range
    note = (
        None
        if passed
        else (f"/account final_path={final_path!r}, status={status}, body_chars={len(body_text)}")
    )
    return ProbeOutcome(passed=passed, evidence=(shot, snap), notes=note)
