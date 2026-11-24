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
SMOOTH = 0.06    # pixels: how far a refitted curve may be from the traced edge
CORNER_SPAN = 0.35  # pixels either side of a point within which a corner's turn is measured
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


def outlines(shape, detail=DETAIL, tidy=True):
    """The shape's edges as paths of lines and curves, in original pixels from the bitmap's corner: each a
    starting point and steps ("line", point) or ("curve", control, control, point)."""
    import potrace

    # (nicks an eighth of a pixel wide are closed and the edge smoothed by a sample's worth first: the
    # reconstruction's edge is stepped a sample at a time)
    brush = 2 * max(detail // 8, 1) + 1
    # (a drawing of finished outlines needs neither, and its corners must stay exact to be found as corners)
    if tidy:
        closed = Image.fromarray(shape.astype(np.uint8) * 255, "L").filter(ImageFilter.MaxFilter(brush)).filter(ImageFilter.MinFilter(brush))
        shape = gaussian(np.asarray(closed, np.float32) / 255, 0.08 * detail) > 0.5
    paths = []
    for curve in potrace.Bitmap(~shape).trace(turdsize=detail, alphamax=1.0, opttolerance=0.4):
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


def corner_of(start, first, second, end, side=0.6, cut=0.6):
    """The corner a curve rounds off, where it turns 50 degrees or more between two sides at least twice
    `side` pixels long and cuts the corner by under `cut` of a pixel; else None."""
    leave, arrive = first - start, end - second
    cross = leave[0] * arrive[1] - leave[1] * arrive[0]
    lengths = np.hypot(*leave) * np.hypot(*arrive)
    if lengths < 1e-9 or abs(cross) / lengths < 0.766:
        return None
    corner = start + leave * (((end[0] - start[0]) * arrive[1] - (end[1] - start[1]) * arrive[0]) / cross)
    middle = (start + 3 * first + 3 * second + end) / 8
    if min(np.hypot(*(corner - start)), np.hypot(*(end - corner))) < side or np.hypot(*(corner - middle)) >= cut:
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


def squared(paths):
    """Corners that outlining a drawing of sharp-cornered outlines rounded by a sample or two, made sharp again."""
    result = []
    for start, steps in paths:
        here, kept = start, []
        for step in steps:
            corner = corner_of(here, step[1], step[2], step[3], side=0.25, cut=0.12) if step[0] == "curve" else None
            kept += [("line", corner), ("line", step[3])] if corner is not None else [step]
            here = step[-1]
        result.append((start, kept))
    return result


def unit(vector):
    length = float(np.hypot(vector[0], vector[1]))
    return vector / length if length > 1e-9 else np.array([1.0, 0.0])


def bezier(curve, t):
    t = np.asarray(t)[:, None]
    return (1 - t) ** 3 * curve[0] + 3 * (1 - t) ** 2 * t * curve[1] + 3 * (1 - t) * t ** 2 * curve[2] + t ** 3 * curve[3]


def fit_cubics(points, start, end, tolerance, depth=0):
    """As few cubic curves through a run of points as stay within the tolerance, leaving along `start` and
    arriving against `end` (unit vectors pointing into the run from each of its ends). Schneider's fit."""
    if len(points) == 2:
        reach = float(np.hypot(*(points[1] - points[0]))) / 3
        return [np.array([points[0], points[0] + start * reach, points[1] + end * reach, points[1]])]
    along = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(points, axis=0).T))])
    total = along[-1]
    u = along / max(total, 1e-9)
    curve, worst = None, 1
    for _ in range(4):
        b0, b1, b2, b3 = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u ** 2, u ** 3
        a1, a2 = start[None, :] * b1[:, None], end[None, :] * b2[:, None]
        rest = points - (points[0][None, :] * (b0 + b1)[:, None] + points[-1][None, :] * (b2 + b3)[:, None])
        c00, c01, c11 = (a1 * a1).sum(), (a1 * a2).sum(), (a2 * a2).sum()
        x0, x1 = (a1 * rest).sum(), (a2 * rest).sum()
        determinant = c00 * c11 - c01 * c01
        first = second = 0.0
        if abs(determinant) > 1e-12:
            first, second = (x0 * c11 - x1 * c01) / determinant, (c00 * x1 - c01 * x0) / determinant
        if first < total * 1e-3 or second < total * 1e-3:  # (a handle pointing backwards: thirds instead)
            first = second = total / 3
        curve = np.array([points[0], points[0] + start * first, points[-1] + end * second, points[-1]])
        error = np.hypot(*(bezier(curve, u) - points).T)
        worst = int(np.argmax(error[1:-1])) + 1
        if error[worst] <= tolerance:
            return [curve]
        # move each point's place along the curve toward where the curve is nearest it, and fit again
        d1 = 3 * ((1 - u) ** 2)[:, None] * (curve[1] - curve[0]) + 6 * ((1 - u) * u)[:, None] * (curve[2] - curve[1]) + \
            3 * (u ** 2)[:, None] * (curve[3] - curve[2])
        d2 = 6 * (1 - u)[:, None] * (curve[2] - 2 * curve[1] + curve[0]) + 6 * u[:, None] * (curve[3] - 2 * curve[2] + curve[1])
        off = bezier(curve, u) - points
        bottom = (d1 * d1).sum(axis=1) + (off * d2).sum(axis=1)
        u = np.clip(u - np.where(np.abs(bottom) > 1e-9, (off * d1).sum(axis=1) / np.where(bottom == 0, 1, bottom), 0), 0, 1)
        u[0], u[-1] = 0, 1
    if depth > 7 or len(points) < 6:
        return [curve]
    worst = min(max(worst, 2), len(points) - 3)
    middle = unit(points[worst - 2] - points[worst + 2])
    return fit_cubics(points[:worst + 1], start, middle, tolerance, depth + 1) + \
        fit_cubics(points[worst:], -middle, end, tolerance, depth + 1)


