"""Browser-driven UI E2E for the BFF (HTMX chat), via Playwright.

Unlike test_bff.py (HTTP-level), this drives a real Chromium: it types into
the chat box, clicks Send, and asserts the rendered DOM — exercising the HTMX
swap, the session-id bootstrap, and the "Thinking Process" tool panel exactly
as a user sees them.

Requires a running stack whose default `agent` is backed by a real model
(it must actually call tools), plus Chromium. Enable with:

    DAK_SMOKE_REAL_LLM=1 uv run pytest test_bff_ui.py

Screenshots are written to tests/integration/artifacts/ for visual inspection.
"""
import os
import pathlib

import pytest

from conftest import BFF_URL

pytestmark = pytest.mark.skipif(
    os.getenv("DAK_SMOKE_REAL_LLM") != "1",
    reason="UI E2E: start the local-llm stack and set DAK_SMOKE_REAL_LLM=1",
)

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

ARTIFACTS = pathlib.Path(__file__).parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# Agent turns on a small local model can take a while; keep DOM waits generous.
ANSWER = ".chat-message.assistant .message-content"
THOUGHTS = ".chat-message.assistant .thoughts"


@pytest.fixture
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.set_default_timeout(90_000)
        yield pg
        browser.close()


def _send(page, text):
    """Type a prompt, submit, and return the latest assistant message locator."""
    before = page.locator(ANSWER).count()
    page.fill('input[name="prompt"]', text)
    page.click('button[type="submit"]')
    # Wait until a NEW assistant message has rendered with non-empty content.
    page.wait_for_function(
        "([sel, n]) => { const e = document.querySelectorAll(sel);"
        " return e.length > n && e[e.length-1].textContent.trim().length > 0; }",
        arg=[ANSWER, before],
    )
    return page.locator(ANSWER).last


def test_ui_basic_chat(page):
    page.goto(BFF_URL)
    assert page.locator('input[name="prompt"]').is_visible()

    answer = _send(page, "Reply with a short one-sentence greeting.")
    text = answer.inner_text().strip()
    page.screenshot(path=str(ARTIFACTS / "ui_basic_chat.png"), full_page=True)

    assert text, "assistant message rendered empty"
    assert "[ENFORCER_BLOCKED]" not in text


def test_ui_skill_discovery_shows_tool_steps(page):
    """Sending a tool-requiring prompt should render the 'Thinking Process' panel
    with a tool Action (proves real tool-calling reached the browser)."""
    page.goto(BFF_URL)

    _send(
        page,
        "Use the list_skills tool to show your available skills. "
        "Do not answer from memory.",
    )
    # The tool call is rendered inside a collapsed <details class="thoughts">
    # panel; expand it (as a user would) so the Action steps become visible.
    panel = page.locator(THOUGHTS).last
    panel.wait_for(timeout=90_000)
    panel.locator("summary").click()
    page.screenshot(path=str(ARTIFACTS / "ui_skill_discovery.png"), full_page=True)
    thoughts = panel.inner_text()

    assert "list_skills" in thoughts, f"no list_skills tool step rendered: {thoughts}"
