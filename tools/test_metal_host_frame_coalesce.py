import struct
import unittest
from metal_host_frame_coalesce import coalesce,commands
from metal_host_draw_validate import Packet


class CoalescingTests(unittest.TestCase):
    @staticmethod
    def program(sequence):
        p=Packet(sequence)
        p.command(struct.pack('<10I',7,40,10000+sequence,1,1,0,3,0,5,1),[(20,b'abc'),(28,b'defgh')])
        return p.finish()

    def test_offsets_realign_and_semantics_stay_identical(self):
        first=Packet(1);first.command(struct.pack('<4I',14,16,20000,1))
        original=[first.finish(),self.program(2),self.program(3)]
        merged,mapping=coalesce(original)
        _,records=commands(merged)
        expected=[r['identity'] for packet in original for r in commands(packet)[1]]
        self.assertEqual([r['identity'] for r in records],expected)
        self.assertEqual(len(mapping),3)
        # Each rebuilt payload is aligned relative to the combined packet.
        for r in records:
            if r['opcode']==7:
                for field in (20,28):self.assertEqual(struct.unpack_from('<I',merged,r['old_offset']+field)[0]%16,0)
        self.assertNotEqual(merged,original[0]+original[1][24:]+original[2][24:])

    def test_outside_command_payload_rejects(self):
        p=bytearray(self.program(1));struct.pack_into('<I',p,24+20,len(p))
        with self.assertRaisesRegex(ValueError,'outside command'):commands(p)

    def test_nonzero_hidden_padding_rejects(self):
        p=bytearray(self.program(1));p[struct.unpack_from('<I',p,24+20)[0]+3]=1
        with self.assertRaisesRegex(ValueError,'hidden payload padding'):commands(p)

    def test_unknown_operation_rejects(self):
        p=Packet(1);p.command(struct.pack('<2I',999,8))
        with self.assertRaisesRegex(ValueError,'Unknown'):commands(p.finish())

    def test_noncontiguous_sequences_reject(self):
        with self.assertRaisesRegex(ValueError,'contiguous'):coalesce([self.program(1),self.program(3)])

    def test_later_upload_rejects(self):
        p=Packet(2);p.command(struct.pack('<12I',3,48,1,1,0,0,1,1,4,0,4,0),[(36,b'abcd')])
        with self.assertRaisesRegex(ValueError,'initial resource uploads'):coalesce([self.program(1),p.finish()])


if __name__=='__main__':unittest.main()
