#!/usr/bin/env python3
"""Check original geometry, clears and forged no-write replay rejection."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from metal_frame_replay import (VerificationPackage, clear_command, geometry,
                                verify_original_commands, verify_replay)


class Package:
    def read(self, value): return value['data']
    def write(self, name, data): return dict(file=name, data=data)


def readonly_fixture():
    """Independent captured-style state: tests must not generate its expected state."""
    targets = dict(color=dict(target_id=1, version=37),
                   depth_stencil=dict(target_id=2, version=37))
    event = dict(event=40, kind='draw', draw='draw-0036.json', use=36,
                 before=targets, after=copy.deepcopy(targets), readonly_visibility_query=True)
    viewport = dict(origin_x=0, origin_y=0, width=16, height=16, znear=0, zfar=1)
    scissor = dict(enabled=True, box_gl=[2, 3, 10, 9])
    raw_state = dict(depth_enable=1, depth_write=0, depth_compare=515,
                     cull=2305, front_face=2304, color_write=0, blend_enable=0,
                     blend_source=770, blend_destination=771, blend_op=32774,
                     offset_enable=1, offset_slope=-2, offset_units=-8,
                     stencil_enable=0, stencil_compare=514, stencil_ref=0,
                     stencil_read_mask=1, stencil_write_mask=0,
                     stencil_fail=7680, stencil_depth_fail=7680, stencil_pass=7680)
    actual = dict(depth_cull_blend_stencil_offset_words=[1, 0, 515, 1, 1029, 2305,
                  0, 770, 771, 32774, 0, 514, 0, 1, 255, 1], blend_color=[.8, 1., .8, 1.])
    raw = dict(use=36, before=targets, viewport=viewport, scissor=scissor,
               render_state_d3d=raw_state, actual_gl_state=actual,
               render_state_words=dict(data=bytes(576)), textures=[None]*4)
    state = dict(viewport=dict(x=0, y=0, width=16, height=16, znear=0, zfar=1),
                 scissor=dict(x=2, y=3, width=10, height=9),
                 depth=dict(enabled=True, write=False, compare='less_equal'),
                 raster=dict(front_face='cw', cull='back', fill='solid', depth_bias=-8,
                             slope_scale=-2, depth_bias_clamp=0.),
                 blend=dict(enabled=False, source='source_alpha', destination='one_minus_source_alpha',
                            operation='add', write_mask=0, color=[.8, 1., .8, 1.]),
                 stencil=dict(enabled=False, compare='equal', reference=0, read_mask=1,
                              write_mask=0, fail='keep', depth_fail='keep', **{'pass': 'keep'}))
    frame = dict(events=[event], draws={event['draw']: raw},
                 targets={'color': dict(target_id=1, width=16, height=16),
                          'depth': dict(target_id=2, width=16, height=16)})
    manifest = dict(commands=[copy.deepcopy(event)],
                    draws={event['draw']: dict(use=36, targets=targets, render_state=state, textures=[None]*4)})
    return manifest, frame


class FrameReplayTests(unittest.TestCase):
    def test_original_index_and_stream_origins_are_preserved(self):
        raw = dict(primitive_d3d=5, source_first_vertex=23, source_base_vertex=20,
                   vertex_count=3, index_count=3, immediate=False,
                   indices=dict(data=struct.pack('<3H', 3, 4, 5)),
                   vertex_declaration=dict(packed_mask=0, elements=[dict(register=0, stream=0, offset=0, type=0x42)]),
                   streams=[dict(stream=0, stride=16, source_first_vertex=23, payload=dict(data=bytes(48)))])
        declaration, streams, draw = geometry(Package(), raw)
        self.assertEqual(draw['base_vertex'], 20)
        self.assertEqual(streams[0]['first_vertex'], 23)
        self.assertEqual(struct.unpack('<3H', draw['index_buffer']['data']), (3, 4, 5))

    def test_immediate_draw_binds_sixteen_original_float4_registers(self):
        raw = dict(primitive_d3d=8, source_first_vertex=0, source_base_vertex=99,
                   vertex_count=4, index_count=0, immediate=True, indices=None,
                   vertex_declaration=dict(packed_mask=0, elements=[]),
                   streams=[dict(stream=0, stride=256, source_first_vertex=0, payload=dict(data=bytes(1024)))])
        declaration, streams, draw = geometry(Package(), raw)
        self.assertEqual(len(declaration['elements']), 16)
        self.assertTrue(all(e['type'] == 0x42 and e['offset'] == e['register']*16 for e in declaration['elements']))
        self.assertEqual(draw['base_vertex'], 0)
        self.assertEqual(draw['primitive'], 'quad')

    def test_partial_red_clear_preserves_other_channels_and_logical_y(self):
        event = dict(event=0, before=dict(color=dict(target_id=1, version=0), depth_stencil=None),
                     after=dict(color=dict(target_id=1, version=1), depth_stencil=None),
                     viewport=[10, 20, 30, 40], rectangles=[[0, 0, 25, 35]],
                     color_d3d=0xff112233, flags_d3d=0x10, depth=1, stencil=0)
        target = dict(width=640, height=480, source_width=640, source_height=480)
        command = clear_command(event, {1: target})
        self.assertEqual(command['color_write_mask'], 1)
        self.assertEqual(command['rectangles'], [dict(x=10, y=20, width=15, height=15)])
        self.assertEqual(command['color'], [17/255, 34/255, 51/255, 1])
        self.assertFalse(command['clear_depth'])

    def test_truncated_or_wrong_index_span_is_rejected(self):
        raw = dict(primitive_d3d=5, source_first_vertex=0, source_base_vertex=0,
                   vertex_count=3, index_count=3, immediate=False,
                   indices=dict(data=struct.pack('<3H', 4, 5, 6)),
                   vertex_declaration=dict(packed_mask=0, elements=[]), streams=[])
        with self.assertRaisesRegex(ValueError, 'stream/index span'):
            geometry(Package(), raw)

    def test_original_readonly_state_preserves_attachment_version_37(self):
        manifest, frame = readonly_fixture()
        verify_original_commands(manifest, frame, Package())
        self.assertEqual(manifest['commands'][0]['before'], manifest['commands'][0]['after'])

    def test_forged_depth_write_is_rejected_before_replay(self):
        manifest, frame = readonly_fixture()
        manifest['draws']['draw-0036.json']['render_state']['depth']['write'] = True
        with self.assertRaisesRegex(ValueError, 'normalized render state'):
            verify_original_commands(manifest, frame, Package())

    def test_forged_readonly_visibility_flag_is_rejected(self):
        manifest, frame = readonly_fixture()
        manifest['commands'][0]['readonly_visibility_query'] = False
        with self.assertRaisesRegex(ValueError, 'read-only visibility flag'):
            verify_original_commands(manifest, frame, Package())

    def test_forged_query_result_and_partial_clear_state_are_rejected(self):
        manifest, frame = readonly_fixture()
        original = dict(event=41, kind='visibility_gpu_result', available=True, any_samples_passed=0)
        frame['events'].append(original)
        manifest['commands'].append(dict(original, any_samples_passed=1))
        with self.assertRaisesRegex(ValueError, 'visibility/bind/present'):
            verify_original_commands(manifest, frame, Package())
        manifest['commands'][1] = copy.deepcopy(original)
        original = dict(event=42, kind='clear', before=manifest['commands'][0]['before'],
                        after=manifest['commands'][0]['after'], viewport=[0, 0, 16, 16],
                        rectangles=[], color_d3d=0xff112233, flags_d3d=0x10, depth=1, stencil=0)
        for value in frame['targets'].values():
            value.update(source_width=16, source_height=16)
        frame['events'].append(original)
        command = clear_command(original, {value['target_id']: value for value in frame['targets'].values()})
        manifest['commands'].append(dict(command, color_write_mask=15))
        with self.assertRaisesRegex(ValueError, 'Prepared clear'):
            verify_original_commands(manifest, frame, Package())

    def test_stale_or_incomplete_translator_sources_are_rejected(self):
        expected = {'original.py': 'a'*64, 'vertex.c': 'b'*64}
        for changed in ({'original.py': '0'*64, 'vertex.c': 'b'*64}, {'original.py': 'a'*64}):
            with self.subTest(source_hashes=changed), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'frame-replay.json'
                path.write_text(json.dumps(dict(schema_version=1, kind='nv2a_frame_replay',
                                               complete=True, source_sha256=changed)))
                with patch('metal_frame_replay.frame_source_hashes', return_value=expected), \
                     self.assertRaisesRegex(ValueError, 'sources are stale or incomplete'):
                    verify_replay(path)

    def test_verification_never_creates_missing_or_substituted_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            package = VerificationPackage(Path(directory), Path(directory))
            with self.assertRaisesRegex(ValueError, 'captured-source derivation'):
                package.write('original.bin', b'original')
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__': unittest.main()
