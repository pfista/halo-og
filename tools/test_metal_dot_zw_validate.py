import math
import struct
import unittest
import metal_dot_zw_validate as depth

class DepthFixtureTests(unittest.TestCase):
    def test_ratio_is_previous_over_current(self):
        self.assertEqual(depth.ratio_depth((0,0,depth.D24*.25),(0,0,1),(0,0,255)),depth.f32(depth.f32(depth.D24*.25)*depth.f32(1/depth.D24)))
        self.assertEqual(depth.ratio_depth((0,0,depth.D24*.5),(0,0,2),(0,0,255)),depth.ratio_depth((0,0,depth.D24*.25),(0,0,1),(0,0,255)))
    def test_zero_denominator_is_discard(self):
        self.assertTrue(math.isnan(depth.ratio_depth((0,0,0),(0,0,0),(0,0,255))))
        self.assertTrue(math.isinf(depth.ratio_depth((0,0,1),(0,0,0),(0,0,255))))
        color,z,s,count,_=depth.oracle(dict(denominator=(0,0,0)))
        self.assertEqual(color,bytes((17,23,31,255))*64)
        self.assertEqual(z,struct.pack('<f',.5)*64);self.assertEqual(s,bytes([7])*64);self.assertEqual(count,bytes(8))
    def test_mask_and_stencil_failure_have_independent_results(self):
        color,z,s,count,_=depth.oracle(dict(color_mask=5,depth_write=False))
        self.assertEqual(color,bytes((32,23,128,255))*64)
        self.assertEqual(z,struct.pack('<f',.5)*64);self.assertEqual(s,bytes([33])*64);self.assertEqual(count,struct.pack('<Q',64))
        color,z,s,count,_=depth.oracle(dict(stencil_compare='never',stencil_fail='replace'))
        self.assertEqual(color,bytes((17,23,31,255))*64);self.assertEqual(s,bytes([33])*64);self.assertEqual(count,bytes(8))
    def test_production_depth_uniforms_and_safe_program_contract(self):
        fixed,payloads=depth.draw(near=.25,far=.75)
        ps=dict(payloads)[404]
        self.assertEqual(struct.unpack_from('<3f',ps,324),(depth.f32(1/depth.D24),.25,.75))
        program,_=depth.program(100,'fragment')
        self.assertEqual(struct.unpack_from('<I',program,36)[0],0)
        self.assertEqual(len(fixed),416)
    def test_actual_guest_key_round_trip(self):
        self.assertEqual(len(depth.canonical(depth.captured_key())),260)
        self.assertEqual(depth.captured_key().texture_modes,0x54421)

if __name__=='__main__':unittest.main()
