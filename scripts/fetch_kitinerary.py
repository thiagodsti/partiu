#!/usr/bin/env python3
"""Download KDE's static kitinerary-extractor build into a directory.

Used by the Dockerfile. KDE's CI publishes a self-contained x86_64 build (one
binary plus translation catalogs, ~35 MB unpacked, needs only glibc) at
https://cdn.kde.org/ci-builds/pim/kitinerary/release-<major.minor>/linux/. It
is the build Nextcloud's KItinerary integration ships. The distro package was
tried first and pulled in ~600 MB of Qt/KDE Frameworks; this does not.

The version and its SHA-256 are pinned by the caller and the archive is
refused on a mismatch. KDE keeps only the latest patch of each release series
on the CDN, so a pinned version can disappear: when it does the build fails
loudly — bump KITINERARY_VERSION and KITINERARY_SHA256 in the Dockerfile to the
newest build listed there (each .tgz has a .sha256 beside it).

    python fetch_kitinerary.py <version> <sha256> <dest-dir>
"""

import hashlib
import io
import sys
import tarfile
import urllib.request

_URL = "https://cdn.kde.org/ci-builds/pim/kitinerary/release-{series}/linux/kitinerary-extractor-x86_64-{version}.tgz"


def archive_url(version: str) -> str:
    series = ".".join(version.split(".")[:2])
    return _URL.format(series=series, version=version)


def verify(data: bytes, sha256: str) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256.lower():
        raise SystemExit(f"kitinerary: checksum mismatch (got {digest}, expected {sha256})")


def extract(data: bytes, dest: str) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        # filter="data" refuses absolute paths, links out of the tree and
        # device files.
        archive.extractall(dest, filter="data")


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        raise SystemExit(__doc__)
    version, sha256, dest = argv[1:]
    url = archive_url(version)
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    verify(data, sha256)
    extract(data, dest)
    print(f"kitinerary {version}: {len(data) // 1024} KiB from {url}")


if __name__ == "__main__":
    main(sys.argv)
