import unittest
import metal_volume_validate as volume
from fractions import Fraction

class VolumeTests(unittest.TestCase):
    def test_asymmetric_axes_channels(self):
        data=volume.synthetic(4,0)
        self.assertEqual(data[:4],bytes((16,32,48,224)))
        self.assertEqual(data[4:8],bytes((32,64,96,224)))
        self.assertEqual(data[16:20],bytes((48,48,112,224)))
        self.assertEqual(data[64:68],bytes((64,96,64,224)))
    def test_independent_morton_source(self):
        self.assertEqual([volume.morton(*xyz) for xyz in ((0,0,0),(1,0,0),(0,1,0),(0,0,1),(1,1,1),(2,0,0))],[0,1,2,4,7,8])
        mips=volume.decode_authored()
        self.assertEqual([len(m) for m in mips],[131072,16384,2048,256,32,4])
        self.assertTrue(all(m[i:i+4]==bytes([m[i]])*4 for m in mips for i in range(0,len(m),4)))
    def test_pitched_partial_box(self):
        data=volume.partial_data()
        self.assertEqual(len(data),80)
        self.assertEqual(data[:4],bytes((208,112,64,224)))
        self.assertEqual(data[12:20],bytes([0xcd])*8)
        self.assertEqual(data[48:52],bytes((192,112,64,224)))
        original=volume.synthetic(8,2);changed=volume.partial_expected(original)
        for z in range(8):
            for y in range(8):
                for x in range(8):
                    p=((z*8+y)*8+x)*4
                    expected=data[(z-1)*48+(y-3)*20+(x-2)*4:(z-1)*48+(y-3)*20+(x-2)*4+4] if 1<=z<3 and 3<=y<5 and 2<=x<5 else original[p:p+4]
                    self.assertEqual(changed[p:p+4],expected)
    def test_exact_xyz_border_and_mip_weights(self):
        levels=volume.linear_levels();origin=(Fraction(0),)*3
        self.assertEqual(volume.linear_oracle(levels,0,origin),bytes((16,0,16,16)))
        self.assertEqual(volume.linear_oracle(levels,Fraction(1,4),origin),bytes((12,4,16,16)))
        self.assertEqual(volume.linear_oracle(levels,Fraction(1,2),origin),bytes((8,8,16,16)))
        self.assertEqual(volume.linear_oracle(levels,Fraction(3,4),origin),bytes((4,12,16,16)))
        fringe=(-Fraction(1,128),Fraction(0),Fraction(0))
        self.assertEqual(volume.linear_oracle(levels,0,fringe),bytes((8,0,8,8)))
        self.assertEqual(volume.linear_oracle(levels,Fraction(1,4),fringe),bytes((6,3,9,9)))
    def test_complete_fixture_no_expected_gpu_seeds(self):
        f=volume.fixture()
        self.assertEqual(len(f.negative),29)
        self.assertEqual(len([r for r in f.readbacks if r['label'].startswith('authored-original/')]),63)
        self.assertEqual(len([r for r in f.readbacks if r['label'].startswith('authored-all-linear/')]),63)
        self.assertEqual(len([r for r in f.readbacks if r['label'].startswith('synthetic/')]),63)
        self.assertEqual(len([r for r in f.readbacks if r['label'].startswith('authored-black-border/')]),36)
        self.assertEqual([n['failed_command'] for n in f.negative],[6]*29)
        self.assertEqual(len([a for a in f.actions if a[0]==4 and a[9]==2]),145)
        self.assertTrue(any(r['label']=='projected-coordinate-q-division' for r in f.readbacks))
        self.assertEqual(len([r for r in f.readbacks if r['label'].startswith('generated-project3d/')]),27)

if __name__=='__main__':unittest.main()
