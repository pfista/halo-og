#!/usr/bin/env python3
"""Small format checks for the cache importer; runtime rendering is tested on Metal."""
from pathlib import Path
import contextlib
import io
import json
import struct
import tempfile
import unittest

from metal_poc_export import Cache, bitmap_mipmap_layout, decode_bitmap, decode_bitmap_mipmaps, export, sky_geometry_indices


class SkySelectionTests(unittest.TestCase):
    def fixture(self, lod_indices, permutations=1, flags=0):
        raw = bytearray(1024)
        struct.pack_into('<II',raw,0xc4,1,0x100)
        struct.pack_into('<II',raw,0x100+64,permutations,0x200)
        struct.pack_into('<I',raw,0x200+32,flags)
        struct.pack_into('<5h',raw,0x200+64,*lod_indices)
        class SkyCache:
            def unpack(self,fmt,offset):return struct.unpack_from(fmt,raw,offset)
            def u32(self,offset):return self.unpack('<I',offset)[0]
            def pointer(self,address,size=1):
                if address<0 or address+size>len(raw):raise ValueError('pointer out of bounds')
                return address
        return SkyCache()

    def test_region_selects_only_its_authored_geometry(self):
        # Four geometries exist, but the original region selects only number2.
        self.assertEqual(sky_geometry_indices(self.fixture([2]*5),0,4),[2])

    def test_alternate_permutation_or_lod_requires_real_selection(self):
        with self.assertRaisesRegex(ValueError,'alternate permutations'):
            sky_geometry_indices(self.fixture([0]*5,permutations=2),0,4)
        with self.assertRaisesRegex(ValueError,'LOD selection'):
            sky_geometry_indices(self.fixture([0,1,1,1,1]),0,4)

    def test_bad_reference_flags_or_no_selected_geometry_reject(self):
        for indices,flags in [([4]*5,0),([-1]*5,0),([0]*5,1)]:
            with self.subTest(indices=indices,flags=flags),self.assertRaises(ValueError):
                sky_geometry_indices(self.fixture(indices,flags=flags),0,4)


