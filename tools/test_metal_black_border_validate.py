"""Hand-calculated borders and exact-byte fixture invariants, no GPU needed."""
import unittest

import metal_black_border_validate as border


class BlackBorderReferenceTests(unittest.TestCase):
    def test_hand_calculated_linear_boundary_and_corners(self):
        self.assertEqual(border.reference(0,.5,0,True,3),bytes((32,64,96,96)))
        self.assertEqual(border.reference(0,0,0,True,3),bytes((16,32,48,48)))
        self.assertEqual(border.reference(1,1,0,True,3),bytes((16,32,48,48)))
        self.assertEqual(border.reference(.25/32,.5,0,True,3),bytes((48,96,144,144)))
        self.assertEqual(border.reference(-.5/32,.5,0,True,3),bytes(4))

    def test_nearest_texel_range_is_half_open(self):
        self.assertEqual(border.reference(0,0,0,False,3),bytes((64,128,192,192)))
        self.assertEqual(border.reference(1,.5,0,False,3),bytes(4))
        self.assertEqual(border.reference(-1/64,.5,0,False,3),bytes(4))

    def test_fractional_mip_interpolation_after_border(self):
        self.assertEqual(border.reference(0,0,.5,True,3),bytes((24,40,32,48)))
        self.assertEqual(border.reference(.5,.5,.5,True,3),bytes((96,160,128,192)))

    def test_other_axis_repeats_without_border(self):
        self.assertEqual(border.reference(.5,-4,0,True,1),bytes((64,128,192,192)))
        self.assertEqual(border.reference(-4,.5,0,True,2),bytes((64,128,192,192)))

    def test_authored_levels_and_derivative_cases_are_distinct(self):
        records=border.cases()
        self.assertEqual(len(records),30)
        self.assertEqual({r['lod'] for r in records if r['grid']=='fringe' and r['anisotropy']==1 and r['axes']==3},set(range(6)))
        self.assertEqual([r['lod'] for r in records if r['grid']=='derivative'],[1.,2.,3.])
        self.assertEqual(len(set(border.COLORS)),6)


if __name__=='__main__':unittest.main()
