import unittest

import metal_alpha_border_validate as alpha


class AlphaBorderReferenceTests(unittest.TestCase):
    def test_bc2_nibbles_and_rows_are_independent_of_port_decoder(self):
        raw=sum(n<<(4*n) for n in range(16)).to_bytes(8,'little')+bytes(8)
        result=alpha.decode_alpha(raw,4)
        self.assertEqual(result,[[0,17,34,51],[68,85,102,119],[136,153,170,187],[204,221,238,255]])
        with self.assertRaises(ValueError):alpha.decode_alpha(raw[:-1],4)

    def test_hand_calculated_boundary_with_alpha70(self):
        image=[[34,34],[102,102]]
        self.assertEqual(alpha.alpha_reference(image,0,0),61)
        self.assertEqual(alpha.alpha_reference(image,0,.25),52)
        self.assertEqual(alpha.alpha_reference(image,0,.5),69)
        self.assertEqual(alpha.alpha_reference(image,-1,.5),70)

    def test_repeat_axis_does_not_acquire_border(self):
        image=[[34,34],[102,102]]
        self.assertEqual(alpha.alpha_reference(image,.5,-1,1),68)
        self.assertEqual(alpha.alpha_reference(image,-1,.25,2),34)

    def test_original_byte_alpha_threshold_rounding(self):
        self.assertEqual([alpha.quantize(v) for v in (68.49,68.5,70.49,70.5)],[68,69,70,71])
        self.assertFalse(alpha.compare_alpha(70,2,70))
        self.assertTrue(alpha.compare_alpha(70,3,70))
        self.assertFalse(alpha.compare_alpha(70,5,70))
        self.assertTrue(alpha.compare_alpha(70,7,70))

    def test_policy_and_authored_asset_matrix(self):
        records=alpha.records()
        self.assertEqual(len(records),108)
        for policy in (False,True):
            subset=[r for r in records if r['fast']==policy]
            self.assertEqual({r['lod'] for r in subset if r['kind']=='authored'},set(range(5)))
            self.assertEqual({r['texture'] for r in subset if r['kind']=='authored'},{1,2})
            self.assertEqual({r['reference'] for r in subset if r['kind']=='threshold'},{68,69,70,71})
            self.assertEqual({r['blend'] for r in subset if r['kind']=='blend'},{'sweep','mask'})


if __name__=='__main__':unittest.main()
