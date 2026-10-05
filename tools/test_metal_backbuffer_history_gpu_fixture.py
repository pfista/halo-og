#!/usr/bin/env python3
"""CPU guards for immutable original-history fixture preparation; no GPU use."""
import struct
import unittest
import metal_backbuffer_history_validate as h


class HistoryFixtureTests(unittest.TestCase):
    def test_original_program_and_payloads_retained(self):
        program, (fixed,payloads), records = h.loading_route()
        self.assertEqual(program,records[2])
        original=bytearray(records[3]['fixed'])
        for field in (32,40,48,56): struct.pack_into('<2I',original,field,3,1)
        self.assertEqual(fixed,bytes(original))
        self.assertEqual(payloads,records[3]['payloads'])

    def test_depth_only_clear_has_no_color_reference(self):
        c=h.clear(0,depth=2)
        self.assertEqual(struct.unpack_from('<5I',c,8),(0,0,2,1,6))

    def test_rectangular_sampling_state(self):
        fixed,payloads=h.sample_draw(4,3,24,8)
        self.assertEqual(struct.unpack_from('<2f',fixed,312),(24.,8.))
        self.assertEqual(struct.unpack_from('<4I',fixed,328),(0,0,24,8))
        self.assertEqual(struct.unpack_from('<4f',fixed,344),(0.,0.,0.,0.))
        self.assertEqual(struct.unpack_from('<2f',dict(payloads)[404]),(24.,8.))

    def test_initial_images_are_distinct_recognizable(self):
        a,b=h.image(64,64),h.image(64,64,1)
        self.assertNotEqual(a,b)
        self.assertNotEqual(a[:4],a[32*4:33*4])
        self.assertEqual(a[:4],bytes((48,32,16,255)))

    def test_control_scopes_and_atomicity_are_present(self):
        f=h.fixture();labels={r['label'] for r in f.readbacks}
        self.assertIn('actual-program54-retained-history-after-current-clear',labels)
        self.assertIn('actual-program54-cleared-history',labels)
        self.assertIn('synthetic-cached-shape-reuse-clear-before-overlap',labels)
        self.assertEqual(f.negative,[dict(label='late-invalid-copy-after-current-clear-and-history-copy',status=-1,failed_command=2)])
        self.assertEqual(sum(r['label']=='actual-atomic-rollback' for r in f.readbacks),5)
        # Every upload is an independent initial image; all later history
        # images derive from op20, clears or draws, never expected-after bytes.
        uploads=[]
        for p in f.packets:
            data=bytes.fromhex(p['bytes']);cursor=24
            while cursor<len(data):
                opcode,extent=struct.unpack_from('<2I',data,cursor)
                if opcode==11:
                    id=struct.unpack_from('<I',data,cursor+8)[0]
                    offset,size=struct.unpack_from('<2I',data,cursor+56)
                    uploads.append((id,data[offset:offset+size]))
                cursor+=extent
            self.assertEqual(cursor,len(data))
        self.assertEqual(uploads,[(1,h.image(640,480,1)),(3,h.image(640,480)),(10,h.image(16,8))])


if __name__=='__main__': unittest.main()
