"""
Generate PNG app icons for PWA (apple-touch-icon, manifest icons).
Uses only Python stdlib — no extra dependencies.
Output files are written to frontend/public/.
"""
import struct
import zlib
from pathlib import Path

# Brand color: indigo #6366f1
BG = (99, 102, 241)
FG = (255, 255, 255)

# Minimal top-down airplane bitmap (32x32 grid, 1 = foreground)
# Designed on a 32x32 grid; scaled up at render time.
_PLANE_32 = """
00000000000001100000000000000000
00000000000011110000000000000000
00000000000111111000000000000000
00000000001111111100000000000000
00000000011111111110000000000000
00000000111111111111000000000000
00000001111111111111100000000000
00000011111111111111110000000000
00000111111111111111111000000000
00001111111111111111111100000000
11111111111111111111111111111100
11111111111111111111111111111111
11111111111111111111111111111111
11111111111111111111111111111100
00001111111111111111111100000000
00000111111111111111111000000000
00000011111111111111110000000000
00000001111111111111100000000000
00000000111111111111000000000000
00000000011111111110000000000000
00000000001111111100000000000000
00000000000111110000000000000000
00000000000011111100000000000000
00000000000001111110000000000000
00000000000000111111000000000000
00000000000000011111100000000000
00000000000000001111000000000000
00000000000000000110000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
"""


def _parse_bitmap():
    rows = [r for r in _PLANE_32.strip().split('\n') if r.strip()]
    return [[int(c) for c in row] for row in rows]


def _make_png(width: int, height: int, pixels_fn) -> bytes:
    """Build a minimal PNG. pixels_fn(x, y) returns (r, g, b)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        c = kind + data
        crc = zlib.crc32(c) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + c + struct.pack('>I', crc)

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: None
        for x in range(width):
            r, g, b = pixels_fn(x, y)
            raw += bytes([r, g, b])

    idat = chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    iend = chunk(b'IEND', b'')
    return sig + ihdr + idat + iend


def _make_icon(size: int) -> bytes:
    bitmap = _parse_bitmap()
    bm_size = len(bitmap)
    margin = round(size * 0.18)
    plane_area = size - 2 * margin

    # Corner radius for background (approx)
    radius = round(size * 0.18)

    def in_rounded_rect(x: int, y: int) -> bool:
        if x < radius and y < radius:
            return (x - radius) ** 2 + (y - radius) ** 2 <= radius ** 2
        if x > size - 1 - radius and y < radius:
            return (x - (size - 1 - radius)) ** 2 + (y - radius) ** 2 <= radius ** 2
        if x < radius and y > size - 1 - radius:
            return (x - radius) ** 2 + (y - (size - 1 - radius)) ** 2 <= radius ** 2
        if x > size - 1 - radius and y > size - 1 - radius:
            return (x - (size - 1 - radius)) ** 2 + (y - (size - 1 - radius)) ** 2 <= radius ** 2
        return True

    def pixel(x: int, y: int):
        if not in_rounded_rect(x, y):
            return (255, 255, 255)  # transparent corners → white bg for PNG

        # Map pixel to bitmap grid
        bx = int((x - margin) * bm_size / plane_area)
        by = int((y - margin) * bm_size / plane_area)

        if 0 <= bx < bm_size and 0 <= by < bm_size and bitmap[by][bx]:
            return FG
        return BG

    return _make_png(size, size, pixel)


def main():
    out = Path(__file__).parent / 'frontend' / 'public'
    out.mkdir(parents=True, exist_ok=True)

    sizes = {
        'apple-touch-icon.png': 180,
        'icon-192.png': 192,
        'icon-512.png': 512,
    }
    for name, size in sizes.items():
        data = _make_icon(size)
        (out / name).write_bytes(data)
        print(f'Generated {name} ({size}x{size})')


if __name__ == '__main__':
    main()
