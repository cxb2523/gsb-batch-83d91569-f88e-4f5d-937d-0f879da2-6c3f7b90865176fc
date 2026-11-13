"""Unit tests for tab lifecycle and per-tab history isolation.

These exercise BrowserManager with in-memory fake pages instead of a real
Camoufox binary, so they need no browser install and no network. Navigation
targets are data: URLs and the local fixture file.
"""

import os

import pytest

from camoufox_cli.browser import BrowserManager
from camoufox_cli.commands import execute

FIXTURE_URL = "file://" + os.path.join(os.path.dirname(__file__), "fixture.html")

URL_A1 = "data:text/html,<h1>A1</h1>"
URL_A2 = "data:text/html,<h1>A2</h1>"
URL_A3 = "data:text/html,<h1>A3</h1>"
URL_B1 = "data:text/html,<h1>B1</h1>"
URL_B2 = "data:text/html,<h1>B2</h1>"


class FakePage:
    """Minimal stand-in for a Playwright Page used by BrowserManager."""

    def __init__(self, ctx: "FakeContext"):
        self._ctx = ctx
        self._url = "about:blank"
        self._closed = False

    @property
    def url(self) -> str:
        return self._url

    def is_closed(self) -> bool:
        return self._closed

    def goto(self, url: str, wait_until: str | None = None):
        self._url = url

    def close(self):
        self._closed = True
        self._ctx.remove(self)

    def bring_to_front(self):
        pass


class FakeContext:
    """Minimal stand-in for a Playwright BrowserContext."""

    def __init__(self):
        self._pages: list[FakePage] = []

    def new_page(self) -> FakePage:
        page = FakePage(self)
        self._pages.append(page)
        return page

    @property
    def pages(self) -> list[FakePage]:
        return list(self._pages)

    def remove(self, page: FakePage):
        self._pages = [p for p in self._pages if p is not page]


@pytest.fixture
def manager() -> BrowserManager:
    mgr = BrowserManager()
    mgr._context = FakeContext()
    return mgr


def _open(manager: BrowserManager, tab: str, url: str) -> FakePage:
    """Mimic the open command: (re)create the tab's page and record history."""
    page = manager.get_page(tab, create=True)
    page.goto(url)
    manager.state(tab).push_history(page.url)
    return page


class TestCloseIsolation:
    def test_closing_one_tab_preserves_other_tabs_page_refs_and_history(self, manager):
        page_a = _open(manager, "a", URL_A1)
        _open(manager, "a", URL_A2)
        page_b = _open(manager, "b", URL_B1)
        _open(manager, "b", URL_B2)

        manager.release_tab("a")

        assert page_a.is_closed()
        # The surviving tab keeps its exact page pointer and history index.
        st_b = manager.state("b")
        assert st_b.page is page_b
        assert not page_b.is_closed()
        assert st_b.history == [URL_B1, URL_B2]
        assert st_b.history_index == 1
        # back still navigates the surviving tab's own history.
        assert manager.go_back("b") == URL_B1
        assert page_b.url == URL_B1

    def test_close_on_a_tab_that_never_opened_a_page_is_a_noop(self, manager):
        page_b = _open(manager, "b", URL_B1)

        # Releasing an unknown tab must succeed and leave the live tab alone.
        manager.release_tab("ghost")
        manager.release_tab("ghost")  # idempotent
        assert manager._context is not None
        assert manager.state("b").page is page_b
        assert manager.state("b").history == [URL_B1]

    def test_close_via_command_on_pageless_tab_reports_success(self, manager):
        _open(manager, "b", URL_B1)
        resp = execute(manager, {"id": "r1", "action": "close", "tab": "ghost"})
        assert resp["success"] is True
        # Other tabs are unaffected.
        assert manager.state("b").history == [URL_B1]

    def test_closing_the_last_live_tab_shuts_the_browser_down(self, manager):
        page = _open(manager, "solo", FIXTURE_URL)

        manager.release_tab("solo")

        assert page.is_closed()
        assert manager._context is None
        assert manager._tabs == {}


