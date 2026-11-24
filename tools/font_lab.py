#!/usr/bin/env python3
"""Compare the maps' bitmap fonts with ways of redrawing them sharply.

Reads a font tag's own glyphs from ui.map and draws test phrases and single
characters with them, enlarged the way the game enlarges them, and again with
each candidate recipe for a display-resolution redraw. Writes one HTML page:
the original line, then one line per candidate, for every phrase, and one row
of tiles per character. Click the line or tile that looks most like the
original; the page lists the picks as text to paste back.

    python3 tools/font_lab.py --output build/font-lab/<new folder>
    python3 tools/font_lab.py --output ... --review    # only our own font: its weight, and each letter to flag
    python3 tools/font_lab.py --output ... --typeface Other-Bold.ttf --typeface 'Variable[wght].ttf@800'
    python3 tools/font_lab.py --output ... --characters RtC= --phrase "COOPERATIVE PLAY"    # seconds, not minutes

By default the candidates are the game as it draws the text now, the original
letter enlarged, and our own font (tools/og_font.py) at three weights. --recipes
picks others: as 0.6 drew it (shipped), tuned per letter (matched), cleaned
traces. Each --typeface adds another typeface, tuned per letter.

The menus' large titles are pictures in the maps, not text. The page ends with
each one beside the picture Upres draws in its place (port/assets/titles);
click a redraw that looks wrong to flag it.

Each candidate also gets a number: how much it differs from the original once
it is shrunk back to the Xbox's pixels, as a share of the original's ink.
Lower is closer. A recipe is a function in RECIPES; add one to try an idea.

Needs NumPy and Pillow (as tools/title_assets.py does) and game data in the
primary checkout. Nothing it draws from the maps is written into the repository.
"""
import argparse
import base64
import html
import io
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from hud_assets import XboxMap, decode_bitmap  # noqa: E402
from primary_checkout import PRIMARY  # noqa: E402

FONTS = ROOT / "port/assets/fonts"
TITLES = ROOT / "port/assets/titles"
PHRASES = [
    "COOPERATIVE PLAY", "SPLIT SCREEN", "Team Slayer Pro", "Edit Gametypes", "Capture the Flag",
    "A=SELECT  B=BACK", "Choose another to edit.", "PLAY AVATAR WAVY TYPE LT", "Rally Oddball illicit fjord",
    "0123456789 : . , ' - % = ?",
]
TEXT, GROUND, TILE_TEXT, TILE_GROUND = (77, 155, 255), (8, 22, 48), (236, 236, 236), (22, 22, 26)
PAD = 3  # empty logical pixels around a line
# The maps store a letter's pixels in 16 levels. They are evenly spaced shares of a pixel, 0 to 15
# fifteenths, stored through a curve that lifts the faint ones: this is each level's stored value.
LEVELS = [0, 104, 124, 140, 154, 167, 178, 189, 199, 208, 217, 225, 233, 240, 248, 255]


def shares(stored_levels):
    """Stored levels (0 to 1) as the share of each pixel the letter covers."""
    return np.interp(stored_levels * 255, LEVELS, np.arange(16) / 15).astype(np.float32)


def stored(covered):
    """The share of each pixel covered as the maps would store it (0 to 1)."""
    return (np.interp(covered, np.arange(16) / 15, LEVELS) / 255).astype(np.float32)


# ---------- the maps' fonts


class Glyph:
    def __init__(self, advance, origin_x, origin_y, coverage):
        self.advance, self.origin_x, self.origin_y, self.coverage = advance, origin_x, origin_y, coverage
        self.ink = ink_rectangle(coverage)


class MapFont:
    """A font tag: font_header and font_character in source/text."""

    def __init__(self, cache: XboxMap, name: str):
        self.name = name
        header = cache.read(cache.tags[("font", name)], 0x9C)
        self.ascending, self.descending, _, self.leading_width = struct.unpack_from("<hhhh", header, 4)
        count, characters = struct.unpack_from("<II", header, 0x7C)
        size, _, _, pixels = struct.unpack_from("<iiiI", header, 0x88)
        data = cache.read(pixels, size)
        self.glyphs = {}
        for index in range(count):
            code, advance, width, height, origin_x, origin_y, _, _, offset = struct.unpack(
                "<HhhhhhhHi", cache.read(characters + index * 20, 20))
            coverage = np.zeros((max(height, 0), max(width, 0)), np.float32)
            if width > 0 and height > 0 and 0 <= offset and offset + width * height <= len(data):
                coverage = np.frombuffer(data, np.uint8, width * height, offset).reshape(height, width) / np.float32(255)
            self.glyphs[code] = Glyph(advance, origin_x, origin_y, coverage)
        # the game sizes a substitute by the rows the capital H covers (hires_text_font_get)
        self.capital_rows = int(np.count_nonzero(self.glyphs[ord("H")].coverage.max(axis=1)))


def ink_edges(profile):
    """hires_ink_edges: the first and last inked position, each moved in by what its edge pixel lacks."""
    inked = np.nonzero(profile > 0)[0]
    if not len(inked):
        return None
    first, last = int(inked[0]), int(inked[-1])
    if first == last:
        return first + (1 - profile[first]) / 2, first + 1 - (1 - profile[first]) / 2
    return first + (1 - profile[first]), last + profile[last]


def ink_rectangle(coverage):
    """Where the ink lies, to a part of a pixel: left, top, right, bottom, or None for a blank."""
    if not coverage.size:
        return None
    columns, rows = ink_edges(coverage.max(axis=0)), ink_edges(coverage.max(axis=1))
    return (columns[0], rows[0], columns[1], rows[1]) if columns and rows else None


# ---------- drawing


def gaussian(image, sigma):
    radius = int(math.ceil(3 * sigma))
    kernel = np.exp(-np.arange(-radius, radius + 1) ** 2 / (2 * sigma * sigma)).astype(np.float32)
    kernel /= kernel.sum()
    padded = np.pad(image, radius)
    padded = np.lib.stride_tricks.sliding_window_view(padded, len(kernel), axis=1) @ kernel
    return np.lib.stride_tricks.sliding_window_view(padded, len(kernel), axis=0) @ kernel


def weigh(mask, shift):
    """Move every edge of a mask out by `shift` pixels (in for a negative one): bolder or lighter strokes.
    A square brush, so square corners stay square."""
    steps = int(round(shift))
    if not steps:
        return mask
    pad = abs(steps) + 2
    image = Image.fromarray((np.pad(mask, pad) * 255 + 0.5).astype(np.uint8), "L")
    brush = ImageFilter.MaxFilter(2 * steps + 1) if steps > 0 else ImageFilter.MinFilter(-2 * steps + 1)
    return np.asarray(image.filter(brush), np.float32) / 255