def pieces(path):
    """A path as its pieces, each with its own start: ["line", a, b] or ["curve", a, control, control, b]."""
    start, steps = path
    found, here = [], start
    for step in steps:
        if np.hypot(*(step[-1] - here)) > 1e-6:
            found.append(["line", here, step[1]] if step[0] == "line" else ["curve", here, step[1], step[2], step[3]])
        here = step[-1]
    return found


def corners_in(points, closed=False, sharp=50.0):
    """Where a run of points turns a corner: the places it turns `sharp` degrees or more within `span`
    pixels either side, as indices. A closed run (its last point is its first) is searched all the way round."""
    span = CORNER_SPAN
    count = len(points) - 1 if closed else len(points)
    ring = np.concatenate([points[:count]] * 3) if closed else points
    along = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(ring, axis=0).T))])
    turn = np.zeros(count)
    for index in range(count):
        at = index + count if closed else index
        before, after = np.searchsorted(along, along[at] - span, side="right") - 1, np.searchsorted(along, along[at] + span)
        if before < 0 or after >= len(ring) or along[at] - along[before] < span * 0.6 or along[after] - along[at] < span * 0.6:
            continue
        into, out = ring[at] - ring[before], ring[after] - ring[at]
        turn[index] = abs(np.degrees(np.arctan2(into[0] * out[1] - into[1] * out[0], into @ out)))
    found = []
    for index in np.argsort(-turn):  # the sharpest first; nothing else within a span of one already taken
        if turn[index] < sharp:
            break
        place = along[index + count if closed else index]
        if all(min(abs(place - along[(other + count) if closed else other]), (along[count] - abs(place - along[other + count])) if closed else 1e9) > span for other in found):
            found.append(int(index))
    return sorted(found)


def refit(points, leave, arrive, tolerance):
    """Steps through a run of points: split at its corners, each part a line where it is straight within
    the tolerance and otherwise as few curves as stay within it. `leave` and `arrive` are the directions
    the run must start and end along (None at an end that is a corner)."""
    cuts = [0] + corners_in(points) + [len(points) - 1]
    steps = []
    for first, last in zip(cuts, cuts[1:]):
        part = points[first:last + 1]
        if len(part) < 2:
            continue
        along = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(part, axis=0).T))])
        near, far = min(int(np.searchsorted(along, 0.25)), len(part) - 1) or 1, max(int(np.searchsorted(along, along[-1] - 0.25)) - 1, 0)
        start = leave if first == 0 and leave is not None else unit(part[near] - part[0])
        end = -arrive if last == len(points) - 1 and arrive is not None else unit(part[min(far, len(part) - 2)] - part[-1])
        chord = unit(part[-1] - part[0])
        stray = np.abs((part[:, 0] - part[0][0]) * chord[1] - (part[:, 1] - part[0][1]) * chord[0]).max()
        if stray <= tolerance and start @ chord > 0.94 and -end @ chord > 0.94:
            steps.append(("line", part[-1]))
        else:
            steps += [("curve", c[1], c[2], c[3]) for c in fit_cubics(part, start, end, tolerance)]
    return steps


def smoothed(paths, tolerance):
    """Each run of curves between straight lines redrawn: split at its corners, and each part a line where
    it is straight within the tolerance, otherwise as few curves as stay within the tolerance of it. The
    reconstruction holds every pixel's ink, and sixteen levels of it are coarse: along a curve or a slope
    that leaves ripples a few hundredths of a pixel high, which this takes out. Straight edges are lines
    already and are left alone; corners stay corners."""
    result = []
    for path in paths:
        found = pieces(path)
        if len(found) < 2:
            continue
        lines = [index for index, piece in enumerate(found) if piece[0] == "line"]

        def sampled(run):
            return np.concatenate([run[0][1][None, :]] + [bezier(np.array(piece[1:]), np.linspace(0, 1, 11)[1:]) for piece in run])

        if not lines:  # one closed outline with no straight line in it
            points = sampled(found)
            turned = corners_in(points, closed=True)
            if turned:  # start it at a corner
                points = np.concatenate([points[turned[0]:-1], points[:turned[0] + 1]])
                result.append((points[0], refit(points, None, None, tolerance)))
            else:  # a closed curve: it leaves and arrives along the same direction
                heading = unit(points[1] - points[-2])
                result.append((points[0], [("curve", c[1], c[2], c[3]) for c in fit_cubics(points, heading, -heading, tolerance)]))
            continue
        found = found[lines[0]:] + found[:lines[0]]
        steps, index = [], 0
        while index < len(found):
            if found[index][0] == "line":
                steps.append(("line", found[index][2]))
                index += 1
                continue
            last = index
            while last < len(found) and found[last][0] == "curve":
                last += 1
            before, after = found[index - 1], found[last % len(found)]  # (lines both: a run is every curve between two)
            steps += refit(sampled(found[index:last]), unit(before[2] - before[1]), unit(after[2] - after[1]), tolerance)
            index = last
        result.append((found[0][1], steps))
    return result


_letters = {}


def letter(coverage, weight=0.0):
    """A letter's outlines from its bitmap (remembered: the reconstruction is the slow part)."""
    key = (coverage.shape, coverage.tobytes(), weight)
    if key not in _letters:
        paths = smoothed(sharpen(outlines(reconstruct(coverage)), coverage), SMOOTH)
        if weight:  # (the weight is added to the finished outline, drawn large, and that is outlined again)
            paths = smoothed(squared(outlines(weighed(fill(paths, coverage.shape, DETAIL) > 0.5, weight), tidy=False)), SMOOTH)
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
