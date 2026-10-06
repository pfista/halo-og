"""CPU/oracle/packet checks for the independent unequal-attachment proof."""
import json,struct,subprocess,tempfile,unittest
from pathlib import Path
import metal_unequal_attachment_validate as subject
class UnequalAttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.f=subject.fixture()
    def test_original320x240clear_metadata_and_primary_resource_identity(self):
        p=self.f.packets[1]['data'];self.assertEqual(struct.unpack_from('<2I',p,24),(17,80))
        self.assertEqual(struct.unpack_from('<10I',p,32),(10,1,12,1,7,0,0,320,240,0))
        self.assertEqual(struct.unpack_from('<2I',p,96),(15,0))
        original_draw=self.f.packets[2]['data'];primary=self.f.packets[3]['data']
        self.assertEqual(struct.unpack_from('<2I',original_draw,48),(12,1))
        self.assertEqual(struct.unpack_from('<2I',primary,48),(12,1))
    def test_analytical_outside_depth_and_stencil_are_unchanged_then_alias_controls_primary(self):
        r=self.f.readbacks
        before=r[2]['data'];after=next(x['data'] for x in r if x['label']=='mirror clear outside depth preserved')
        final=next(x['data'] for x in r if x['label']=='primary alias baseline' and x['plane']==2)
        for x,y in ((320,0),(0,240),(639,479),(480,350)):
            o=(y*640+x)*4;self.assertEqual(before[o:o+4],after[o:o+4]);self.assertEqual(before[o:o+4],final[o:o+4])
        for x,y,z in ((1,1,.75),(50,50,.5),(300,230,.75)):
            self.assertEqual(struct.unpack_from('<f',final,(y*640+x)*4)[0],z)
        primary_before=r[1]['data'];primary_after=next(x['data'] for x in r if x['label']=='primary alias baseline' and x['target_id']==11)
        self.assertEqual(primary_after[0:4],bytes((200,44,90,255)))
        o=(50*640+50)*4;self.assertEqual(primary_before[o:o+4],primary_after[o:o+4])
        self.assertEqual(primary_before[(479*640+639)*4:][:4],primary_after[(479*640+639)*4:][:4])
    def test_raw_constant_bank_bytes_are_not_converted_and_native_controls_still_reject(self):
        p=self.f.packets[2]['data'];offset=struct.unpack_from('<I',p,24+400)[0]
        for byte,bits in ((0,0x7f800000),(380,0xffffffff),(3068,0xff800000)):
            self.assertEqual(struct.unpack_from('<I',p,offset+byte)[0],bits)
        self.assertEqual(p[offset+3072:offset+3120],bytes(48))
        self.assertEqual(len(self.f.negative),7)
        self.assertEqual(len(self.f.readbacks),45)
        for read in self.f.readbacks[14:42]:self.assertEqual(read['sequence'],4)
    def test_every_late_rejection_has_prior_clear_and_same_actual_baseline_bytes_versions(self):
        baseline=self.f.readbacks[10:14]
        for i,packet in enumerate(self.f.packets[4:11]):
            b=packet['data'];self.assertEqual(packet['failed_command'],1)
            opcode,size=struct.unpack_from('<2I',b,24);self.assertEqual((opcode,size),(17,80))
            self.assertEqual(struct.unpack_from('<4f',b,24+48),(1,0,1,1))
            for n in range(4):
                read=self.f.readbacks[14+i*4+n];self.assertEqual(read['data'],baseline[n]['data']);self.assertEqual(read['version'],baseline[n]['version'])
    def test_source_extracted_finite_scan_preserves_raw_bank_and_checks_every_control_word(self):
        root=subject.ROOT;source=(root/'port/macos/host/host_metal.mm').read_text()
        # Only the production failure/check helpers belong in this C++ probe;
        # sampler caches and host metrics have separate ABI dependencies.
        failure=source[source.index('struct Failure {'):source.index('\n',source.index('struct Failure {'))+1]
        checks=failure+source[source.index('void check_at('):source.index('struct Texture {')]
        finite=source[source.index('    // Packed input registers'):source.index('    auto &p = program(programs,c.program);')]
        cpp='''#include <cmath>\n#include <cstring>\n#include <cstdint>\n#include <vector>\n#include <utility>\nconstexpr int HALO_METAL_INVALID=-1,HOST_LOG_ERROR=1;\nconstexpr uint32_t HaloMetalVertexStride=256,HaloMetalVertexUniformSize=3120,HaloMetalPixelUniformSize=608;\nvoid host_logf(int,const char*,...){}\n'''+checks+'''\nstruct C {uint32_t vertex_count=1,packed_mask=0,vertices_offset=0,vertex_uniforms_offset=256,pixel_uniforms_offset=3376;};\nvoid scan(const std::vector<uint8_t>&packet,C c){\n'''+finite+'''\n}\nint main(){C c;std::vector<uint8_t>p(3984);const uint32_t bad[]={0xffffffff,0x7fc00001,0xffc00001,0x7f800001,0xff800001,0x7f800000,0xff800000,0x7fffffff};unsigned positives=0,negative=0;\nfor(unsigned offset=0;offset<3072;offset+=4)for(uint32_t bits:bad){memcpy(p.data()+256+offset,&bits,4);auto before=p;try{scan(p,c);}catch(Failure){return 1;}if(p!=before)return 2;memset(p.data()+256+offset,0,4);positives++;}\nfor(unsigned offset=3072;offset<3120;offset+=4)for(uint32_t bits:bad){memcpy(p.data()+256+offset,&bits,4);try{scan(p,c);return 3;}catch(Failure f){if(f.status!=-1||f.index!=UINT32_MAX)return 4;}memset(p.data()+256+offset,0,4);negative++;}\nfor(unsigned offset=0;offset<608;offset+=4)for(uint32_t bits:bad){memcpy(p.data()+3376+offset,&bits,4);try{scan(p,c);return 5;}catch(Failure f){if(f.status!=-1||f.index!=UINT32_MAX)return 6;}memset(p.data()+3376+offset,0,4);negative++;}\nreturn positives==6144&&negative==1312?0:7;}\n'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'scan.cpp').write_text(cpp)
            subprocess.run(['clang++','-std=c++17','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer','-Wall','-Wextra','-Werror',str(path/'scan.cpp'),'-o',str(path/'scan')],check=True,capture_output=True)
            subprocess.run([str(path/'scan')],check=True,capture_output=True)
if __name__=='__main__':unittest.main()
