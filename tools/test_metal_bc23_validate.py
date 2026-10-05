"""Independent known blocks and transport preservation for BC2/BC3 fixtures."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest

from metal_bc23_validate import block,fixture
from metal_host_draw_validate import wire_packet


class BC23FixtureTests(unittest.TestCase):
    def test_bc2_alpha_nibbles_and_bc3_known_endpoint_modes(self):
        encoded,pixels,exact=block(0,0,0,0)
        self.assertEqual(encoded[:8],bytes.fromhex('1032547698badcfe'))
        self.assertEqual([p[3] for p in pixels],[i*17 for i in range(16)])
        self.assertTrue(all(mask[1] for mask in exact))
        # Hand-calculated byte values from the published rounded alpha tables.
        palettes=((249,13,[249,13,215,182,148,114,80,47]),
                  (11,243,[11,243,57,104,150,197,0,255]),
                  (128,128,[128,128,128,128,128,128,0,255]),
                  (255,0,[255,0,219,182,146,109,73,36]),
                  (0,255,[0,255,51,102,153,204,0,255]))
        for variant,(a0,a1,palette) in enumerate(palettes):
            encoded,pixels,exact=block(1,0,variant,0)
            self.assertEqual(encoded[:2],bytes((a0,a1)))
            selectors=[(int.from_bytes(encoded[2:8],'little')>>(i*3))&7 for i in range(16)]
            self.assertEqual(set(selectors),set(range(8)))
            self.assertEqual([p[3] for p in pixels],[palette[s] for s in selectors])
            if a0<=a1:
                self.assertTrue(all(exact[i][1] for i,s in enumerate(selectors) if s in (0,1,6,7)))
        encoded,pixels,_=block(1,0,1,0)
        self.assertEqual(struct.unpack_from('<2H',encoded,8),(0,0x07e0))
        self.assertIn(bytes((0,85,0,57)),pixels) # Reversed RGB endpoints still use four-color interpolation.

    def test_wire_retains_all_authored_block16_mips_and_rejects_unverified_cubes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);manifest=fixture(folder);packet,info=wire_packet(folder,manifest)
            self.assertEqual(info['command_count'],17)
            creates={};uploads={};offset=24
            while offset<len(packet):
                opcode,size=struct.unpack_from('<2I',packet,offset)
                if opcode==10:
                    fields=struct.unpack_from('<12I',packet,offset);creates[fields[2]]=fields
                elif opcode==11:
                    fields=struct.unpack_from('<18I',packet,offset);data=packet[fields[14]:fields[14]+fields[15]]
                    uploads[fields[2],fields[4]]=(fields,data)
                offset+=size
            for slot,format_id in ((0,5),(1,6)):
                self.assertEqual(creates[10+slot][4:11],(format_id,16,16,1,1,5,1))
                for level,mip in enumerate(manifest['textures'][slot]['mipmaps']):
                    fields,data=uploads[10+slot,level]
                    self.assertEqual(fields[5:12],(0,0,0,0,mip['width'],mip['height'],1))
                    self.assertEqual(fields[12:14],(mip['bytes_per_row'],mip['bytes_per_image']))
                    self.assertEqual(len(data),max(1,(mip['width']+3)//4)**2*16)
                    self.assertEqual(data,(folder/mip['file']).read_bytes())
            for slot in (0,1):
                cube=copy.deepcopy(manifest);cube['textures'][slot]['type']='cube'
                with self.assertRaisesRegex(ValueError,'cube transport has not been validated'):
                    wire_packet(folder,cube)


if __name__=='__main__':unittest.main()
