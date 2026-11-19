"""Generate the iOS launch images in frontend/public/splash/.

iOS ignores the manifest's background_color and opens an installed PWA on a
blank screen unless a `apple-touch-startup-image` matches the device *exactly*
(CSS size, pixel ratio and orientation), so there is one image per device class
and per theme. The app is portrait-only (manifest `orientation`), so only
portrait images are made.

    uv run python scripts/generate_splash.py

Re-run after changing the icon or the page background colours, then paste the
printed <link> block into frontend/index.html between the SPLASH markers.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "frontend" / "public"
OUT = PUBLIC / "splash"

# Must match the page ink in index.html / app.css, or the launch image visibly
# swaps colour when the first frame paints.
THEMES = {"dark": "#0c0c0d", "light": "#f2f2f0"}

# (CSS width, CSS height, device pixel ratio), portrait.
DEVICES = [
    (440, 956, 3),  # iPhone 16 Pro Max
    (430, 932, 3),  # iPhone 14/15 Pro Max, 15/16 Plus
    (402, 874, 3),  # iPhone 16 Pro
    (393, 852, 3),  # iPhone 14 Pro, 15, 15 Pro, 16
    (428, 926, 3),  # iPhone 12/13 Pro Max, 14 Plus
    (390, 844, 3),  # iPhone 12, 13, 14
    (414, 896, 3),  # iPhone XS Max, 11 Pro Max
    (414, 896, 2),  # iPhone XR, 11
    (375, 812, 3),  # iPhone X, XS, 11 Pro, 12/13 mini
    (414, 736, 3),  # iPhone 6/7/8 Plus
    (375, 667, 2),  # iPhone 6/7/8, SE 2/3
    (1024, 1366, 2),  # iPad Pro 12.9"
    (834, 1194, 2),  # iPad Pro 11"
    (820, 1180, 2),  # iPad Air 10.9"
    (768, 1024, 2),  # iPad, iPad mini (older)
    (744, 1133, 2),  # iPad mini 6
]

ICON_FRACTION = 0.32  # of the shorter side


def render(width: int, height: int, background: str, icon: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (width, height), background)
    side = round(min(width, height) * ICON_FRACTION)
    mark = icon.resize((side, side), Image.Resampling.LANCZOS)
    canvas.paste(mark, ((width - side) // 2, (height - side) // 2), mark)
    return canvas


def main() -> None:
    OUT.mkdir(exist_ok=True)
    icon = Image.open(PUBLIC / "icon-512.png").convert("RGBA")
    links = []
    for css_w, css_h, dpr in DEVICES:
        px_w, px_h = css_w * dpr, css_h * dpr
        for theme, background in THEMES.items():
            name = f"splash-{px_w}x{px_h}-{theme}.png"
            render(px_w, px_h, background, icon).save(OUT / name, optimize=True)
            media = (
                f"(prefers-color-scheme: {theme}) and (device-width: {css_w}px) and "
                f"(device-height: {css_h}px) and (-webkit-device-pixel-ratio: {dpr}) "
                "and (orientation: portrait)"
            )
            links.append(
                f'    <link rel="apple-touch-startup-image" media="{media}" href="/splash/{name}" />'
            )
    print("\n".join(links))


if __name__ == "__main__":
    main()
