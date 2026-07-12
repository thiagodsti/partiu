"""
Ensures the service worker script and SPA shell are never cached by the
browser, so a new deploy is picked up promptly instead of being served
stale (the bug this guards against: PWA users on mobile not seeing new
versions until they reinstall the app).
"""

import backend.main as main


class TestStaticCacheHeaders:
    def test_sw_js_is_not_cached(self):
        response = main.serve_sw()
        assert response.headers.get("cache-control") == "no-cache"

    def test_spa_shell_is_not_cached(self):
        response = main.serve_spa("some/client/route")
        assert response.headers.get("cache-control") == "no-cache"
