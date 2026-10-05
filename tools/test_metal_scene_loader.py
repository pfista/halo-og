#!/usr/bin/env python3
"""Exercise the native preview's exact-mip loader without requiring a GPU."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('xcrun'), 'Native macOS loader')
class NativeMipLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='metal-scene-loader-')
        cls.directory = Path(cls.temporary.name)
        cls.probe = cls.directory / 'loader-probe'
        source = cls.directory / 'loader-probe.mm'
        source.write_text('''#define main haloMetalPreviewMain
#include "''' + str(ROOT / 'port/macos/metal-poc/main.mm') + '''"
#undef main
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) return 2;
        NSDictionary *texture = [NSJSONSerialization JSONObjectWithData:readFile(@(argv[1]))
            options:0 error:nil];
        auto levels = loadTextureMipmaps(texture, @(argv[2]));
        for (const TextureMipLevel &mip : levels)
            printf("%lu %lu %s %s %lu\\n", mip.width, mip.height, sha256(mip.pixels).UTF8String,
                mip.format == MTLPixelFormatBC1_RGBA ? "bc1" : "rgba8", mip.bytesPerRow);
    }
    return 0;
}
''')
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fobjc-arc', '-O0',
                        '-mmacosx-version-min=13.0', str(source), '-framework', 'Cocoa',
                        '-framework', 'Metal', '-framework', 'MetalKit', '-framework', 'QuartzCore',
                        '-o', str(cls.probe)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.scene = self.directory / self._testMethodName
        self.scene.mkdir()
        self.pixels = [bytes([19, 41, 71, 255]) * 16, bytes([128, 128, 128, 255]) * 4]
        for level, pixels in enumerate(self.pixels):
            (self.scene / f'mip-{level}.rgba').write_bytes(pixels)
        self.texture = dict(width=4, height=4, file='mip-0.rgba', mipmaps=[
            dict(width=4, height=4, file='mip-0.rgba'),
            dict(width=2, height=2, file='mip-1.rgba')])

    def run_loader(self, success=True, message=None):
        manifest = self.scene / 'texture.json'
        manifest.write_text(json.dumps(self.texture))
        result = subprocess.run([str(self.probe), str(manifest), str(self.scene)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
        if message:
            self.assertIn(message, result.stderr)
        return result.stdout

    def test_keeps_authored_level_bytes_and_count(self):
        # Level1 is deliberately different from any reduction of level0.
        expected = ''.join(f'{size} {size} {hashlib.sha256(pixels).hexdigest()} rgba8 {size*4}\n'
                           for size, pixels in zip((4, 2), self.pixels))
        self.assertEqual(self.run_loader(), expected)

    def test_single_level_explicit_fallback(self):
        self.texture = dict(width=1, height=1, file='fallback.rgba', mipmaps=[
            dict(width=1, height=1, file='fallback.rgba')])
        pixels = bytes([128, 128, 128, 255])
        (self.scene / 'fallback.rgba').write_bytes(pixels)
        self.assertEqual(self.run_loader(), f'1 1 {hashlib.sha256(pixels).hexdigest()} rgba8 4\n')

    def compressed_texture(self):
        # Rectangular Xbox BC1 levels end at 4x2, retaining a full 4x4 block.
        # Deliberately unrelated decoded files prove the native loader selects
        # original blocks, rather than recompressing or sampling those RGBA files.
        blocks = [bytes.fromhex('00f8000000000000') * 2,
                  bytes.fromhex('e007000000000000')]
        self.texture.update(width=8, height=4, source_format=14, swizzled=False,
                            native_format='bc1_rgba', native_file='mip-0.bc1',
                            native_mipmaps=[dict(width=8, height=4, file='mip-0.bc1'),
                                            dict(width=4, height=2, file='mip-1.bc1')])
        for i, block in enumerate(blocks):
            (self.scene / f'mip-{i}.bc1').write_bytes(block)
        return blocks

    def test_original_compressed_rectangular_mips_and_block_pitch(self):
        blocks = self.compressed_texture()
        expected = ''.join(f'{w} {h} {hashlib.sha256(block).hexdigest()} bc1 {pitch}\n'
                           for w,h,block,pitch in ((8,4,blocks[0],16),(4,2,blocks[1],8)))
        self.assertEqual(self.run_loader(), expected)

    def test_compressed_truncation_rejected(self):
        self.compressed_texture()
        (self.scene / 'mip-1.bc1').write_bytes(bytes(7))
        self.run_loader(False, 'Invalid texture mipmap byte count')

    def test_compressed_format_must_match_source(self):
        self.compressed_texture()
        self.texture['source_format'] = 15
        self.run_loader(False, 'Unsupported native texture format')

    def test_compressed_chain_must_preserve_authored_level_count(self):
        self.compressed_texture()
        self.texture['native_mipmaps'].pop()
        self.run_loader(False, 'Native mipmaps differ from authored level count')

    def test_missing_or_empty_mipmap_list_rejected(self):
        for value in (None, []):
            with self.subTest(value=value):
                self.texture['mipmaps'] = value
                self.run_loader(False, 'Scene lacks authored mipmaps')

    def test_wrong_level_dimensions_rejected(self):
        self.texture['mipmaps'][1]['width'] = 3
        self.run_loader(False, 'Invalid texture mipmap dimensions')

    def test_fractional_dimensions_rejected(self):
        self.texture['mipmaps'][1]['height'] = 2.5
        self.run_loader(False, 'Invalid texture dimensions')

    def test_level_bytes_rejected(self):
        (self.scene / 'mip-1.rgba').write_bytes(bytes(15))
        self.run_loader(False, 'Invalid texture mipmap byte count')

    def test_mipmap_filename_must_stay_in_scene(self):
        for name in ('../mip-1.rgba', '/tmp/mip-1.rgba', '.', '..', ''):
            with self.subTest(name=name):
                self.texture['mipmaps'][1]['file'] = name
                self.run_loader(False, 'Invalid texture mipmap filename')

    def test_mipmap_zero_must_match_texture_file(self):
        self.texture['mipmaps'][0]['file'] = 'different.rgba'
        self.run_loader(False, 'Mipmap zero filename mismatch')

    def test_chain_cannot_repeat_final_level(self):
        self.texture['mipmaps'] += [dict(width=1, height=1, file='tail.rgba')] * 2
        self.run_loader(False, 'Too many texture mipmaps')


if __name__ == '__main__':
    unittest.main()
