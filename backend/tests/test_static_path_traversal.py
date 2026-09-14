"""
Guards the SPA catch-all route against unauthenticated arbitrary file read.

``serve_spa`` used to join the request path straight onto the frontend directory
(``base / full_path``), which served any file on the host to anyone who could
reach the port — no session required, since the catch-all is deliberately
unauthenticated and ``FirstRunMiddleware`` only gates ``/api/`` paths. Two vectors
reached it and a fix that closes only one is no fix at all:

* an **absolute** path parameter, which pathlib resolves by discarding the base
  entirely — reachable from a browser address bar as ``GET //etc/passwd``, since
  the doubled slash leaves ``/etc/passwd`` in the path parameter;
* **percent-encoded** traversal (``GET /..%2f..%2f.env``), decoded into the path
  parameter after the server's own path normalisation has already run.

Both were confirmed against the running app: the first returned ``/etc/passwd``
and the second the project's ``.env``, which carries ``SECRET_KEY`` — itself the
key that decrypts the stored IMAP and Immich credentials. The paths are exercised
through ``_resolve_static_file`` directly rather than over HTTP because an HTTP
client normalises some of these before they are ever sent, which would make the
assertions pass without testing anything.
"""

from pathlib import Path

import backend.main as main


def _base() -> Path:
    return main._FRONTEND_DIR


class TestAbsolutePathIsRejected:
    """`Path(base) / "/abs"` silently discards the base — the `//etc/passwd` vector."""

    def test_absolute_system_path(self):
        assert main._resolve_static_file(_base(), "/etc/passwd") is None

    def test_absolute_path_to_project_secret(self):
        env = Path(__file__).parent.parent.parent / ".env"
        assert main._resolve_static_file(_base(), str(env)) is None

    def test_absolute_path_to_database(self):
        db = Path(__file__).parent.parent.parent / "data" / "partiu.db"
        assert main._resolve_static_file(_base(), str(db)) is None


class TestTraversalIsRejected:
    """Decoded `..` segments must not climb out of the frontend directory."""

    def test_dotdot_to_env(self):
        assert main._resolve_static_file(_base(), "../../.env") is None

    def test_dotdot_to_database(self):
        assert main._resolve_static_file(_base(), "../../data/partiu.db") is None

    def test_deep_dotdot_to_system_file(self):
        assert main._resolve_static_file(_base(), "../../../../../../etc/passwd") is None

    def test_dotdot_buried_mid_path(self):
        assert main._resolve_static_file(_base(), "assets/../../../.env") is None


class TestLegitimateFilesStillServe:
    """The fix must not break ordinary static serving — the point of the route."""

    def test_index_html_resolves(self):
        resolved = main._resolve_static_file(_base(), "index.html")
        assert resolved is not None
        assert resolved.name == "index.html"

    def test_directory_is_not_served_as_a_file(self):
        assert main._resolve_static_file(_base(), "assets") is None

    def test_unknown_path_resolves_to_nothing(self):
        assert main._resolve_static_file(_base(), "trips/some-id") is None


class TestServeSpaFallsThroughToShell:
    """A rejected path must look exactly like any unknown route, not a 403.

    Reporting the rejection would confirm which files exist on the host.
    """

    def test_traversal_returns_the_spa_shell(self):
        response = main.serve_spa("../../.env")
        assert Path(response.path).name == "index.html"

    def test_absolute_path_returns_the_spa_shell(self):
        response = main.serve_spa("/etc/passwd")
        assert Path(response.path).name == "index.html"
