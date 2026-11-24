#!/usr/bin/env python3
"""Rebuild a bitmap font of the maps as a scalable font of our own.

The maps' text fonts are small bitmaps: letters 10 to 13 pixels tall in 16
levels. Each letter is redrawn as an outline, from its own pixels alone:

1. decode: the 16 stored levels are not brightness. They are evenly spaced
   shares of a pixel, stored through a curve that lifts the faint ones (one
   fifteenth of a pixel is stored as 104 of 255). Read as brightness they make
   every stroke a third of a pixel too heavy and close the small counters;
2. reconstruct: the smoothest shape that covers exactly that share of every
   pixel. A fully covered pixel stays solid and an empty one stays empty, so
   edges and corners that lie on pixel boundaries stay sharp, and only what
   the pixels leave open is smoothed;
3. weigh: optionally move every edge out by a part of a pixel. The stored
   curve makes the original read heavier on screen than its true shape;
4. outline: lines and curves through the shape's edge (potrace);
5. write: a TrueType font, one glyph per character, with the tag's own
   advance and origin, so text set in it is spaced exactly as the original.

No other typeface is used. tools/font_lab.py shows the result beside the
original, letter by letter.

    python3 tools/og_font.py --output build/font-lab/fonts [--weight 0.15]

Needs NumPy, Pillow, potracer and fontTools, and game data in the primary
checkout.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from font_lab import MapFont, gaussian, shares, stored  # noqa: E402
from hud_assets import XboxMap  # noqa: E402
from primary_checkout import PRIMARY  # noqa: E402

# font tag -> (family name, file name)
FAMILIES = {
    "ui\\large_ui": ("OG Menu Large", "OGMenuLarge.ttf"),
    "ui\\small_ui": ("OG Menu Small", "OGMenuSmall.ttf"),
    "ui\\interstate": ("OG Message", "OGMessage.ttf"),
}
UNITS = 64    # font units to the original pixel
PAD = 2       # empty pixels kept around a bitmap
DETAIL = 16   # samples to the original pixel when reconstructing
SMOOTHING = 0.2  # pixels: how far each round of the reconstruction smooths
SLACK = 0.4   # of a level: how far a pixel's share may be from the middle of its level


def reconstruct(coverage, detail=DETAIL, rounds=80):
    """The smoothest shape that every pixel would store as it is stored, as a grid of `detail` samples to
    the pixel with PAD empty pixels around. Each round smooths the shape, then in every pixel keeps as many
    of the highest samples as its level allows (threshold dynamics, the area held pixel by pixel). A level
    stands for a range of shares, half a level either way, and the shape may use SLACK of a level of it:
    holding each pixel to the middle of its level carves the rounding of sixteen levels into the edges,
    and all of the range lets the smoothing round off the ends of strokes."""
    share = np.pad(shares(coverage), PAD)
    rows, columns = share.shape
    field = np.asarray(Image.fromarray(share, "F").resize((columns * detail, rows * detail), Image.BICUBIC)).copy()
    last = detail * detail - 1
    least = np.ceil(np.clip(share - SLACK / 15, 0, 1) * (last + 1)).astype(int)
    most = np.floor(np.clip(share + SLACK / 15, 0, 1) * (last + 1)).astype(int)
    for _ in range(rounds):
        field = gaussian(field, SMOOTHING * detail)
        blocks = field.reshape(rows, detail, columns, detail).transpose(0, 2, 1, 3).reshape(rows, columns, -1)
        wanted = np.clip((blocks > 0.5).sum(axis=2), least, most)
        order = np.sort(blocks, axis=2)
        below = np.take_along_axis(order, np.clip(last - wanted, 0, last)[..., None], 2)[..., 0]
        above = np.take_along_axis(order, np.clip(last + 1 - wanted, 0, last)[..., None], 2)[..., 0]
        level = np.where(wanted == 0, np.inf, np.where(wanted == last + 1, -np.inf, (below + above) / 2))
        field = (blocks > level[..., None]).reshape(rows, columns, detail, detail).transpose(0, 2, 1, 3).reshape(
            rows * detail, columns * detail).astype(np.float32)
    return field > 0.5


def weighed(shape, pixels, detail=DETAIL):
    """Every edge moved out by a part of a pixel (in for a negative one), with a square brush so corners stay square."""
    steps = int(round(pixels * detail))
    if not steps:
        return shape
    brush = ImageFilter.MaxFilter(2 * steps + 1) if steps > 0 else ImageFilter.MinFilter(-2 * steps + 1)
    return np.asarray(Image.fromarray(shape.astype(np.uint8) * 255, "L").filter(brush)) > 127


def outlines(shape, detail=DETAIL):
    """The shape's edges as paths of lines and curves, in original pixels from the bitmap's corner: each a
    starting point and steps ("line", point) or ("curve", control, control, point)."""
    import potrace

    # (nicks an eighth of a pixel wide are closed and the edge smoothed by a sample's worth first: the
    # reconstruction's edge is stepped a sample at a time)
    brush = 2 * max(detail // 8, 1) + 1
    closed = Image.fromarray(shape.astype(np.uint8) * 255, "L").filter(ImageFilter.MaxFilter(brush)).filter(ImageFilter.MinFilter(brush))
    tidy = gaussian(np.asarray(closed, np.float32) / 255, 0.08 * detail) > 0.5
    paths = []
    for curve in potrace.Bitmap(~tidy).trace(turdsize=detail, alphamax=1.0, opttolerance=0.4):
        def place(point):
            return np.array([point.x / detail - PAD, point.y / detail - PAD])
        steps, here = [], place(curve.start_point)
        for segment in curve.segments:
            end = place(segment.end_point)
            if segment.is_corner:
                steps += [("line", place(segment.c)), ("line", end)]
            else:
                steps.append(("curve", place(segment.c1), place(segment.c2), end))
            here = end
        paths.append((place(curve.start_point), steps))
    return paths


def corner_of(start, first, second, end):
    """The corner a curve rounds off, where it turns 50 degrees or more between two sides at least 1.2
    pixels long and cuts the corner by under 0.6 of a pixel; else None."""
    leave, arrive = first - start, end - second
    cross = leave[0] * arrive[1] - leave[1] * arrive[0]
    lengths = np.hypot(*leave) * np.hypot(*arrive)
    if lengths < 1e-9 or abs(cross) / lengths < 0.766:
        return None
    corner = start + leave * (((end[0] - start[0]) * arrive[1] - (end[1] - start[1]) * arrive[0]) / cross)
    middle = (start + 3 * first + 3 * second + end) / 8
    if min(np.hypot(*(corner - start)), np.hypot(*(end - corner))) < 0.6 or np.hypot(*(corner - middle)) >= 0.6:
        return None
    return corner


def difference(paths, coverage):
    """How far outlines are from a bitmap once shrunk to its pixels and stored as the maps store them."""
    return float(np.abs(stored(fill(paths, coverage.shape, 1, over=DETAIL)) - np.pad(coverage, PAD)).sum())


def sharpen(paths, coverage):
    """Each rounded corner made sharp wherever the bitmap's pixels are matched at least as well: sixteen
    levels cannot tell a small rounding from a sharp corner, the letters' corners are sharp, and the
    reconstruction rounds them."""
    paths = [(start, list(steps)) for start, steps in paths]
    best = difference(paths, coverage)
    for start, steps in paths:
        here = start
        for index, step in enumerate(steps):
            if step[0] == "curve":
                corner = corner_of(here, step[1], step[2], step[3])
                if corner is not None:
                    steps[index] = ("corner", corner, step[3])
                    found = difference(paths, coverage)
                    if found <= best + 0.02:
                        best = min(best, found)
                    else:
                        steps[index] = step
            here = step[-1]
    return [(start, [part for step in steps for part in (
        [("line", step[1]), ("line", step[2])] if step[0] == "corner" else [step])]) for start, steps in paths]


_letters = {}


def letter(coverage, weight=0.0):
    """A letter's outlines from its bitmap (remembered: the reconstruction is the slow part)."""
    key = (coverage.shape, coverage.tobytes(), weight)
    if key not in _letters:
        paths = sharpen(outlines(reconstruct(coverage)), coverage)
        if weight:  # (the weight is added to the finished outline, drawn large, and traced again)
            paths = outlines(weighed(fill(paths, coverage.shape, DETAIL) > 0.5, weight))
        _letters[key] = paths
    return _letters[key]