class BitmapTests(unittest.TestCase):
    def test_dxt1_color_and_transparent_modes(self):
        # A red endpoint and a green endpoint, with each of the four selectors.
        pixels = decode_bitmap(struct.pack('<HHI', 0xf800, 0x07e0, 0xe4), 4, 4, 14, False)
        self.assertEqual(list(pixels[:16]), [255, 0, 0, 255, 0, 255, 0, 255,
                                           170, 85, 0, 255, 85, 170, 0, 255])
        transparent = decode_bitmap(struct.pack('<HHI', 0, 0xffff, 3), 4, 4, 14, False)
        self.assertEqual(transparent[:4], bytes(4))

    def test_dxt3_and_dxt5_alpha(self):
        color = struct.pack('<HHI', 0xf800, 0, 0)
        explicit = decode_bitmap((0xf).to_bytes(8, 'little') + color, 4, 4, 15, False)
        self.assertEqual(explicit[:8], bytes([255, 0, 0, 255, 255, 0, 0, 0]))
        interpolated = decode_bitmap(bytes([255, 0]) + (2).to_bytes(6, 'little') + color,
                                     4, 4, 16, False)
        self.assertEqual(interpolated[:4], bytes([255, 0, 0, 218]))

    def test_rectangular_xbox_swizzle(self):
        # 4x2 row-major pixels map to Morton source slots 0,1,4,5 / 2,3,6,7.
        raw = struct.pack('<8H', 0xf800, 0x07e0, 0x001f, 0xffff, 0, 0xffe0, 0x07ff, 0xf81f)
        pixels = decode_bitmap(raw, 4, 2, 6, True)
        self.assertEqual(pixels[:16], bytes([255, 0, 0, 255, 0, 255, 0, 255,
                                            0, 0, 0, 255, 255, 255, 0, 255]))
        self.assertEqual(pixels[16:20], bytes([0, 0, 255, 255]))

    def test_truncated_and_unsupported_textures_fail(self):
        for data, w, h, fmt, swizzled in [(b'', 4, 4, 14, False), (b'', 4, 4, 6, True),
                                         (bytes(16), 4, 4, 16, True), (bytes(16), 2, 2, 17, False)]:
            with self.assertRaises(ValueError):
                decode_bitmap(data, w, h, fmt, swizzled)

    def test_authored_dxt_levels_are_preserved_and_hardware_tail_is_excluded(self):
        red = struct.pack('<HHI', 0xf800, 0, 0)
        green = struct.pack('<HHI', 0x07e0, 0, 0)
        # Halo exposes 8x8 and 4x4, even when the cache declares three mips.
        # The green authored mip differs from any mip generated from red.
        levels = decode_bitmap_mipmaps(red * 4 + green + bytes(128), 8, 8, 14, 3, 3)
        self.assertEqual([(m['width'], m['height']) for m in levels], [(8, 8), (4, 4)])
        self.assertEqual(levels[0]['rgba'], bytes([255, 0, 0, 255]) * 64)
        self.assertEqual(levels[1]['rgba'], bytes([0, 255, 0, 255]) * 16)
        # The cap uses the largest dimension; rectangular levels still use
        # complete 4x4 blocks when the other dimension falls below four.
        self.assertEqual(bitmap_mipmap_layout(16, 4, 14, 3, 4),
                         [(16, 4, 0, 32, 32), (8, 2, 32, 16, 16), (4, 1, 48, 8, 8)])

    def test_dxt3_and_dxt5_mip_offsets(self):
        red = struct.pack('<HHI', 0xf800, 0, 0)
        green = struct.pack('<HHI', 0x07e0, 0, 0)
        for fmt, alpha in ((15, bytes([255]) * 8), (16, bytes([255, 0]) + bytes(6))):
            levels = decode_bitmap_mipmaps((alpha + red) * 4 + alpha + green, 8, 8, fmt, 3, 3)
            self.assertEqual(levels[1]['rgba'], bytes([0, 255, 0, 255]) * 16)

    def test_rectangular_swizzle_restarts_at_each_authored_mip(self):
        base = struct.pack('<8H', 0xf800, 0x07e0, 0x001f, 0xffff, 0, 0xffe0, 0x07ff, 0xf81f)
        levels = decode_bitmap_mipmaps(base + struct.pack('<3H', 0xf800, 0xffe0, 0xffff),
                                      4, 2, 6, 9, 2)
        self.assertEqual([(m['width'], m['height']) for m in levels], [(4, 2), (2, 1), (1, 1)])
        self.assertEqual(levels[0]['rgba'][8:12], bytes([0, 0, 0, 255]))
        self.assertEqual(levels[1]['rgba'], bytes([255, 0, 0, 255, 255, 255, 0, 255]))
        self.assertEqual(levels[2]['rgba'], bytes([255] * 4))

    def test_linear_rows_use_xbox_pitch_and_have_no_extra_mips(self):
        red, green = struct.pack('<H', 0xf800), struct.pack('<H', 0x07e0)
        raw = red * 3 + bytes([0xa5]) * 58 + green * 3 + bytes([0xa5]) * 58
        levels = decode_bitmap_mipmaps(raw, 3, 2, 6, 16, 1)
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0]['rgba'], bytes([255, 0, 0, 255]) * 3 +
                         bytes([0, 255, 0, 255]) * 3)

    def test_short_mip_chains_and_inconsistent_layouts_fail(self):
        for raw, w, h, fmt, flags, count in (
                (bytes(32), 8, 8, 14, 3, 3),  # mip0 complete, mip1 missing
                (bytes(21), 4, 2, 6, 9, 2),  # final 16-bit texel missing
                (bytes(127), 3, 2, 6, 16, 0),  # last padded row truncated
                (bytes(64), 8, 8, 14, 1, 3),  # wrong compression flag
                (bytes(64), 8, 8, 14, 11, 3),  # compressed + swizzled
                (bytes(64), 8, 8, 14, 19, 3),  # compressed + linear
                (bytes(64), 3, 2, 6, 9, 0),  # invalid Morton dimensions
                (bytes(64), 4, 4, 6, 9, -1),
                (bytes(64), 4, 4, 6, 9, 3)):
            with self.subTest(width=w, height=h, format=fmt, flags=flags, count=count):
                with self.assertRaises(ValueError):
                    decode_bitmap_mipmaps(raw, w, h, fmt, flags, count)


