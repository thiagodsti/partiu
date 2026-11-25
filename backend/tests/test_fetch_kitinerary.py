"""scripts/fetch_kitinerary.py: the Docker build's download of KDE's static extractor.

No network here: the URL is checked as a string and the archive is built in
memory. What matters is that a wrong checksum stops the build and that a
hostile archive cannot write outside the target folder.
"""

import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "fetch_kitinerary.py"
_spec = importlib.util.spec_from_file_location("fetch_kitinerary", _PATH)
assert _spec and _spec.loader
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)


def _tgz(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestFetchKitinerary:
    def test_url_follows_the_cdn_layout(self):
        assert fetch.archive_url("26.04.3") == (
            "https://cdn.kde.org/ci-builds/pim/kitinerary/release-26.04/linux/"
            "kitinerary-extractor-x86_64-26.04.3.tgz"
        )

    def test_a_checksum_mismatch_stops_the_build(self):
        with pytest.raises(SystemExit, match="checksum mismatch"):
            fetch.verify(b"archive", "0" * 64)

    def test_a_matching_checksum_passes(self):
        data = b"archive"
        fetch.verify(data, hashlib.sha256(data).hexdigest().upper())

    def test_extracts_the_binary(self, tmp_path):
        fetch.extract(_tgz({"bin/kitinerary-extractor": b"\x7fELF"}), str(tmp_path))
        assert (tmp_path / "bin" / "kitinerary-extractor").read_bytes() == b"\x7fELF"

    def test_refuses_paths_outside_the_target(self, tmp_path):
        target = tmp_path / "kit"
        target.mkdir()
        with pytest.raises(tarfile.TarError):
            fetch.extract(_tgz({"../escaped": b"x"}), str(target))
        assert not (tmp_path / "escaped").exists()
