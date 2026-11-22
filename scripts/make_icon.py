"""Generate the Workforge mark at every size it is used.

    python scripts/make_icon.py

Outputs PNGs in assets/, a multi-resolution ICO for the desktop shortcut, and
favicon/hero copies inside site/ so the Cloudflare deployment is self-contained.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 4  # supersample for smooth diagonals
SIZE = 256


def build() -> Image.Image:
    n = SIZE * S
    img = Image.new("RGB", (n, n))
    px = img.load()
    for y in range(n):
        t = y / n
        for x in range(n):
            px[x, y] = (
                int(11 + (19 - 11) * t),
                int(16 + (26 - 16) * t),
                int(32 + (53 - 32) * t),
            )
    d = ImageDraw.Draw(img)
    sc = lambda pts: [(int(x * S), int(y * S)) for x, y in pts]
    outer = [(128, 28), (206, 74), (206, 182), (128, 228), (50, 182), (50, 74)]
    inner = [(128, 52), (186, 87), (186, 169), (128, 204), (70, 169), (70, 87)]
    d.polygon(sc(outer), outline=(56, 189, 248, 150), width=3 * S)
    d.line(sc(outer + [outer[0]]), fill=(56, 189, 248), width=3 * S, joint="curve")
    d.polygon(sc(inner), fill=(15, 32, 56), outline=(167, 139, 250), width=2 * S)
    d.line(sc(inner + [inner[0]]), fill=(167, 139, 250), width=2 * S, joint="curve")
    pulse = [(76, 130), (104, 130), (116, 100), (132, 158), (144, 124), (178, 124)]
    d.line(sc(pulse), fill=(34, 211, 238), width=6 * S, joint="curve")
    for x, y in (pulse[0], pulse[-1]):
        d.ellipse([x * S - 2 * S, y * S - 2 * S, x * S + 2 * S, y * S + 2 * S],
                  fill=(34, 211, 238))
    r = 5 * S
    d.ellipse([128 * S - r, 130 * S - r, 128 * S + r, 130 * S + r], fill=(240, 171, 252))
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    img = build()
    assets = ROOT / "assets"
    site = ROOT / "site"
    assets.mkdir(exist_ok=True)
    site.mkdir(exist_ok=True)
    for size in (16, 32, 48, 64, 128, 256, 512):
        img.resize((size, size), Image.LANCZOS).save(assets / f"icon-{size}.png")
    img.resize((256, 256), Image.LANCZOS).save(assets / "icon.png")
    img.save(assets / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48),
                                         (64, 64), (128, 128), (256, 256)])
    img.resize((256, 256), Image.LANCZOS).save(site / "icon.png")
    img.resize((64, 64), Image.LANCZOS).save(site / "favicon.png")
    print("generated icons in assets/ and site/")


if __name__ == "__main__":
    main()
