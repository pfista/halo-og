import struct
import unittest
from fractions import Fraction as Q
import metal_volume_colour_validate as v

class VolumeColourOracleTests(unittest.TestCase):
    def test_arbitrary_colour_outside_all_axes(self):
        levels=v.volume.linear_levels();rgba=(5,37,91,203)
        for axis in range(3):
            for edge in (-1,2):
                coord=[Q(1,2)]*3;coord[axis]=Q(edge)
                self.assertEqual(v.expected(levels,3,coord,rgba),bytes(rgba))

    def test_independent_eight_voxel_border_corner(self):
        levels=[bytes((0,64,128,192))*(32>>n)**3 for n in range(6)]
        rgba=(64,128,192,0)
        self.assertEqual(v.expected(levels,0,(Q(0),)*3,rgba),bytes((56,120,184,24)))
        self.assertEqual(v.expected(levels,0,(Q(1,64),)*3,rgba),bytes((0,64,128,192)))

    def test_two_mip_quarter_blend(self):
        levels=v.volume.linear_levels()
        self.assertEqual(v.expected(levels,Q(1,4),(Q(1,2),)*3,(64,96,160,192)),bytes((96,32,128,128)))

    def test_half_ties_are_explicit_separate_gate(self):
        levels=[bytes(4)*(32>>n)**3 for n in range(6)]
        with self.assertRaises(ValueError):v.expected(levels,0,(Q(0),Q(1,2),Q(1,2)),(5,5,5,5))
        self.assertEqual(v.expected(levels,0,(Q(0),Q(1,2),Q(1,2)),(5,5,5,5),integer_only=False),bytes([3]*4))

    def test_point_nearest_quarter_mip(self):
        levels=v.volume.linear_levels()
        for lod,n in ((Q(1,4),0),(Q(3,4),1),(Q(17,4),4),(Q(19,4),5)):
            self.assertEqual(v.expected(levels,lod,(Q(1,2),)*3,(5,5,5,5),linear=False,mip_linear=False),levels[n][:4])

    def test_wire_preserves_original_payload_field_offsets(self):
        fixed,payloads=v.extended_draw(35,1,11,4,(Q(1,4),)*3,stage=2,program=114)
        self.assertEqual(len(fixed),424)
        self.assertEqual(struct.unpack_from('<2I',fixed), (21,424))
        self.assertEqual(struct.unpack_from('<2I',fixed,416),(4,0))
        self.assertEqual(struct.unpack_from('<2I',fixed,48),(11,1))
        self.assertEqual([p[0] for p in payloads],[392,396,400,404])
        self.assertEqual([len(p[1]) for p in payloads],[1024,24,3120,608])
        self.assertEqual(struct.unpack_from('<4f',payloads[-2][1]),(.5,.5,.5,2.))

    def test_source_asset_decode_and_channels(self):
        levels=v.volume.decode_authored()
        self.assertEqual([len(x) for x in levels],[4*(32>>n)**3 for n in range(6)])
        self.assertNotEqual(v.volume.synthetic(4,1)[:4],v.volume.synthetic(4,1)[4:8])

if __name__=='__main__':unittest.main()
