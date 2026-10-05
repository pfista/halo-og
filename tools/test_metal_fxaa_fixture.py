"""CPU checks of authored FXAA inputs and the independent GPU comparator."""
import struct
import unittest

import metal_fxaa_validate as fxaa


class FxaaFixtureTests(unittest.TestCase):
    def setUp(self):
        self.rect = (8, 4, 16, 24)
        self.original = fxaa.image(32, self.rect)
        self.row = dict(expected=self.original.hex(), aa_rect=list(self.rect), width=32)
        self.smoothed = bytearray(self.original)
        # Independent example of a smoothed edge; no copy of the production
        # shader, search direction or sampling formula enters the oracle.
        self.offset = (10*32+15)*4
        self.smoothed[self.offset:self.offset+3] = bytes([128])*3

    def test_source_contains_edges_flat_pixels_alpha_and_outside_sentinel(self):
        pixels = [self.original[i:i+4] for i in range(0, len(self.original), 4)]
        self.assertEqual({p[3] for p in pixels}, set(range(256)))
        self.assertEqual(pixels[0][:3], bytes((253, 11, 197)))
        self.assertIn(bytes([32])*3, {p[:3] for p in pixels})
        self.assertIn(bytes([224])*3, {p[:3] for p in pixels})
        self.assertNotIn(bytes([128])*3, {p[:3] for p in pixels})

    def test_comparator_requires_actual_edge_smoothing(self):
        self.assertFalse(fxaa.compare(self.original, self.row)['passed'])
        result = fxaa.compare(bytes(self.smoothed), self.row)
        self.assertTrue(result['passed'])
        self.assertEqual(result['changed_edge_pixels'], 1)
        self.assertEqual(result['intermediate_edge_pixels'], 1)

    def test_comparator_detects_each_preservation_failure(self):
        mutations = [
            ('alpha_differences', self.offset+3, 123),
            ('outside_differences', 0, 22),
            ('viewport_leak_pixels', self.offset, 130),
        ]
        for key, offset, value in mutations:
            changed = bytearray(self.smoothed); changed[offset] = value
            with self.subTest(key=key):
                result = fxaa.compare(bytes(changed), self.row)
                self.assertFalse(result['passed']); self.assertGreater(result[key], 0)
        changed = bytearray(self.smoothed); offset = (26*32+8)*4
        changed[offset:offset+3] = bytes([128])*3
        result = fxaa.compare(bytes(changed), self.row)
        self.assertFalse(result['passed']); self.assertGreater(result['flat_differences'], 0)

    def test_exact_depth_stencil_query_comparison_and_size(self):
        for data in (bytes([91])*1024, struct.pack('<f', .75)*1024, struct.pack('<Q', 1024)):
            row = dict(expected=data.hex(), aa_rect=None)
            self.assertTrue(fxaa.compare(data, row)['passed'])
            self.assertFalse(fxaa.compare(data[:-1], row)['passed'])
            changed = bytearray(data); changed[-1] ^= 1
            self.assertFalse(fxaa.compare(bytes(changed), row)['passed'])

    def test_wire_record_and_negative_atomic_scope(self):
        self.assertEqual(struct.unpack('<8I', fxaa.fxaa()), (22, 32, 1, 1, 8, 4, 16, 24))
        fixture = fxaa.fixture()
        self.assertEqual(len(fixture.negative), 15)
        self.assertEqual(len(fixture.readbacks), 103)
        self.assertEqual(sum(row['label'].startswith('atomic/') for row in fixture.readbacks), 90)
        self.assertEqual({row['plane'] for row in fixture.readbacks if row['label'] == 'fxaa-baseline'}, {1, 2, 4, 8})
        self.assertTrue(all(p['failed_command'] == (1 if p['label'] == 'active-visibility-query' else 5)
                            for p in fixture.packets if p['status']))
        # Uploads contain only independent initial inputs, including a refresh;
        # no expected smoothed frame is uploaded to make GPU output pass.
        uploads = []
        for packet in fixture.packets:
            data = bytes.fromhex(packet['bytes']); cursor = 24
            while cursor < len(data):
                opcode, extent = struct.unpack_from('<2I', data, cursor)
                if opcode == 11:
                    offset, size = struct.unpack_from('<2I', data, cursor+56)
                    uploads.append(data[offset:offset+size])
                cursor += extent
            self.assertEqual(cursor, len(data))
        self.assertEqual(uploads, [self.original, self.original, fxaa.image(16, (0, 0, 16, 16)),
            fxaa.opposite(self.original), fxaa.image(32, (0, 0, 16, 32)), self.original])
        positive = bytes.fromhex(fixture.packets[1]['bytes'])
        commands = [struct.unpack_from('<8I', positive, offset) for offset in range(24, len(positive), 32)]
        self.assertEqual([command[2] for command in commands], [1, 11, 12, 12, 3, 4])
        self.assertEqual(commands[2][4:], (0, 0, 16, 32))
        self.assertEqual(commands[3][4:], (16, 0, 16, 32))


if __name__ == '__main__':
    unittest.main()