def weigh_round(mask, shift):
    """The same with a round brush (blur and threshold): it rounds corners."""
    if abs(shift) < 0.02:
        return mask
    sigma = max(1.5 * abs(shift), 1.0)
    pad = int(math.ceil(3 * sigma + abs(shift))) + 2
    blurred = gaussian(np.pad(mask, pad), sigma)
    level = 0.5 * (1 - math.erf(shift / (sigma * math.sqrt(2))))
    slope = math.exp(-shift * shift / (2 * sigma * sigma)) / (sigma * math.sqrt(2 * math.pi))
    return np.clip((blurred - level) / slope + 0.5, 0, 1).astype(np.float32)


def place(canvas, mask, source, target, scale):
    """Draw a mask so the rectangle `source` (mask pixels) lands on `target` (logical pixels) of a canvas
    that has `scale` pixels to the logical pixel. Overlapping ink keeps the larger coverage."""
    left, top, right, bottom = target
    if right - left <= 0 or bottom - top <= 0:
        return
    a = (source[2] - source[0]) / ((right - left) * scale)
    e = (source[3] - source[1]) / ((bottom - top) * scale)
    # the mask's whole extent on the canvas, clipped to it
    x0 = max(0, math.floor(left * scale - source[0] / a) - 1)
    y0 = max(0, math.floor(top * scale - source[1] / e) - 1)
    x1 = min(canvas.shape[1], math.ceil(left * scale + (mask.shape[1] - source[0]) / a) + 1)
    y1 = min(canvas.shape[0], math.ceil(top * scale + (mask.shape[0] - source[1]) / e) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    drawn = Image.fromarray(mask, "F").transform(
        (x1 - x0, y1 - y0), Image.AFFINE,
        (a, 0, (x0 - left * scale) * a + source[0], 0, e, (y0 - top * scale) * e + source[1]), resample=Image.BILINEAR)
    np.maximum(canvas[y0:y1, x0:x1], np.asarray(drawn), out=canvas[y0:y1, x0:x1])


class Outline:
    """A typeface file, drawn at `detail` pixels to the logical pixel with its capital H `capital` logical pixels tall."""

    def __init__(self, path: Path, capital: float, detail: int, weight: str = ""):
        self.label = path.stem.split("[")[0] + (" " + weight if weight else "")
        box = self.load(path, 1000, weight).getbbox("H", anchor="ls")
        self.font = self.load(path, capital * detail * 1000 / (box[3] - box[1]), weight)
        self.detail, self.cache = detail, {}

    @staticmethod
    def load(path, size, weight):
        font = ImageFont.truetype(str(path), size)
        if weight:  # a variable font: the weight axis as asked, the others as they are
            font.set_variation_by_axes([float(weight) if axis["name"] in ("Weight", b"Weight") else axis["default"]
                                        for axis in font.get_variation_axes()])
        return font

    def glyph(self, character: str):
        """The mask, where its ink lies in it, and that ink relative to the pen on the baseline, with the advance
        (the last two in logical pixels)."""
        if character not in self.cache:
            left, top, right, bottom = self.font.getbbox(character, anchor="ls")
            pad = 4
            image = Image.new("L", (max(right - left, 1) + 2 * pad, max(bottom - top, 1) + 2 * pad), 0)
            ImageDraw.Draw(image).text((pad - left, pad - top), character, font=self.font, anchor="ls", fill=255)
            mask = np.asarray(image, np.float32) / 255
            ink = ink_rectangle(mask)
            relative = None
            if ink:
                origin = (pad - left, pad - top)
                relative = tuple((ink[index] - origin[index % 2]) / self.detail for index in range(4))
            self.cache[character] = (mask, ink, relative, self.font.getlength(character) / self.detail)
        return self.cache[character]


def shrunk(mask, source, target, shape, detail=8):
    """A placed mask as the Xbox's pixels would show it: its coverage of each pixel of an original bitmap
    (`target` in that bitmap's pixels), with one more pixel all around so ink outside it counts."""
    canvas = np.zeros(((shape[0] + 2) * detail, (shape[1] + 2) * detail), np.float32)
    place(canvas, mask, source, tuple(value + 1 for value in target), detail)
    return canvas.reshape(shape[0] + 2, detail, shape[1] + 2, detail).mean(axis=(1, 3))


def difference(drawn, coverage):
    """How far a shrunk redraw, stored as the maps store a letter, is from the original bitmap, as a share
    of the original's ink."""
    return float(np.abs(stored(drawn) - np.pad(coverage, 1)).sum() / max(coverage.sum(), 1e-6))


# ---------- recipes: each returns (mask, source rectangle, target rectangle relative to the bitmap's corner)
# for one glyph, or None to draw nothing. `detail` is the mask pixels to a logical pixel.


def recipe_shipped(font, glyph, character, outline, detail, state):
    """0.6: capital heights matched, the letter centred in its slot."""
    mask, ink, relative, advance = outline.glyph(character)
    if not ink:
        return None
    pen = glyph.origin_x + (glyph.advance - advance) / 2
    return mask, ink, (pen + relative[0], glyph.origin_y + relative[1], pen + relative[2], glyph.origin_y + relative[3])


def recipe_fit(font, glyph, character, outline, detail, state):
    """0.7 now: the letter is stretched to fill the space the original's ink takes."""
    mask, ink, _, _ = outline.glyph(character)
    return (mask, ink, glyph.ink) if ink and glyph.ink else None


def tuned(font, glyph, character, outline, detail, state, tune_rectangle):
    """Stroke weight, and optionally the rectangle, chosen to differ least from the original's pixels."""
    key = (font.name, character, id(outline), tune_rectangle)
    if key not in state:
        mask, ink, _, _ = outline.glyph(character)
        best = None
        if ink and glyph.ink:
            shape = glyph.coverage.shape
            for weight in np.arange(-0.5, 0.51, 0.125):
                heavier = weigh(mask, weight * detail)
                source = ink_rectangle(heavier)
                if not source:
                    continue
                target = list(glyph.ink)
                error = difference(shrunk(heavier, source, target, shape), glyph.coverage)
                for _ in range(2 if tune_rectangle else 0):
                    for edge in range(4):
                        for delta in np.arange(-0.75, 0.76, 0.125):
                            trial = list(target)
                            trial[edge] = glyph.ink[edge] + delta
                            if trial[2] - trial[0] < 0.5 or trial[3] - trial[1] < 0.5:
                                continue
                            trial_error = difference(shrunk(heavier, source, trial, shape), glyph.coverage)
                            if trial_error < error:
                                error, target = trial_error, trial
                if best is None or error < best[0]:
                    best = (error, heavier, source, tuple(target), float(weight))
        state[key] = best
    best = state[key]
    return best[1:4] if best else None


def recipe_weight(font, glyph, character, outline, detail, state):
    """The letter fills the original's space, with its strokes made as heavy as the original's."""
    return tuned(font, glyph, character, outline, detail, state, False)


def recipe_matched(font, glyph, character, outline, detail, state):
    """Place, size and stroke weight tuned for each letter against the original's pixels."""
    return tuned(font, glyph, character, outline, detail, state, True)


def traced(glyph, detail, edge, level, smooth):
    if not glyph.ink:
        return None
    pad = 2
    padded = np.pad(glyph.coverage, pad)
    if smooth:
        padded = gaussian(padded, smooth).astype(np.float32)
    height, width = padded.shape
    enlarged = np.asarray(Image.fromarray(padded, "F").resize((width * detail, height * detail), Image.BICUBIC))
    mask = np.clip((enlarged - level) * (detail / edge) + 0.5, 0, 1).astype(np.float32)
    return mask, (0, 0, width * detail, height * detail), (-pad, -pad, width - pad, height - pad)


def level_loops(field, level=0.5):
    """The closed outlines where a field of samples at pixel centres crosses a level (marching squares), as
    lists of points with the ink on one side throughout."""
    field = np.pad(field, 1)
    ink = field > level
    after = {}

    def crossing(p, q):
        p, q = min(p, q), max(p, q)
        a, b = field[p[1], p[0]], field[q[1], q[0]]
        t = (level - a) / (b - a)
        return round(p[0] + (q[0] - p[0]) * t - 1, 6), round(p[1] + (q[1] - p[1]) * t - 1, 6)

    for y in range(field.shape[0] - 1):
        for x in range(field.shape[1] - 1):
            corners = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
            inked = [bool(ink[corner[1], corner[0]]) for corner in corners]
            edges = [index for index in range(4) if inked[index] != inked[(index + 1) % 4]]  # edge i: corner i to i+1
            if len(edges) == 2:
                cuts = [(edges[0], edges[1], inked.index(True), True)]
            elif len(edges) == 4:  # a saddle: the middle says which two corners are joined
                middle = bool(field[y:y + 2, x:x + 2].mean() > level)
                cuts = [((index - 1) % 4, index, index, not middle) for index in range(4) if inked[index] != middle]
            else:
                continue
            for first, second, corner, corner_inked in cuts:
                p = crossing(corners[first], corners[(first + 1) % 4])
                q = crossing(corners[second], corners[(second + 1) % 4])
                side = (q[0] - p[0]) * (corners[corner][1] - 1 - p[1]) - (q[1] - p[1]) * (corners[corner][0] - 1 - p[0])
                if (side > 0) != corner_inked:
                    p, q = q, p
                after[p] = q
    loops = []
    while after:
        start = next(iter(after))
        loop, point = [start], after.pop(start)
        while point != start and point in after:
            loop.append(point)
            point = after.pop(point)
        if len(loop) >= 3:
            loops.append(np.array(loop))
    return loops


def breakpoints(loop, tolerance):
    """The fewest points of an outline that keep every other point within the tolerance of the lines between
    them (Ramer-Douglas-Peucker), as indices."""
    count = len(loop)
    far = int(np.argmax(((loop - loop[0]) ** 2).sum(axis=1)))
    keep = {0, far}

    def split(a, b):
        if b - a < 2:
            return
        p, q = loop[a % count], loop[b % count]
        chain = loop[np.arange(a + 1, b) % count]
        along = q - p
        length = math.hypot(along[0], along[1])
        if length > 1e-9:
            distance = np.abs((chain[:, 0] - p[0]) * along[1] - (chain[:, 1] - p[1]) * along[0]) / length
        else:
            distance = np.hypot(chain[:, 0] - p[0], chain[:, 1] - p[1])
        worst = int(np.argmax(distance))
        if distance[worst] > tolerance:
            keep.add((a + 1 + worst) % count)
            split(a, a + 1 + worst)
            split(a + 1 + worst, b)

    split(0, far)
    split(far, count)
    return sorted(keep)


def clean_outline(loop, tolerance, corner=55.0, reach=2.0):
    """An outline redrawn from its own points: a straight line fitted to each run between breakpoints, the
    lines met at sharp corners, and gentle turns rounded into curves. Returns the points to fill."""
    count, cuts = len(loop), breakpoints(loop, tolerance)
    if len(cuts) < 3:
        return loop
    lines = []
    for index, a in enumerate(cuts):
        b = cuts[(index + 1) % len(cuts)]
        run = loop[np.arange(a, (b if b > a else b + count) + 1) % count]
        inner = run[1:-1] if len(run) >= 4 else run  # (the ends are where the next line's corner was cut off)
        centre, along = inner.mean(axis=0), run[-1] - run[0]
        if len(inner) >= 3:
            axis = np.linalg.svd(inner - centre)[2][0]
            along = axis if axis @ along >= 0 else -axis
        lines.append((centre, along / max(math.hypot(along[0], along[1]), 1e-9)))
    vertices = []
    for index, a in enumerate(cuts):
        (c1, d1), (c2, d2) = lines[index - 1], lines[index]
        turn = d1[0] * d2[1] - d1[1] * d2[0]
        vertex = (c1 + d1 * ((loop[a] - c1) @ d1) + c2 + d2 * ((loop[a] - c2) @ d2)) / 2
        if abs(turn) > 0.2:
            met = c1 + d1 * (((c2[0] - c1[0]) * d2[1] - (c2[1] - c1[1]) * d2[0]) / turn)
            if math.hypot(met[0] - loop[a][0], met[1] - loop[a][1]) < 0.8:
                vertex = met
        vertices.append(vertex)
    points = []
    for index, here in enumerate(vertices):
        into, out = here - vertices[index - 1], vertices[(index + 1) % len(vertices)] - here
        before, after = math.hypot(into[0], into[1]), math.hypot(out[0], out[1])
        if before < 1e-6 or after < 1e-6:
            continue
        turn = abs(math.degrees(math.atan2(into[0] * out[1] - into[1] * out[0], into @ out)))
        if turn >= corner or turn < 4 or (turn >= 30 and min(before, after) >= 4):
            points.append(here)
            continue
        start, end = here - into / before * min(before / 2, reach), here + out / after * min(after / 2, reach)
        for t in np.linspace(0, 1, 9):
            points.append((1 - t) ** 2 * start + 2 * (1 - t) * t * here + t * t * end)
    return np.array(points)


def cleaned(glyph, detail, tolerance, level=0.5):
    """The original letter's own outline, cleaned, filled at `detail` pixels to the logical pixel."""
    if not glyph.ink:
        return None
    pad, over = 2, 4
    rows, columns = glyph.coverage.shape
    size = ((columns + 2 * pad) * detail * over, (rows + 2 * pad) * detail * over)
    filled = np.zeros(size[::-1], bool)
    for loop in level_loops(glyph.coverage, level):
        path = clean_outline(loop, tolerance)
        if len(path) < 3:
            continue
        image = Image.new("1", size, 0)
        # (a sample is the middle of its pixel)
        ImageDraw.Draw(image).polygon([((x + 0.5 + pad) * detail * over, (y + 0.5 + pad) * detail * over) for x, y in path], fill=1)
        filled ^= np.asarray(image, bool)
    mask = filled.reshape(size[1] // over, over, size[0] // over, over).mean(axis=(1, 3)).astype(np.float32)
    return mask, (0, 0, mask.shape[1], mask.shape[0]), (-pad, -pad, columns + pad, rows + pad)


def recipe_clean(font, glyph, character, outline, detail, state):
    """The original letter's own outline with straight runs made straight, corners sharp and turns smooth."""
    return cleaned(glyph, detail, 0.3)


def recipe_clean_tight(font, glyph, character, outline, detail, state):
    """The same, following the original's pixels more closely."""
    return cleaned(glyph, detail, 0.2)


def recipe_clean_loose(font, glyph, character, outline, detail, state):
    """The same, straightening more."""
    return cleaned(glyph, detail, 0.45)


def ours(glyph, detail, weight):
    """Our own font's letter (tools/og_font.py): its outline filled at `detail` pixels to the pixel."""
    import og_font
    if not glyph.ink:
        return None
    mask = og_font.fill(og_font.letter(glyph.coverage, weight), glyph.coverage.shape, detail)
    rows, columns = glyph.coverage.shape
    return mask, (0, 0, mask.shape[1], mask.shape[0]), (-og_font.PAD, -og_font.PAD, columns + og_font.PAD, rows + og_font.PAD)


def recipe_ours(font, glyph, character, outline, detail, state):
    """Our font: the letter's true shape, rebuilt from the original's pixels."""
    return ours(glyph, detail, 0.0)


def recipe_ours_15(font, glyph, character, outline, detail, state):
    """Our font with every edge 0.15 of a pixel further out."""
    return ours(glyph, detail, 0.15)


def recipe_ours_30(font, glyph, character, outline, detail, state):
    """Our font with every edge 0.3 of a pixel further out."""
    return ours(glyph, detail, 0.3)


def recipe_trace(font, glyph, character, outline, detail, state):
    """The original letter itself, enlarged with a smooth curve and given a sharp edge."""
    return traced(glyph, detail, 1.5, 0.5, 0)


def recipe_trace_smooth(font, glyph, character, outline, detail, state):
    """The original letter enlarged, smoothed a little first: rounder, fewer bumps."""
    return traced(glyph, detail, 1.5, 0.5, 0.45)


def recipe_trace_bold(font, glyph, character, outline, detail, state):
    """The original letter enlarged with its soft edge counted as ink: slightly heavier."""
    return traced(glyph, detail, 1.5, 0.4, 0)


RECIPES = [
    ("shipped", "0.6 build", recipe_shipped),
    ("fit", "0.7 now", recipe_fit),
    ("weight", "fit + weight", recipe_weight),
    ("matched", "tuned per letter", recipe_matched),
    ("trace", "original, sharpened", recipe_trace),
    ("trace-smooth", "original, enlarged", recipe_trace_smooth),
    ("trace-bold", "original, heavier", recipe_trace_bold),
    ("trace-clean-tight", "clean outline, tight", recipe_clean_tight),
    ("trace-clean", "clean outline", recipe_clean),
    ("trace-clean-loose", "clean outline, loose", recipe_clean_loose),
    ("trace-ours", "our font", recipe_ours),
    ("trace-ours-15", "our font +0.15", recipe_ours_15),
    ("trace-ours-30", "our font +0.3", recipe_ours_30),
]
DEFAULT_RECIPES = "fit,trace-smooth,trace-ours,trace-ours-15,trace-ours-30"


# ---------- lines and pictures


def original_line(font, text, detail):
    """The original glyphs at the Xbox's pixels, enlarged with the linear filter the game draws them with."""
    width = sum(font.glyphs[ord(c)].advance for c in text if ord(c) in font.glyphs) + 2 * PAD
    height = font.ascending + font.descending + 2 * PAD
    canvas = np.zeros((height, width), np.float32)
    pen = PAD
    for character in text:
        glyph = font.glyphs.get(ord(character))
        if not glyph:
            continue
        x, y = pen - glyph.origin_x, PAD + font.ascending - glyph.origin_y
        rows, columns = glyph.coverage.shape
        y0, x0 = max(y, 0), max(x, 0)
        y1, x1 = min(y + rows, height), min(x + columns, width)
        if y1 > y0 and x1 > x0:
            np.maximum(canvas[y0:y1, x0:x1], glyph.coverage[y0 - y:y1 - y, x0 - x:x1 - x], out=canvas[y0:y1, x0:x1])
        pen += glyph.advance
    return np.asarray(Image.fromarray(canvas, "F").resize((width * detail, height * detail), Image.BILINEAR))


def recipe_line(font, text, recipe, outline, detail, state):
    width = sum(font.glyphs[ord(c)].advance for c in text if ord(c) in font.glyphs) + 2 * PAD
    height = font.ascending + font.descending + 2 * PAD
    canvas = np.zeros((height * detail, width * detail), np.float32)
    pen = PAD
    for character in text:
        glyph = font.glyphs.get(ord(character))
        if not glyph:
            continue
        drawn = recipe(font, glyph, character, outline, detail, state) if character != " " else None
        if drawn:
            x, y = pen - glyph.origin_x, PAD + font.ascending - glyph.origin_y
            target = (x + drawn[2][0], y + drawn[2][1], x + drawn[2][2], y + drawn[2][3])
            place(canvas, drawn[0], drawn[1], target, detail)
        pen += glyph.advance
    return canvas


def picture(ink, detail, shrink, text, ground, shadow):
    """Compose a line: the ground, the shadow one logical pixel down and right, the ink; as PNG bytes."""
    image = np.empty(ink.shape + (3,), np.float32)
    image[:] = ground
    if shadow:
        shade = np.zeros_like(ink)
        shade[detail:, detail:] = ink[:-detail, :-detail]
        image *= (1 - shade * shadow)[..., None]
    image += (np.array(text, np.float32) - image) * ink[..., None]
    return png(image, shrink)


def overlay(original, ink, shrink):
    """Original in red, redraw in cyan: white where they agree."""
    return png(np.stack([original, ink, ink], axis=-1) * 255, shrink)


def png(image, shrink):
    rows, columns = image.shape[0] // shrink * shrink, image.shape[1] // shrink * shrink
    image = image[:rows, :columns].reshape(rows // shrink, shrink, columns // shrink, shrink, 3).mean(axis=(1, 3))
    data = io.BytesIO()
    # (a line is a blend of two or three colours: 64 palette entries hold it, in a fraction of the bytes)
    Image.fromarray(np.clip(image + 0.5, 0, 255).astype(np.uint8), "RGB").quantize(64, dither=Image.Dither.NONE).save(
        data, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii")


def title_pictures(cache, scale):
    """Each menu title as the maps have it, enlarged, and as port/assets/titles redraws it, cut to the text."""
    listing = json.loads((TITLES / "titles.json").read_text())
    ground = np.array(GROUND, np.float32)
    titles = []
    for asset in listing["assets"]:
        size = (asset["width"] * scale, asset["height"] * scale)
        original = Image.fromarray(decode_bitmap(cache.bitmap_group(asset["tag"])["bitmaps"][asset["bitmap"]]), "RGBA")
        redraw = Image.open(TITLES / (asset["name"] + ".png")).convert("RGBA")
        # (colour multiplied by alpha before resizing, so transparent texels do not tint the edges)
        pair = [np.asarray(original.convert("RGBa").resize(size, Image.BILINEAR), np.float32),
                np.asarray(redraw.convert("RGBa").resize(size, Image.LANCZOS), np.float32)]
        inked = np.nonzero(np.maximum(pair[0][..., 3], pair[1][..., 3]) > 24)
        if not len(inked[0]):
            continue
        top, bottom = max(inked[0].min() - 2 * scale, 0), min(inked[0].max() + 2 * scale, size[1])
        left, right = max(inked[1].min() - 2 * scale, 0), min(inked[1].max() + 2 * scale, size[0])
        images = [png(ground * (1 - image[top:bottom, left:right, 3:] / 255) + image[top:bottom, left:right, :3], 1)
                  for image in pair]
        titles.append({"text": asset["text"], "name": asset["name"], "original": images[0], "redraw": images[1],
                       "width": int(right - left) // 2, "height": int(bottom - top) // 2})
    return listing["font"], titles


def glyph_error(font, character, recipe, outline, detail, state):
    glyph = font.glyphs[ord(character)]
    drawn = recipe(font, glyph, character, outline, detail, state)
    if not drawn or not glyph.ink:
        return None
    return difference(shrunk(drawn[0], drawn[1], drawn[2], glyph.coverage.shape), glyph.coverage)


PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Font lab</title>
<style>
 body { background: #101114; color: #d8dae0; font: 14px/1.4 -apple-system, system-ui, sans-serif; margin: 0 0 190px; }
 header, section { padding: 12px 20px; } h1 { font-size: 20px; margin: 0 0 6px; } h2 { font-size: 16px; margin: 26px 0 8px; }
 h3 { font-size: 13px; margin: 18px 0 4px; color: #9aa0ad; font-weight: 600; } p { margin: 4px 0; max-width: 900px; }
 .line { display: flex; align-items: center; gap: 10px; padding: 2px 6px; border: 2px solid transparent; border-radius: 6px;
   width: max-content; } .line.pick { cursor: pointer; } .line.pick:hover { border-color: #3a4152; }
 .line.picked, .tiles button.picked { border-color: #ffd24a !important; background: #2a2613; }
 .line.flagged, .tiles button.flagged { border-color: #ff5d5d !important; background: #2e1414; }
 #notes { flex: 0.6; }
 .line.original { position: sticky; top: 0; z-index: 1; background: #101114; border-bottom-color: #2c3140; border-radius: 0; }
 .label { width: 190px; flex: none; color: #9aa0ad; font-size: 12px; } .label b { color: #d8dae0; font-weight: 600; }
 img { display: block; image-rendering: auto; }
 table { border-collapse: collapse; } th { font-size: 11px; color: #9aa0ad; font-weight: 600; padding: 2px 6px; text-align: left;
   position: sticky; top: 0; background: #101114; } td { padding: 1px 3px; vertical-align: middle; }
 .tiles button { all: unset; display: block; border: 2px solid transparent; border-radius: 6px; padding: 2px; cursor: pointer; }
 .tiles button:hover { border-color: #3a4152; } .tiles small { display: block; text-align: center; color: #70778a; font-size: 10px; }
 .tiles td.original button { cursor: default; } .character { font: 600 15px ui-monospace, monospace; color: #9aa0ad; padding-right: 8px; }
 footer { position: fixed; left: 0; right: 0; bottom: 0; background: #181a20; border-top: 1px solid #2c3140; padding: 8px 20px;
   display: flex; gap: 12px; align-items: flex-start; } textarea { flex: 1; height: 150px; background: #0c0d10; color: #d8dae0;
   border: 1px solid #2c3140; border-radius: 6px; font: 12px/1.4 ui-monospace, monospace; padding: 6px; }
 footer button, header label { background: #2a3040; color: #e8eaf0; border: 1px solid #3a4152; border-radius: 6px; padding: 6px 12px;
   font: inherit; cursor: pointer; } header label { display: inline-block; margin-top: 8px; }
</style>
<header>
 <h1>Font lab: original letters against sharp redraws</h1>
 <p>Under each original line is the same text drawn by each candidate. Click the candidate that looks most like the
 original; in the character tables, click the best tile for each character. The number is how much a candidate differs
 from the original once shrunk back to the Xbox's pixels, as a percentage of the original's ink: lower is closer.
 <b>Shift-click</b> a line or tile that has something wrong with it to flag it in red, and say what in the notes box.
 Your picks, flags and notes collect at the bottom. Copy them and paste them into the chat.</p>
 <label><input type="checkbox" id="overlay"> Show character tiles as differences (red: only in the original, cyan: only
 in the redraw, white: both)</label>
</header>
<main id="main"></main>
<footer><textarea id="picks" readonly></textarea><textarea id="notes" placeholder="Notes: what looks wrong, and where"></textarea><div><button id="copy">Copy picks</button><br><br>
<button id="clear">Clear picks</button></div></footer>
<script>
const DATA = __DATA__;
const main = document.getElementById("main"), box = document.getElementById("picks");
const notes = document.getElementById("notes");
let picks = {}, flags = {};
try { picks = JSON.parse(localStorage.getItem(DATA.run) || "{}"); flags = JSON.parse(localStorage.getItem(DATA.run + ":flags") || "{}");
  notes.value = localStorage.getItem(DATA.run + ":notes") || ""; } catch (error) {}
function save() {
  try { localStorage.setItem(DATA.run, JSON.stringify(picks)); localStorage.setItem(DATA.run + ":flags", JSON.stringify(flags));
    localStorage.setItem(DATA.run + ":notes", notes.value); } catch (error) {}
  const lines = ["Font lab picks (" + DATA.run + ")"];
  for (const font of DATA.fonts.concat(DATA.titles.length ? [{name: "menu titles"}] : [])) {
    const mine = picks[font.name] || {}, tally = {};
    for (const key in mine) tally[mine[key]] = (tally[mine[key]] || 0) + 1;
    lines.push(font.name + "  totals: " + (Object.keys(tally).map(k => k + " x" + tally[k]).join(", ") || "none"));
    for (const key in mine) lines.push("  " + key + " -> " + mine[key]);
    for (const key in flags[font.name] || {}) lines.push("  FLAGGED " + key);
  }
  if (notes.value.trim()) lines.push("Notes: " + notes.value.trim());
  box.value = lines.join("\\n");
  document.querySelectorAll("[data-key]").forEach(node => {
    const mine = picks[node.dataset.font] || {};
    node.classList.toggle("picked", mine[node.dataset.key] === node.dataset.recipe);
    node.classList.toggle("flagged", !!(flags[node.dataset.font] || {})[node.dataset.key + " in " + node.dataset.recipe]);
  });
}
function pick(node, event) {
  if (event && event.shiftKey) {
    const marked = flags[node.dataset.font] = flags[node.dataset.font] || {}, key = node.dataset.key + " in " + node.dataset.recipe;
    if (marked[key]) delete marked[key]; else marked[key] = true;
    save();
    return;
  }
  const mine = picks[node.dataset.font] = picks[node.dataset.font] || {};
  if (mine[node.dataset.key] === node.dataset.recipe) delete mine[node.dataset.key]; else mine[node.dataset.key] = node.dataset.recipe;
  save();
}
function element(tag, attributes, parent) {
  const node = document.createElement(tag);
  for (const key in attributes) { if (key === "text") node.textContent = attributes[key]; else if (key in node) node[key] = attributes[key]; else node.setAttribute(key, attributes[key]); }
  if (parent) parent.appendChild(node);
  return node;
}
for (const font of DATA.fonts) {
  const section = element("section", {}, main);
  element("h2", {text: font.name + " (drawn with " + font.file + ")"}, section);
  for (const phrase of font.phrases) {
    element("h3", {text: phrase.text}, section);
    const block = element("div", {}, section);  // the original line stays in view while this block scrolls past
    phrase.lines.forEach((line, index) => {
      const row = element("div", {className: "line" + (index ? " pick" : " original")}, block);
      const label = element("div", {className: "label"}, row);
      element("b", {text: index ? DATA.recipes[index - 1][1] : "ORIGINAL"}, label);
      if (index) { element("span", {text: "  " + line.error + "%"}, label);
        row.dataset.font = font.name; row.dataset.key = 'phrase "' + phrase.text + '"'; row.dataset.recipe = DATA.recipes[index - 1][0];
        row.onclick = event => pick(row, event); }
      element("img", {src: line.image, width: line.width, height: line.height}, row);
    });
  }
  element("h3", {text: "Characters"}, section);
  const table = element("table", {className: "tiles"}, section), head = element("tr", {}, table);
  element("th", {}, head); element("th", {text: "ORIGINAL"}, head);
  for (const recipe of DATA.recipes) element("th", {text: recipe[1]}, head);
  for (const character of font.characters) {
    const row = element("tr", {}, table);
    element("td", {className: "character", text: character.text}, row);
    character.tiles.forEach((tile, index) => {
      const cell = element("td", {className: index ? "" : "original"}, row), button = element("button", {}, cell);
      const image = element("img", {src: tile.image, width: character.width, height: character.height}, button);
      image.dataset.plain = tile.image; image.dataset.overlay = tile.overlay || tile.image;
      if (index) { element("small", {text: tile.error + "%"}, button);
        button.dataset.font = font.name; button.dataset.key = "character " + character.text; button.dataset.recipe = DATA.recipes[index - 1][0];
        button.onclick = event => pick(button, event); }
    });
  }
}
if (DATA.titles.length) {
  const section = element("section", {}, main);
  element("h2", {text: "Menu titles (pictures in the maps, redrawn with " + DATA.titleFont + ")"}, section);
  element("p", {text: "These are not text: each is one picture. Click a redraw that looks wrong to flag it."}, section);
  for (const title of DATA.titles) {
    element("h3", {text: title.text}, section);
    const block = element("div", {}, section);
    [["ORIGINAL", title.original], ["0.7 now", title.redraw]].forEach((line, index) => {
      const row = element("div", {className: "line" + (index ? " pick" : "")}, block);
      element("b", {text: line[0]}, element("div", {className: "label"}, row));
      element("img", {src: line[1], width: title.width, height: title.height}, row);
      if (index) { row.dataset.font = "menu titles"; row.dataset.key = 'title "' + title.text + '" (' + title.name + ")";
        row.dataset.recipe = "needs work"; row.onclick = event => pick(row, event); }
    });
  }
}
document.getElementById("overlay").onchange = event => document.querySelectorAll("img[data-plain]").forEach(image => {
  image.src = event.target.checked ? image.dataset.overlay : image.dataset.plain; });
document.getElementById("copy").onclick = () => { box.select(); try { navigator.clipboard.writeText(box.value); } catch (error) { document.execCommand("copy"); } };
document.getElementById("clear").onclick = () => { picks = {}; flags = {}; save(); };
notes.oninput = save;
save();
</script>
"""


REVIEW_PHRASES = ["COOPERATIVE PLAY", "Team Slayer Pro", "Choose another to edit.", "A=SELECT  B=BACK", "0123456789 : . , ' - % = ?"]
REVIEW_WEIGHTS = [("true weight", 0.0), ("+0.15 px", 0.15), ("+0.3 px", 0.3)]
REVIEW_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Font review</title>
<style>
 body { background: #101114; color: #d8dae0; font: 14px/1.45 -apple-system, system-ui, sans-serif; margin: 0 0 170px; }
 header, section { padding: 12px 20px; } h1 { font-size: 20px; margin: 0 0 6px; } h2 { font-size: 17px; margin: 22px 0 2px; }
 h3 { font-size: 13px; margin: 16px 0 6px; color: #9aa0ad; font-weight: 600; } p { margin: 4px 0; max-width: 860px; }
 .line { display: flex; align-items: center; gap: 10px; padding: 2px 6px; border: 2px solid transparent; border-radius: 6px; width: max-content; }
 .line.pick { cursor: pointer; } .line.pick:hover, .letter:hover { border-color: #3a4152; }
 .line.picked { border-color: #ffd24a; background: #2a2613; }
 .label { width: 110px; flex: none; color: #9aa0ad; font-size: 12px; } img { display: block; }
 .phrase { margin-bottom: 14px; } .letters { display: flex; flex-wrap: wrap; gap: 6px; }
 .letter { display: flex; gap: 2px; border: 2px solid transparent; border-radius: 6px; padding: 2px; cursor: pointer; background: #16171b; }
 .letter.flagged { border-color: #ff5d5d; background: #2e1414; }
 footer { position: fixed; left: 0; right: 0; bottom: 0; background: #181a20; border-top: 1px solid #2c3140; padding: 8px 20px;
   display: flex; gap: 12px; align-items: flex-start; } textarea { flex: 1; height: 130px; background: #0c0d10; color: #d8dae0;
   border: 1px solid #2c3140; border-radius: 6px; font: 12px/1.4 ui-monospace, monospace; padding: 6px; }
 footer button { background: #2a3040; color: #e8eaf0; border: 1px solid #3a4152; border-radius: 6px; padding: 6px 12px; font: inherit; cursor: pointer; }
</style>
<header>
 <h1>Font review</h1>
 <p>Two things to decide for each font. <b>1.</b> Click the line whose weight reads most like the original. <b>2.</b> Click any
 letter that looks wrong; each pair is the original on the left and our font on the right, at the weight you picked.
 Say what is wrong in the notes box, then copy and paste the result into the chat.</p>
</header>
<main id="main"></main>
<footer><textarea id="result" readonly></textarea><textarea id="notes" placeholder="Notes: what looks wrong, and where"></textarea>
<div><button id="copy">Copy</button><br><br><button id="clear">Clear</button></div></footer>
<script>
const DATA = __DATA__;
const main = document.getElementById("main"), result = document.getElementById("result"), notes = document.getElementById("notes");
let state = {weights: {}, flags: {}};
try { state = JSON.parse(localStorage.getItem(DATA.run) || "null") || state; notes.value = localStorage.getItem(DATA.run + ":notes") || ""; } catch (error) {}
function element(tag, attributes, parent) {
  const node = document.createElement(tag);
  for (const key in attributes) { if (key === "text") node.textContent = attributes[key]; else node[key] = attributes[key]; }
  if (parent) parent.appendChild(node);
  return node;
}
function shown(font) { return font.name in state.weights ? state.weights[font.name] : 1; }
function refresh() {
  try { localStorage.setItem(DATA.run, JSON.stringify(state)); localStorage.setItem(DATA.run + ":notes", notes.value); } catch (error) {}
  const lines = ["Font review (" + DATA.run + ")"];
  for (const font of DATA.fonts) {
    const flagged = Object.keys(state.flags[font.name] || {});
    lines.push(font.name + ": weight " + (font.name in state.weights ? DATA.weights[state.weights[font.name]] : "not picked") +
      "; letters flagged: " + (flagged.length ? flagged.join(" ") : "none"));
  }
  if (notes.value.trim()) lines.push("Notes: " + notes.value.trim());
  result.value = lines.join("\\n");
  document.querySelectorAll(".line.pick").forEach(node => node.classList.toggle("picked", state.weights[node.dataset.font] === +node.dataset.weight));
  document.querySelectorAll(".letter").forEach(node => {
    node.classList.toggle("flagged", !!(state.flags[node.dataset.font] || {})[node.dataset.letter]);
    const font = DATA.fonts[+node.dataset.index];
    node.lastChild.src = font.letters[+node.dataset.at].ours[shown(font)];
  });
}
DATA.fonts.forEach((font, index) => {
  const section = element("section", {}, main);
  element("h2", {text: font.title}, section);
  element("p", {text: font.note}, section);
  element("h3", {text: "1. Weight: click the line that reads most like the original"}, section);
  for (const phrase of font.phrases) {
    const block = element("div", {className: "phrase"}, section);
    const first = element("div", {className: "line"}, block);
    element("div", {className: "label", text: "ORIGINAL"}, first);
    element("img", {src: phrase.original, width: phrase.width, height: phrase.height}, first);
    phrase.lines.forEach((image, weight) => {
      const row = element("div", {className: "line pick"}, block);
      row.dataset.font = font.name; row.dataset.weight = weight;
      element("div", {className: "label", text: DATA.weights[weight]}, row);
      element("img", {src: image, width: phrase.width, height: phrase.height}, row);
      row.onclick = () => { if (state.weights[font.name] === weight) delete state.weights[font.name]; else state.weights[font.name] = weight; refresh(); };
    });
  }
  element("h3", {text: "2. Letters: click any that looks wrong (original left, ours right)"}, section);
  const grid = element("div", {className: "letters"}, section);
  font.letters.forEach((letter, at) => {
    const pair = element("div", {className: "letter", title: letter.text}, grid);
    pair.dataset.font = font.name; pair.dataset.letter = letter.text; pair.dataset.index = index; pair.dataset.at = at;
    element("img", {src: letter.original, width: letter.width, height: letter.height}, pair);
    element("img", {src: letter.ours[1], width: letter.width, height: letter.height}, pair);
    pair.onclick = () => { const mine = state.flags[font.name] = state.flags[font.name] || {};
      if (mine[letter.text]) delete mine[letter.text]; else mine[letter.text] = true; refresh(); };
  });
});
document.getElementById("copy").onclick = () => { result.select(); try { navigator.clipboard.writeText(result.value); } catch (error) { document.execCommand("copy"); } };
document.getElementById("clear").onclick = () => { state = {weights: {}, flags: {}}; refresh(); };
notes.oninput = refresh;
refresh();
</script>
"""
REVIEW_NOTES = {
    "ui\\large_ui": ("Large menu font", "Menu lists and buttons. The in-game message font (ui\\interstate) has these same letters "
                     "set one pixel closer together, so reviewing this covers both."),
    "ui\\small_ui": ("Small menu font", "Descriptions, legends and settings rows."),
}


def review(args, cache):
    """The page for settling our own font: only its weight and its letters, beside the original."""
    # (pictures hold twice the pixels they are shown at, for sharp screens; letters are shown twice as large as phrases)
    detail, close = args.scale * 2, args.scale * 4
    recipes = [recipe_ours, recipe_ours_15, recipe_ours_30]
    data = {"run": args.output.name, "weights": [label for label, _ in REVIEW_WEIGHTS], "fonts": []}
    for name in filter(None, args.fonts.split(",")):
        font = MapFont(cache, name)
        title, note = REVIEW_NOTES.get(name, (name, ""))
        entry = {"name": name, "title": title + " (" + name + ")", "note": note, "phrases": [], "letters": []}
        for text in args.phrase or REVIEW_PHRASES:
            original = original_line(font, text, detail)
            entry["phrases"].append({
                "original": picture(original, detail, 1, TEXT, GROUND, 1.0),
                "lines": [picture(recipe_line(font, text, recipe, None, detail, {}), detail, 1, TEXT, GROUND, 0.5) for recipe in recipes],
                "width": original.shape[1] // 2, "height": original.shape[0] // 2})
        for character in args.characters or "".join(chr(code) for code in range(33, 127) if code in font.glyphs):
            original = original_line(font, character, close)
            entry["letters"].append({
                "text": character, "original": picture(original, close, 1, TILE_TEXT, TILE_GROUND, 0),
                "ours": [picture(recipe_line(font, character, recipe, None, close, {}), close, 1, TILE_TEXT, TILE_GROUND, 0)
                         for recipe in recipes],
                "width": original.shape[1] // 2, "height": original.shape[0] // 2})
        data["fonts"].append(entry)
        print(f"{name}: {len(entry['phrases'])} phrases, {len(entry['letters'])} letters")
    args.output.mkdir(parents=True)
    page = args.output / "index.html"
    page.write_text(REVIEW_PAGE.replace("__DATA__", json.dumps(data).replace("</", "<\\/")))
    print(f"Page: {page} ({page.stat().st_size // 1024} KB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", action="store_true", help="Write the short page for settling our own font: its "
                        "weight against the original on a few phrases, and each letter beside the original to flag. "
                        "Covers the large and small fonts unless --fonts says otherwise")
    parser.add_argument("--output", type=Path, required=True, help="A new folder for index.html")
    parser.add_argument("--fonts", default="ui\\large_ui,ui\\small_ui,ui\\interstate",
                        help="Font tags, comma-separated; '' for none. The maps have these three and the console's "
                        "'old tags\\internal system plain', which Upres does not redraw")
    parser.add_argument("--no-titles", action="store_true", help="Leave out the menu title pictures")
    parser.add_argument("--scale", type=int, default=4, help="Screen pixels to the Xbox pixel in phrase lines (tiles use twice this)")
    parser.add_argument("--phrase", action="append", help="A phrase to draw instead of the built-in ones; repeat for more")
    parser.add_argument("--characters", help="Characters for the tile tables; default every printable ASCII one in the font")
    parser.add_argument("--recipes", default=DEFAULT_RECIPES, help="Recipe names to draw with the shipped typeface, "
                        "comma-separated; default " + DEFAULT_RECIPES)
    parser.add_argument("--typeface", action="append", default=[], metavar="FILE[@WEIGHT]",
                        help="Another typeface file to try, tuned per letter; @WEIGHT picks a variable font's weight. "
                        "Repeat for more")
    args = parser.parse_args()
    if args.output.exists():
        sys.exit("Use a new output folder so earlier pages are kept")
    cache = XboxMap(PRIMARY / "assets/maps/ui.map")
    if args.review:
        if args.fonts == parser.get_default("fonts"):
            args.fonts = "ui\\large_ui,ui\\small_ui"
        return review(args, cache)
    files = {entry["tag"]: FONTS / entry["file"] for entry in json.loads((FONTS / "fonts.json").read_text())["fonts"]}
    chosen = [recipe for recipe in RECIPES if recipe[0] in args.recipes.split(",")]
    detail = args.scale * 2
    data = {"run": args.output.name, "fonts": [], "recipes": [], "titles": [], "titleFont": ""}
    if not args.no_titles:
        data["titleFont"], data["titles"] = title_pictures(cache, args.scale)
        print(f"menu titles: {len(data['titles'])} pictures")
    for name in filter(None, args.fonts.split(",")):
        font = MapFont(cache, name)
        shipped = Outline(files[name], font.capital_rows, detail)
        # each candidate: its name for picks, its label, its recipe, its typeface
        recipes = [recipe + (shipped,) for recipe in chosen if not recipe[0].startswith("trace")]
        for spec in args.typeface:
            file, _, weight = spec.partition("@")
            other = Outline(Path(file), font.capital_rows, detail, weight)
            recipes.append((other.label, other.label, recipe_matched, other))
        recipes += [recipe + (shipped,) for recipe in chosen if recipe[0].startswith("trace")]
        data["recipes"] = [recipe[:2] for recipe in recipes]
        state = {}
        entry = {"name": name, "file": files[name].name, "phrases": [], "characters": []}
        characters = args.characters or "".join(chr(code) for code in range(33, 127) if code in font.glyphs)
        errors = {recipe[0]: {c: glyph_error(font, c, recipe[2], recipe[3], detail, state) for c in characters + "".join(
            args.phrase or PHRASES) if ord(c) in font.glyphs} for recipe in recipes}
        for text in args.phrase or PHRASES:
            original = original_line(font, text, detail)
            lines = [{"image": picture(original, detail, 2, TEXT, GROUND, 1.0)}]
            for recipe in recipes:
                ink = recipe_line(font, text, recipe[2], recipe[3], detail, state)
                inked = [errors[recipe[0]].get(c) for c in text]
                inked = [value for value in inked if value is not None]
                lines.append({"image": picture(ink, detail, 2, TEXT, GROUND, 0.5),
                              "error": round(100 * sum(inked) / max(len(inked), 1))})
            for line in lines:
                line["width"], line["height"] = original.shape[1] // 2, original.shape[0] // 2
            entry["phrases"].append({"text": text, "lines": lines})
        for character in characters:
            original = original_line(font, character, detail)
            tiles = [{"image": picture(original, detail, 1, TILE_TEXT, TILE_GROUND, 0)}]
            for recipe in recipes:
                ink = recipe_line(font, character, recipe[2], recipe[3], detail, state)
                error = errors[recipe[0]].get(character)
                tiles.append({"image": picture(ink, detail, 1, TILE_TEXT, TILE_GROUND, 0), "overlay": overlay(original, ink, 1),
                              "error": "-" if error is None else round(100 * error)})
            entry["characters"].append({"text": character, "tiles": tiles, "width": original.shape[1], "height": original.shape[0]})
        data["fonts"].append(entry)
        tuned_letters = {key[1]: value for key, value in state.items() if key[3] and key[2] == id(shipped) and value}
        closest = {}
        for character in characters:
            scored = [(errors[recipe[0]][character], recipe[1]) for recipe in recipes
                      if errors[recipe[0]][character] is not None and not recipe[0].startswith("trace")]
            if scored:
                closest.setdefault(min(scored)[1], []).append(character)
        print(f"{name}: closest typeface redraw by character: " + "; ".join(
            f"{label} ({len(found)}) {''.join(found)}" for label, found in sorted(closest.items(), key=lambda item: -len(item[1]))))
        print(f"{name} ({files[name].name}): {len(characters)} characters; average difference from the original at Xbox size: " + ", ".join(
            f"{recipe[1]} {round(100 * np.mean([v for v in errors[recipe[0]].values() if v is not None]))}%" for recipe in recipes))
        if tuned_letters:
            weights = [value[4] for value in tuned_letters.values()]
            print(f"  tuned per letter: stroke weight moved by {np.mean(weights):+.2f} px on average "
                  f"({min(weights):+.2f} to {max(weights):+.2f})")
    args.output.mkdir(parents=True)
    page = args.output / "index.html"
    page.write_text(PAGE.replace("__DATA__", json.dumps(data).replace("</", "<\\/")))
    print(f"Page: {page} ({page.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