def fixture_cache(path, truncate_selected_base=False, invalid_lightmap=False):
    """A real v5 cache with one BSP draw, unequal bitmap counts and authored mips."""
    raw = bytearray(0x5000)
    raw[:4], raw[2044:2048] = b'daeh', b'toof'
    struct.pack_into('<4I', raw, 4, 5, len(raw), 0, 0x800)
    struct.pack_into('<I', raw, 20, 0x2400)
    raw[32:39] = b'fixture'
    tag_base, bsp_address = 0x40440000, 0x80000000
    tag_ptr = lambda offset: tag_base + offset - 0x800
    bsp_ptr = lambda offset: bsp_address + offset - 0x3000
    struct.pack_into('<4I', raw, 0x800, tag_base + 36, 0x10000, 0, 5)
    for i, (cls, offset) in enumerate((('scnr', 0x1000), ('senv', 0x1800),
                                      ('bitm', 0x1c00), ('bitm', 0x1d00), ('bitm', 0x1e00))):
        table = 0x824 + i * 32
        raw[table:table + 4] = cls[::-1].encode()
        struct.pack_into('<3I', raw, table + 12, 0x10000 + i, tag_ptr(0xa00 + i * 16), tag_ptr(offset))
        raw[0xa00 + i * 16:0xa08 + i * 16] = f'fixture{i}'.encode()
    struct.pack_into('<2I', raw, 0x1000 + 0x5a4, 1, tag_ptr(0x2300))
    struct.pack_into('<3I', raw, 0x2300, 0x3000, 0x1000, bsp_address)
    struct.pack_into('<I', raw, 0x3000, bsp_ptr(0x3040))
    struct.pack_into('<I', raw, 0x3040 + 12, 0x10004)
    struct.pack_into('<6f', raw, 0x3040 + 0xc8, 0, 1, 0, 1, 0, 1)
    struct.pack_into('<2I', raw, 0x3040 + 0xf8, 1, bsp_ptr(0x3400))
    struct.pack_into('<2I', raw, 0x3040 + 0x104, 1, bsp_ptr(0x3420))
    struct.pack_into('<3H', raw, 0x3400, 0, 1, 2)
    struct.pack_into('<h', raw, 0x3420, 2 if invalid_lightmap else 1)
    struct.pack_into('<2I', raw, 0x3420 + 20, 1, bsp_ptr(0x3480))
    struct.pack_into('<Ih', raw, 0x3480 + 12, 0x10001, 5)
    struct.pack_into('<2I', raw, 0x3480 + 20, 0, 1)
    struct.pack_into('<I', raw, 0x3480 + 0xb4, 3)
    struct.pack_into('<I', raw, 0x3480 + 0xc8, 3)
    struct.pack_into('<I', raw, 0x3480 + 0xf8, bsp_ptr(0x3600))
    for i in range(3):
        struct.pack_into('<3f', raw, 0x3600 + i * 32, i == 1, i == 2, 0)
    for offset, index in ((0x88, 2), (0xb8, 3), (0xcc, None), (0xfc, None)):
        struct.pack_into('<I', raw, 0x1800 + offset + 12, 0xffffffff if index is None else 0x10000 + index)
    for offset in (0xb4, 0xc8, 0xf8):
        struct.pack_into('<f', raw, 0x1800 + offset, 1)
    next_pixels = 0x4000
    for tag, count, array in ((0x1c00, 2, 0x2000), (0x1d00, 3, 0x2100), (0x1e00, 2, 0x2200)):
        struct.pack_into('<2I', raw, tag + 96, count, tag_ptr(array))
        for index in range(count):
            data = array + index * 48
            raw[data:data + 4] = b'mtib'
            if tag == 0x1c00:
                w, h, fmt, flags, mips = 8, 4, 14, 3, 3
                pixels = struct.pack('<HHI', 0xf800, 0, 0) * 2 + struct.pack('<HHI', 0x07e0, 0, 0)
            elif tag == 0x1d00:
                w, h, fmt, flags, mips = 4, 4, 14, 3, 0
                pixels = struct.pack('<HHI', (0xf800, 0x07e0, 0x001f)[index], 0, 0)
            else:
                w, h, fmt, flags, mips = 4, 2, 6, 9, 2
                pixels = struct.pack('<11H', *([0xffff if index else 0] * 11))
            struct.pack_into('<6H', raw, data + 4, w, h, 1, 0, fmt, flags)
            struct.pack_into('<h', raw, data + 20, mips)
            size = 16 if truncate_selected_base and tag == 0x1c00 and index == 1 else 128
            struct.pack_into('<2I', raw, data + 24, next_pixels, size)
            raw[next_pixels:next_pixels + len(pixels)] = pixels
            next_pixels += 128
    path.write_bytes(raw)