class TestReopenAfterClose:
    """Reusing a closed tab's name while another tab keeps the browser alive."""

    def test_reopened_same_named_tab_starts_with_blank_history(self, manager):
        # A spectator tab keeps the shared context alive after worker closes.
        _open(manager, "spectator", FIXTURE_URL)
        page = _open(manager, "worker", URL_A1)
        _open(manager, "worker", URL_A2)
        # Sanity: before closing, back works through the recorded history.
        assert manager.go_back("worker") == URL_A1

        manager.release_tab("worker")
        assert page.is_closed()
        assert "worker" not in manager._tabs

        new_page = _open(manager, "worker", URL_B1)
        assert new_page is not page

        st = manager.state("worker")
        assert st.history == [URL_B1]
        assert st.history_index == 0
        # The new lifecycle has no previous or next page.
        assert manager.go_back("worker") is None
        assert manager.go_forward("worker") is None

    def test_reopened_tab_back_and_forward_report_no_page_errors(self, manager):
        _open(manager, "spectator", FIXTURE_URL)
        _open(manager, "worker", URL_A1)
        _open(manager, "worker", URL_A2)
        manager.release_tab("worker")
        _open(manager, "worker", URL_B1)

        back = execute(manager, {"id": "r1", "action": "back", "tab": "worker"})
        assert back["success"] is False
        assert "no previous page" in back["error"].lower()

        forward = execute(manager, {"id": "r2", "action": "forward", "tab": "worker"})
        assert forward["success"] is False
        assert "no next page" in forward["error"].lower()

    def test_reopened_tab_gets_fresh_ref_registry(self, manager):
        _open(manager, "spectator", FIXTURE_URL)
        _open(manager, "t", URL_A1)
        manager.state("t").refs.build_from_snapshot('- button "Go"')
        assert len(manager.state("t").refs) == 1

        manager.release_tab("t")
        _open(manager, "t", URL_B1)

        assert len(manager.state("t").refs) == 0

    def test_navigation_then_close_reopen_does_not_resurrect_old_urls(self, manager):
        _open(manager, "spectator", FIXTURE_URL)
        _open(manager, "w", URL_A1)
        _open(manager, "w", URL_A2)
        _open(manager, "w", URL_A3)
        manager.release_tab("w")

        _open(manager, "w", URL_B1)
        # A new navigation truncates against the fresh history — no A* URLs
        # may survive anywhere in the stack.
        _open(manager, "w", URL_B2)
        history = manager.state("w").history
        assert history == [URL_B1, URL_B2]
        assert all(not url.startswith("data:text/html,<h1>A") for url in history)


class TestSwitchIsolation:
    def test_switch_resets_adopting_tab_to_single_entry_history(self, manager):
        page_b = _open(manager, "beta", URL_B1)
        _open(manager, "beta", URL_B2)
        page_a = _open(manager, "alpha", URL_A1)
        _open(manager, "alpha", URL_A2)
        # Give alpha a stale ref; switch must invalidate it.
        manager.state("alpha").refs.build_from_snapshot('- button "Old"')

        index = manager.get_context().pages.index(page_b)
        manager.switch_to_tab("alpha", index)

        st_a = manager.state("alpha")
        assert st_a.page is page_b
        assert st_a.history == [URL_B2]
        assert st_a.history_index == 0
        assert len(st_a.refs) == 0
        assert manager.go_back("alpha") is None
        assert manager.go_forward("alpha") is None
        # page_a is still open in the context, just no longer alpha's pointer.
        assert not page_a.is_closed()

    def test_switch_does_not_pollute_the_other_tab(self, manager):
        page_b = _open(manager, "beta", URL_B1)
        _open(manager, "beta", URL_B2)
        _open(manager, "alpha", URL_A1)
        _open(manager, "alpha", URL_A2)

        index = manager.get_context().pages.index(page_b)
        manager.switch_to_tab("alpha", index)

        # The original owner's state — page, refs, history index — is untouched.
        st_b = manager.state("beta")
        assert st_b.page is page_b
        assert st_b.history == [URL_B1, URL_B2]
        assert st_b.history_index == 1
        # beta can still walk its own history after alpha switched onto its page.
        assert manager.go_back("beta") == URL_B1
        assert page_b.url == URL_B1
        assert manager.state("alpha").history == [URL_B2]

    def test_navigation_after_switch_cannot_contaminate_the_other_tab(self, manager):
        page_b = _open(manager, "beta", URL_B1)
        _open(manager, "beta", URL_B2)
        _open(manager, "alpha", URL_A1)

        index = manager.get_context().pages.index(page_b)
        manager.switch_to_tab("alpha", index)
        _open(manager, "alpha", URL_A3)

        assert manager.state("alpha").history == [URL_B2, URL_A3]
        # beta's history stays exactly as it was before the switch.
        assert manager.state("beta").history == [URL_B1, URL_B2]
        assert manager.state("beta").history_index == 1

    def test_switch_back_and_forward_report_no_page_until_new_navigation(self, manager):
        page_b = _open(manager, "beta", URL_B1)
        _open(manager, "alpha", URL_A1)

        index = manager.get_context().pages.index(page_b)
        manager.switch_to_tab("alpha", index)

        back = execute(manager, {"id": "r1", "action": "back", "tab": "alpha"})
        assert back["success"] is False
        assert "no previous page" in back["error"].lower()
        forward = execute(manager, {"id": "r2", "action": "forward", "tab": "alpha"})
        assert forward["success"] is False
        assert "no next page" in forward["error"].lower()

        # One fresh navigation gives exactly one back step, still no forward.
        _open(manager, "alpha", URL_A2)
        assert manager.go_back("alpha") == URL_B1
        assert manager.go_forward("alpha") == URL_A2