def flatten(path):
    start, steps = path
    points, here = [start], start
    for step in steps:
        if step[0] == "line":
            points.append(step[1])
        elif step[0] == "corner":
            points += [step[1], step[2]]
        else:
            t = np.linspace(0, 1, 13)[1:, None]
            points.extend((1 - t) ** 3 * here + 3 * (1 - t) ** 2 * t * step[1] + 3 * (1 - t) * t ** 2 * step[2] + t ** 3 * step[3])
        here = step[-1]
    return np.array(points)


def fill(paths, shape, scale, over=4):
    """Outlines filled (an outline inside another is a hole) at `scale` pixels to the bitmap's pixel, PAD around."""
    size = ((shape[1] + 2 * PAD) * scale * over, (shape[0] + 2 * PAD) * scale * over)
    filled = np.zeros(size[::-1], bool)
    for path in paths:
        points = flatten(path)
        if len(points) < 3:
            continue
        image = Image.new("1", size, 0)
        ImageDraw.Draw(image).polygon([((x + PAD) * scale * over, (y + PAD) * scale * over) for x, y in points], fill=1)
        filled ^= np.asarray(image, bool)
    return filled.reshape(size[1] // over, over, size[0] // over, over).mean(axis=(1, 3)).astype(np.float32)


def build(font: MapFont, family: str, path: Path, weight=0.0):
    """Write the font: every character of the tag, in font units of UNITS to the original pixel."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    order, mapping, glyphs, advances = [".notdef"], {}, {".notdef": TTGlyphPen(None).glyph()}, {".notdef": UNITS * 8}
    for code in sorted(font.glyphs):
        glyph = font.glyphs[code]
        name = "space" if code == 32 else f"uni{code:04X}"
        order.append(name)
        mapping[code] = name
        pen = TTGlyphPen(None)
        if glyph.ink:
            draw = Cu2QuPen(pen, max_err=0.5)

            def place(point):  # from the bitmap's corner, y down, to the pen on the baseline, y up
                return (float(point[0] - glyph.origin_x) * UNITS, float(glyph.origin_y - point[1]) * UNITS)

            for start, steps in letter(glyph.coverage, weight):
                draw.moveTo(place(start))
                for step in steps:
                    if step[0] == "line":
                        draw.lineTo(place(step[1]))
                    else:
                        draw.curveTo(place(step[1]), place(step[2]), place(step[3]))
                draw.closePath()
        glyphs[name] = pen.glyph()
        advances[name] = max(glyph.advance, 0) * UNITS
    builder = FontBuilder((font.ascending + font.descending) * UNITS, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(mapping)
    builder.setupGlyf(glyphs)
    table = builder.font["glyf"]
    metrics = {}
    for name in order:
        table[name].recalcBounds(table)
        metrics[name] = (advances[name], table[name].xMin if table[name].numberOfContours else 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=font.ascending * UNITS, descent=-font.descending * UNITS)
    builder.setupNameTable({"familyName": family, "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=font.ascending * UNITS, sTypoDescender=-font.descending * UNITS,
                     usWinAscent=font.ascending * UNITS, usWinDescent=font.descending * UNITS,
                     sCapHeight=font.capital_rows * UNITS)
    builder.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    builder.save(str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="Folder for the font files")
    parser.add_argument("--fonts", default=",".join(FAMILIES), help="Font tags, comma-separated")
    parser.add_argument("--weight", type=float, default=0.0, help="Move every edge out by this part of a pixel")
    args = parser.parse_args()
    cache = XboxMap(PRIMARY / "assets/maps/ui.map")
    for tag in args.fonts.split(","):
        family, file = FAMILIES[tag]
        font = MapFont(cache, tag)
        build(font, family, args.output / file, args.weight)
        print(f"{tag}: {args.output / file} ({family}, {len(font.glyphs)} characters)")


if __name__ == "__main__":
    main()
