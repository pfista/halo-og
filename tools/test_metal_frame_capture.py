#!/usr/bin/env python3
"""Mutation checks for frame order, alias lifetime, and query isolation."""
import copy
import unittest

from metal_frame_capture import validate_sequence


def fixture():
    ref = lambda v: dict(target_id=1, version=v)
    bound = lambda v: dict(color=ref(v), depth_stencil=None)
    status = dict(schema_version=1, kind='captured_frame', complete=True, frame=420,
                  orientation='top_left', event_count=5, draw_count=1, clear_count=0,
                  copy_count=0, target_bind_count=0)
    use = dict(program_id=17, declaration_id=17, immediate=0)
    draw = dict(complete=True, frame=420, use=0, **use, before=bound(0),
                vertex_constants=dict(bytes=3072), draw_uniforms=dict(bytes=636),
                fixed_attributes=dict(bytes=256), indices=None, streams=[],
                textures=[None]*4)
    events = [dict(event=0, frame=420, kind='visibility_begin', atomic_counters=False),
              dict(event=1, frame=420, kind='draw', draw='draw-0000.json', use=0,
                   before=bound(0), after=bound(0), readonly_visibility_query=True),
              dict(event=2, frame=420, kind='visibility_end', atomic_counters=False),
              dict(event=3, frame=420, kind='visibility_gpu_result', available=True, any_samples_passed=1),
              dict(event=4, frame=420, kind='present', targets=bound(0), back_buffer=ref(0))]
    return status, events, {'draw-0000.json': draw}, {(1, 0): {}}, [use]


class FrameCaptureTests(unittest.TestCase):
    def test_original_readonly_query_does_not_advance_attachment(self):
        self.assertEqual(validate_sequence(*fixture()), {1: 0})

    def test_gpu_readback_mutation_inside_query_is_rejected(self):
        args = fixture()
        args[1][1]['after']['color']['version'] = 1
        args[3][(1, 1)] = {}
        with self.assertRaisesRegex(ValueError, 'active visibility query'):
            validate_sequence(*args)

    def test_shader_identity_cannot_be_reused_for_different_program(self):
        args = fixture()
        args[2]['draw-0000.json']['program_id'] = 999
        with self.assertRaisesRegex(ValueError, 'paired'):
            validate_sequence(*args)

    def test_target_alias_cannot_use_a_missing_gpu_version(self):
        args = fixture()
        args[2]['draw-0000.json']['textures'][0] = dict(render_target_aliases=[dict(target_id=1, version=99)])
        with self.assertRaisesRegex(ValueError, 'alias version is missing'):
            validate_sequence(*args)

    def test_missing_or_reordered_command_is_rejected(self):
        args = fixture()
        args[1][1]['event'] = 3
        with self.assertRaisesRegex(ValueError, 'out of order'):
            validate_sequence(*args)


if __name__ == '__main__':
    unittest.main()
