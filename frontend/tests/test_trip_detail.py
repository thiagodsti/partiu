"""End-to-end Playwright tests for TripIt Mine.

Requires the server to be running at http://localhost:8000.
Start it with: cd backend && uvicorn main:app --reload

Run headless (default):   pytest tests/e2e/
Run with visible browser: pytest tests/e2e/ --headed
"""
import pytest
from playwright.sync_api import Page, expect

BASE_URL = 'http://localhost:8000'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def go_to_first_trip(page: Page) -> bool:
    """Navigate to the first trip detail page. Returns False if none exist."""
    page.goto(f'{BASE_URL}/#/trips')
    page.wait_for_load_state('networkidle')
    card = page.locator('.trip-card').first
    if card.count() == 0:
        return False
    card.click()
    page.wait_for_load_state('networkidle')
    return True


# ---------------------------------------------------------------------------
# Basic navigation
# ---------------------------------------------------------------------------

def test_homepage_loads_trips_view(page: Page):
    """Navigating to / should render the trips list view (hash routing stays at /)."""
    page.goto(BASE_URL)
    page.wait_for_load_state('networkidle')
    # The SPA uses hash-based routing; the document URL stays at /
    # but the app should render either trip cards or the empty state
    cards = page.locator('.trip-card')
    empty = page.locator('.empty-state')
    assert cards.count() > 0 or empty.count() > 0, 'Trips view did not render'


def test_trips_list_renders(page: Page):
    """The trips list should show trip cards or an empty state."""
    page.goto(f'{BASE_URL}/#/trips')
    page.wait_for_load_state('networkidle')
    cards = page.locator('.trip-card')
    empty = page.locator('.empty-state')
    assert cards.count() > 0 or empty.count() > 0, 'Page rendered neither cards nor empty state'


# ---------------------------------------------------------------------------
# Trip detail — structure
# ---------------------------------------------------------------------------

def test_trip_detail_has_outbound_divider(page: Page):
    """Trip detail must show the Outbound section divider."""
    if not go_to_first_trip(page):
        pytest.skip('No trips in database')
    outbound = page.locator('.section-divider-label', has_text='Outbound')
    expect(outbound.first).to_be_visible()


def test_trip_detail_shows_flight_rows(page: Page):
    """Trip detail must show at least one flight row."""
    if not go_to_first_trip(page):
        pytest.skip('No trips in database')
    expect(page.locator('.flight-row').first).to_be_visible()


def test_flight_row_shows_route_arrow(page: Page):
    """Each flight row must render the departure → arrival route."""
    if not go_to_first_trip(page):
        pytest.skip('No trips in database')
    route = page.locator('.flight-route').first
    expect(route).to_be_visible()
    expect(route.locator('.flight-route-arrow')).to_be_visible()


def test_outbound_divider_shows_flying_time(page: Page):
    """The Outbound divider should contain a 'flying' time annotation."""
    if not go_to_first_trip(page):
        pytest.skip('No trips in database')
    outbound = page.locator('.section-divider-label', has_text='Outbound').first
    expect(outbound).to_be_visible()
    label = outbound.text_content() or ''
    assert 'flying' in label, f"Expected 'flying' in outbound divider, got: {label!r}"


# ---------------------------------------------------------------------------
# Trip detail — round trips
# ---------------------------------------------------------------------------

def test_round_trip_has_return_divider(page: Page):
    """A round-trip must show both Outbound and Return section dividers."""
    page.goto(f'{BASE_URL}/#/trips')
    page.wait_for_load_state('networkidle')
    cards = page.locator('.trip-card')
    if cards.count() == 0:
        pytest.skip('No trips in database')

    for i in range(min(cards.count(), 8)):
        cards.nth(i).click()
        page.wait_for_load_state('networkidle')

        ret = page.locator('.section-divider-label', has_text='Return')
        if ret.count() > 0:
            expect(ret.first).to_be_visible()
            return

        page.go_back()
        page.wait_for_load_state('networkidle')

    pytest.skip('No round-trip found in first 8 trips')


# ---------------------------------------------------------------------------
# Trip detail — connections
# ---------------------------------------------------------------------------

def test_connection_badge_visible_for_multi_leg(page: Page):
    """Multi-leg outbound must show a connection badge with a time label."""
    page.goto(f'{BASE_URL}/#/trips')
    page.wait_for_load_state('networkidle')
    cards = page.locator('.trip-card')
    if cards.count() == 0:
        pytest.skip('No trips in database')

    for i in range(min(cards.count(), 15)):
        cards.nth(i).click()
        page.wait_for_load_state('networkidle')

        badges = page.locator('.connection-badge')
        if badges.count() > 0:
            expect(badges.first).to_be_visible()
            label = badges.first.locator('.connection-badge-label')
            expect(label).to_be_visible()
            # Label should look like "2h 30m at LIS"
            text = label.text_content() or ''
            assert 'at' in text or 'm' in text, f"Unexpected badge text: {text!r}"
            return

        page.go_back()
        page.wait_for_load_state('networkidle')

    pytest.skip('No multi-leg trip found in first 15 trips')


def test_no_total_shown_for_long_stopover(page: Page):
    """Outbound divider must NOT show a total when any connection exceeds 24 h."""
    page.goto(f'{BASE_URL}/#/trips')
    page.wait_for_load_state('networkidle')
    cards = page.locator('.trip-card')
    if cards.count() == 0:
        pytest.skip('No trips in database')

    # Look for a trip that has a multi-day stopover (24 h+ connection badge)
    for i in range(min(cards.count(), 15)):
        cards.nth(i).click()
        page.wait_for_load_state('networkidle')

        badges = page.locator('.connection-badge-label')
        for j in range(badges.count()):
            text = badges.nth(j).text_content() or ''
            # Extract hours from labels like "26h 15m at LIS"
            import re
            m = re.search(r'(\d+)h', text)
            if m and int(m.group(1)) >= 24:
                # Found a long stopover — the outbound divider should NOT say "total"
                outbound = page.locator('.section-divider-label', has_text='Outbound').first
                label = outbound.text_content() or ''
                assert 'total' not in label, (
                    f"'total' should not appear when stopover ≥ 24h, got: {label!r}"
                )
                return

        page.go_back()
        page.wait_for_load_state('networkidle')

    pytest.skip('No trip with 24 h+ stopover found')


# ---------------------------------------------------------------------------
# Flight detail navigation
# ---------------------------------------------------------------------------

def test_clicking_flight_opens_detail(page: Page):
    """Clicking a flight row should navigate to the flight detail page."""
    if not go_to_first_trip(page):
        pytest.skip('No trips in database')

    try:
        page.wait_for_selector('.flight-row', state='visible', timeout=5000)
    except Exception:
        pytest.skip('No flight rows found')

    page.locator('.flight-row').first.click()
    page.wait_for_load_state('networkidle')
    assert '/flights/' in page.url, f"Expected flight detail URL, got: {page.url}"
