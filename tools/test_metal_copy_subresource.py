"""CPU guards for the independent GPU copy fixture and oracle."""
import struct
import unittest
import metal_copy_subresource_validate as copy

class CopyFixtureTests(unittest.TestCase):
    def test_coordinate_oracle(self):
        self.assertEqual(copy.pattern(2,0),bytes((11,23,31,255,14,24,38,255,16,24,42,255,19,23,49,255)))
        self.assertEqual(copy.pattern(1,2,1),bytes((213,61,57,255)))
        self.assertEqual(copy.pattern(1,0,bgra=True),bytes((31,23,11,255)))
    def test_partial_preserves_outside(self):
        source=copy.pattern(4,1);destination=copy.pattern(8,2)
        result=copy.copy_region(source,4,destination,8,1,1,3,4,2,2)
        for y in range(8):
            for x in range(8):
                offset=(y*8+x)*4
                expected=source[((y-4+1)*4+x-3+1)*4:((y-4+1)*4+x-3+1)*4+4] if 3<=x<5 and 4<=y<6 else destination[offset:offset+4]
                self.assertEqual(result[offset:offset+4],expected)
    def test_wire_layout(self):
        record=copy.copy(src=13,dst=20,dm=3,size=16)
        self.assertEqual(len(record),72)
        self.assertEqual(struct.unpack_from('<4I',record,24),(0,0,3,0))
        self.assertEqual(struct.unpack_from('<2I',record,64),(1,0))
        fixed,payloads=copy.draw(30,128,101,texture=20)
        self.assertEqual(len(fixed),416)
        self.assertEqual([len(d) for _,d in payloads],[1024,24,3120,608])
    def test_fixture_scopes_and_rejections(self):
        f=copy.fixture()
        self.assertEqual(len(f.negative),25)
        self.assertEqual(f.composite_versions,[1,2,3,4,5,6])
        self.assertEqual(len([r for r in f.readbacks if r['label']=='atomic-baseline']),5)
        self.assertEqual(len([a for a in f.actions if a[0]==4 and a[9]==2]),125)
        self.assertEqual([n['failed_command'] for n in f.negative],[5]*25)
        # Only one deliberately rejected prefix uploads a small marker.
        # No analytic expected destination buffer is part of the immutable GPU inputs.
        for r in f.readbacks:
            if r['label'].startswith('initial-composite/'):
                self.assertNotIn(bytes.fromhex(r['expected']),f.inputs)

if __name__=='__main__':unittest.main()
