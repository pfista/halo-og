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


def straight_parts(share, detail):
    """The pixels whose share is explained by a straight level or upright edge, each with how it is filled.

    Along a straight edge that does not lie on a pixel boundary, the pixels it crosses all hold the same
    share, with solid pixels on one side and empty ones on the other: a strip. Where two such edges meet,
    the corner pixel holds the product of their two shares (or all but the product of what they leave).
    These pixels are filled as exactly that, so stems, bars and their corners come out straight and
    square. Smoothing cannot do it: it rounds every corner, and holding the area then bulges the end."""
    rows, columns = share.shape
    level = np.rint(share * 15).astype(int)
    solid, blank = level == 15, level == 0
    strips = {}  # (row, column) -> (upright?, the side the ink is on: -1 left/top, 1 right/bottom)
    for upright in (True, False):
        for y in range(1, rows - 1):
            for x in range(1, columns - 1):
                if solid[y, x] or blank[y, x]:
                    continue
                before, after = ((y, x - 1), (y, x + 1)) if upright else ((y - 1, x), (y + 1, x))
                side = -1 if solid[before] and blank[after] else 1 if blank[before] and solid[after] else 0
                if side:
                    strips[(y, x, upright)] = side
    runs = []  # (cells, upright?, share, side)
    for (y, x, upright), side in strips.items():  # two or more in a row along the edge, a level apart at most
        step = (1, 0) if upright else (0, 1)
        if strips.get((y - step[0], x - step[1], upright)) == side and abs(level[y - step[0], x - step[1]] - level[y, x]) <= 1:
            continue  # (not the start of its run)
        run = [(y, x)]
        while strips.get((run[-1][0] + step[0], run[-1][1] + step[1], upright)) == side and \
                abs(level[run[-1][0] + step[0], run[-1][1] + step[1]] - level[run[-1]]) <= 1:
            run.append((run[-1][0] + step[0], run[-1][1] + step[1]))
        if len(run) >= 2:
            runs.append((run, upright, float(np.mean([share[cell] for cell in run])), side))
    width = {(cell, upright): (index, mean, side) for index, (run, upright, mean, side) in enumerate(runs) for cell in run}

    def block(across, down):
        """A pixel filled across (share, side) and down (share, side); None for all of that direction."""
        pattern = np.ones((detail, detail), bool)
        for axis, part in ((1, across), (0, down)):
            if part:
                keep = np.zeros(detail, bool)
                keep[:int(round(part[0] * detail))] = True
                if part[1] > 0:
                    keep = keep[::-1]
                pattern &= keep[None, :] if axis == 1 else keep[:, None]
        return pattern

    corners = {}  # cell -> (pattern, the two runs that meet in it)
    for y in range(1, rows - 1):
        for x in range(1, columns - 1):
            if solid[y, x] or blank[y, x] or ((y, x), True) in width or ((y, x), False) in width:
                continue
            for dx in (-1, 1):
                for dy in (-1, 1):
                    # an outside corner: the upright edge comes from the pixel above or below, the level one from beside
                    upright_edge, level_edge = width.get(((y + dy, x), True)), width.get(((y, x + dx), False))
                    if upright_edge and level_edge and upright_edge[2] == dx and level_edge[2] == dy and \
                            blank[y - dy, x] and blank[y, x - dx] and abs(upright_edge[1] * level_edge[1] - share[y, x]) <= 0.7 / 15:
                        corners[(y, x)] = (block((upright_edge[1], dx), (level_edge[1], dy)), (upright_edge[0], level_edge[0]))
                    # an inside corner: solid toward the ink, the two edges leaving along the other sides
                    upright_edge, level_edge = width.get(((y - dy, x), True)), width.get(((y, x - dx), False))
                    if upright_edge and level_edge and upright_edge[2] == dx and level_edge[2] == dy and \
                            solid[y + dy, x] and solid[y, x + dx] and \
                            abs(1 - (1 - upright_edge[1]) * (1 - level_edge[1]) - share[y, x]) <= 0.7 / 15:
                        corners[(y, x)] = (~block((1 - upright_edge[1], -dx), (1 - level_edge[1], -dy)), (upright_edge[0], level_edge[0]))
    # A curve at its highest, lowest, leftmost or rightmost also runs level or upright for a few pixels, and
    # must stay a curve. A stroke's edge is long, or ends at both ends in a corner: on a pixel boundary (the
    # next pixel solid or empty) or in a corner pixel as above.
    kept = set()
    for index, (run, upright, mean, side) in enumerate(runs):
        step = (1, 0) if upright else (0, 1)
        ends = [(run[0][0] - step[0], run[0][1] - step[1]), (run[-1][0] + step[0], run[-1][1] + step[1])]
        if len(run) >= 6 or all(solid[end] or blank[end] or (end in corners and index in corners[end][1]) for end in ends):
            kept.add(index)
    patterns = {}
    for index in kept:
        run, upright, mean, side = runs[index]
        for cell in run:
            if (cell, not upright) not in width or width[(cell, not upright)][0] not in kept:
                patterns[cell] = block((mean, side), None) if upright else block(None, (mean, side))
    for cell, (pattern, pair) in corners.items():
        if pair[0] in kept and pair[1] in kept:
            patterns[cell] = pattern
    return patterns


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
    straight = straight_parts(share, detail)

    def hold(samples):
        for (y, x), pattern in straight.items():
            samples[y * detail:(y + 1) * detail, x * detail:(x + 1) * detail] = pattern
        return samples

    field = hold(field)
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
        field = hold((blocks > level[..., None]).reshape(rows, columns, detail, detail).transpose(0, 2, 1, 3).reshape(
            rows * detail, columns * detail).astype(np.float32))
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