class CacheTests(unittest.TestCase):
    def test_export_preserves_authored_mips_and_material_bitmap_permutations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_cache(root / 'fixture.map')
            with contextlib.redirect_stdout(io.StringIO()):
                manifest = export(root / 'fixture.map', root / 'scene')
            draw = manifest['meshes'][0]
            self.assertEqual(draw['bitmap_permutation'], 5)
            base = manifest['textures'][draw['base_texture']]
            detail = manifest['textures'][draw['detail_textures'][0]]
            lightmap = manifest['textures'][draw['lightmap_texture']]
            self.assertEqual((base['bitmap_index'], detail['bitmap_index'], lightmap['bitmap_index']), (1, 2, 1))
            self.assertEqual([(m['width'], m['height']) for m in base['mipmaps']], [(8, 4), (4, 2)])
            self.assertEqual(base['file'], base['mipmaps'][0]['file'])
            self.assertEqual((root / 'scene' / base['mipmaps'][1]['file']).read_bytes(),
                             bytes([0, 255, 0, 255]) * 8)
            self.assertEqual(base['native_format'], 'bc1_rgba')
            self.assertEqual([(m['width'], m['height']) for m in base['native_mipmaps']], [(8, 4), (4, 2)])
            self.assertEqual((root / 'scene' / base['native_mipmaps'][0]['file']).read_bytes(),
                             struct.pack('<HHI', 0xf800, 0, 0) * 2)
            self.assertEqual((root / 'scene' / base['native_mipmaps'][1]['file']).read_bytes(),
                             struct.pack('<HHI', 0x07e0, 0, 0))
            self.assertNotIn('native_format', lightmap)
            self.assertEqual((root / 'scene' / detail['file']).read_bytes(), bytes([0, 0, 255, 255]) * 16)
            self.assertEqual((root / 'scene' / lightmap['mipmaps'][2]['file']).read_bytes(), bytes([255] * 4))
            for default in manifest['textures'][:2]:
                self.assertEqual(default['mipmaps'], [dict(file=default['file'], width=1, height=1)])
            saved = json.loads((root / 'scene' / 'scene.json').read_text())
            self.assertEqual(saved['textures'], manifest['textures'])
            self.assertEqual(saved['meshes'], manifest['meshes'])

    def test_export_rejects_truncated_mips_and_does_not_wrap_lightmap_indices(self):
        for options, message in ((dict(truncate_selected_base=True), 'Truncated bitmap mip chain'),
                                 (dict(invalid_lightmap=True), 'Invalid bitmap index')):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture_cache(root / 'fixture.map', **options)
                with self.assertRaisesRegex(ValueError, message):
                    export(root / 'fixture.map', root / 'scene')

    def test_rejects_non_xbox_and_oversized_decompression(self):
        import zlib
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.map'
            header = bytearray(2048)
            header[:4], header[2044:] = b'daeh', b'toof'
            struct.pack_into('<II', header, 4, 7, 2048)
            path.write_bytes(header)
            with self.assertRaisesRegex(ValueError, 'version 5'):
                Cache(path)
            struct.pack_into('<II', header, 4, 5, 2056)
            path.write_bytes(header + zlib.compress(bytes(4096)))
            with self.assertRaisesRegex(ValueError, 'compressed cache size'):
                Cache(path)


if __name__ == '__main__':
    unittest.main()
