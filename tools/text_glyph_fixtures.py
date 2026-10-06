"""Real committed-font pixels shared by the native and portable GPU probes."""
import copy
from pathlib import Path
import sys

# Existing standalone shader tools also resolve their peers as top-level
# modules; keep both `python tools/...` and unittest module calls working.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from .test_text_hires import real_glyph
    from .metal_hud_hires_validate import CLEAR, text_key
    from . import metal_shader_validate as shader
except ImportError:
    from test_text_hires import real_glyph
    from metal_hud_hires_validate import CLEAR, text_key
    import metal_shader_validate as shader


def real_text_fixtures(directory):
    metadata, atlas = real_glyph(Path(directory) / "glyph-core")
    _, _, _, _, u0, v0, u1, v1, _ = metadata["glyph"]
    x0, y0 = round(u0 * 8) - 2, round(v0 * 8) - 2
    width, height = round((u1 - u0) * 8) + 4, round((v1 - v0) * 8) + 4
    stride = metadata["width"] * 4
    pixels = b"".join(atlas[y * stride + x0 * 4:y * stride + (x0 + width) * 4]
                      for y in range(y0, y0 + height))
    alpha = pixels[3::4]
    opaque = next(index for index, value in enumerate(alpha) if value == 255)
    edge = next(index for index, value in enumerate(alpha) if 0 < value < 255)
    pairs = [(abs(alpha[y * width + x + 1] - alpha[y * width + x]), x, y)
             for y in range(height) for x in range(width - 1)]
    _, filtered_x, filtered_y = max(pairs)
    probes = {
        "transparent": (.5 / width, .5 / height),
        "opaque": ((opaque % width + .5) / width, (opaque // width + .5) / height),
        "antialias": ((edge % width + .5) / width, (edge // width + .5) / height),
        "filtered": ((filtered_x + 1) / width, (filtered_y + .5) / height),
    }

    def sampled(u, v):
        # Independent clamp-edge bilinear alpha, including exact RGBA8 decode.
        x, y = u * width - .5, v * height - .5
        low_x, low_y = int(x // 1), int(y // 1)
        fx, fy = x - low_x, y - low_y
        def at(px, py):
            return alpha[max(0, min(height - 1, py)) * width + max(0, min(width - 1, px))] / 255
        return ((at(low_x, low_y) * (1 - fx) + at(low_x + 1, low_y) * fx) * (1 - fy) +
                (at(low_x, low_y + 1) * (1 - fx) + at(low_x + 1, low_y + 1) * fx) * fy)

    for name, (u, v) in probes.items():
        coverage = sampled(u, v)
        for tint in ([.4, .7, 1., 1.], [.4, .7, 1., .5], [0., 0., 0., .8]):
            for blended in (False, True):
                f = copy.deepcopy(shader.fixture(f"text-real-glyph-{name}-{tint}-{int(blended)}"))
                f["inputs"]["d0"] = tint
                f["inputs"]["t"][0] = [u, v, 0, 1]
                f["textures"][0] = dict(kind=1, width=width, height=height, linear=True,
                    clamp_axes=3, rgba=list(pixels))
                f["uniforms"]["c0"][0] = [1, 1, 1, 1]
                source = tint[:3] + [tint[3] * coverage]
                f["text_blend"] = blended
                f["clear_color"] = CLEAR
                f["expected"] = ([a * source[3] + b * (1 - source[3])
                    for a, b in zip(source[:3], CLEAR[:3])] + [CLEAR[3]] if blended else source)
                f["coverage"] = coverage
                f["real_glyph"] = name
                yield text_key(), f
