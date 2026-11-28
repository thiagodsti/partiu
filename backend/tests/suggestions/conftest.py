import pytest


@pytest.fixture(autouse=True)
def _no_wikipedia(monkeypatch):
    """No network: test_photos.py covers the lookup against a mocked API.

    Here, an article exists only for names listed in ``ARTICLES``.
    """
    from backend.tests.suggestions import ARTICLES

    def fake(cards, city, centre, max_km):
        for card in cards:
            article = ARTICLES.get(card["title"])
            card["on_wikipedia"] = article is not None
            card["image_url"] = article["image_url"] if article else None
            card["image_page"] = article["page_url"] if article else None
            card["lat"] = article["lat"] if article else None
            card["lon"] = article["lon"] if article else None

    monkeypatch.setattr("backend.suggestions.service.add_articles", fake)
