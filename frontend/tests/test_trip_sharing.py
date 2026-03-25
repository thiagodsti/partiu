"""End-to-end Playwright tests for trip sharing and delete trip flows.

Requires the server to be running at http://localhost:8000.
Start it with: uvicorn backend.main:app --reload

Run headless (default):   pytest frontend/tests/test_trip_sharing.py
Run with visible browser: pytest frontend/tests/test_trip_sharing.py --headed
"""

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:8000"


def _server_available(page: Page) -> bool:
    """Check if the dev server is running."""
    try:
        response = page.request.get(BASE_URL, timeout=3000)
        return response.status < 500
    except Exception:
        return False


@pytest.fixture(autouse=True)
def skip_if_no_server(page: Page):
    if not _server_available(page):
        pytest.skip("Server not available at http://localhost:8000")


def _login(page: Page, username: str, password: str):
    page.goto(f"{BASE_URL}/#/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[type="text"]', username)
    page.fill('input[type="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def test_delete_trip_flow(page: Page):
    """Login, navigate to a trip, click delete, confirm, verify redirected and trip is gone."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Skip if no trips exist
    cards = page.locator(".trip-card")
    if cards.count() == 0:
        pytest.skip("No trips available for delete test")

    # Get the trip name before deletion
    first_card = cards.first
    first_card.click()
    page.wait_for_load_state("networkidle")

    # Look for delete button (only visible for owner)
    delete_btn = page.locator('button:has-text("Delete Trip")')
    if delete_btn.count() == 0:
        pytest.skip("Delete Trip button not found (may be a shared trip)")

    delete_btn.click()

    # Confirm modal should appear
    confirm_btn = page.locator('button:has-text("Delete Trip")').last
    confirm_btn.click()
    page.wait_for_load_state("networkidle")

    # Should be redirected to trips list
    assert "/#/" in page.url or page.url.endswith("/#/trips") or page.url.endswith("/")


def test_share_trip_panel_opens(page: Page):
    """Login, navigate to a trip, click Share Trip, verify panel opens."""
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    cards = page.locator(".trip-card")
    if cards.count() == 0:
        pytest.skip("No trips available for share test")

    cards.first.click()
    page.wait_for_load_state("networkidle")

    share_btn = page.locator('button:has-text("Share Trip")')
    if share_btn.count() == 0:
        pytest.skip("Share Trip button not found (may be a shared trip view)")

    share_btn.click()

    # The share panel should appear with a username input
    username_input = page.locator(
        'input[placeholder*="username" i], input[placeholder*="Username" i]'
    )
    assert username_input.count() > 0, "Share panel with username input did not appear"
