"""Tests for the Wikipedia article lookup (backend/suggestions/photos.py)."""

from unittest.mock import patch

import httpx

from backend.suggestions import photos

LISBON = (38.7223, -9.1393)


def _pages(*pages):
    body = {"query": {"pages": {str(i): p | {"index": i} for i, p in enumerate(pages)}}}
    return httpx.Response(200, json=body, request=httpx.Request("GET", photos._API))


def _page(title, lat, lon, thumb=True):
    page = {
        "title": title,
        "coordinates": [{"lat": lat, "lon": lon}],
        "fullurl": f"https://en.wikipedia.org/wiki/{title}",
    }
    if thumb:
        page["thumbnail"] = {"source": f"https://upload.wikimedia.org/{title}.jpg"}
    return page


def _find(name, reply):
    with patch.object(photos.httpx, "get", return_value=reply) as get:
        found = photos.article_for(name, "Lisbon", LISBON, 40)
    return found, get


class TestArticleFor:
    def test_the_article_about_the_place_gives_photo_and_position(self):
        found, get = _find(
            "Torre de Belém",
            _pages(
                _page("Jerónimos Monastery", 38.6979, -9.2068),
                _page("Belém Tower", 38.6916, -9.2160),
            ),
        )
        assert found == {
            "image_url": "https://upload.wikimedia.org/Belém Tower.jpg",
            "page_url": "https://en.wikipedia.org/wiki/Belém Tower",
            "lat": 38.6916,
            "lon": -9.2160,
        }
        assert get.call_args.kwargs["params"]["gsrsearch"] == "Torre de Belém Lisbon"

    def test_an_article_without_a_photo_still_places_the_pin(self):
        found, _ = _find("Belém Tower", _pages(_page("Belém Tower", 38.6916, -9.2160, thumb=False)))
        assert found is not None and found["image_url"] is None and found["lat"] == 38.6916

    def test_the_district_named_in_the_place_does_not_lend_its_photo(self):
        found, _ = _find("Café Chiado", _pages(_page("Chiado", 38.7108, -9.1420)))
        assert found is None

    def test_a_namesake_elsewhere_is_not_it(self):
        found, _ = _find("Belém Tower", _pages(_page("Belém Tower", -1.45, -48.5)))  # Belém, Brazil
        assert found is None

    def test_an_article_with_no_coordinates_is_skipped(self):
        page = _page("Belém Tower", 0, 0)
        del page["coordinates"]
        found, _ = _find("Belém Tower", _pages(page))
        assert found is None

    def test_wikipedia_trouble_is_just_no_article(self):
        with patch.object(photos.httpx, "get", side_effect=httpx.ConnectError("down")):
            assert photos.article_for("Belém Tower", "Lisbon", LISBON, 40) is None


class TestAddArticles:
    def test_every_card_gets_every_field(self):
        cards = [{"title": "Belém Tower"}, {"title": "Café X"}]
        found = {"Belém Tower": {"image_url": "u", "page_url": "p", "lat": 1.0, "lon": 2.0}}
        with patch.object(photos, "article_for", side_effect=lambda name, *a: found.get(name)):
            photos.add_articles(cards, "Lisbon", LISBON, 40)
        assert cards[0] | {} == {
            "title": "Belém Tower",
            "on_wikipedia": True,
            "image_url": "u",
            "image_page": "p",
            "lat": 1.0,
            "lon": 2.0,
        }
        assert cards[1]["on_wikipedia"] is False and cards[1]["lat"] is None
