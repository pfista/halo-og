"""Transport preparation regressions independent of game/GPU execution."""
import copy
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from metal_host_draw_validate import fetch_attribute,geometry,state_bytes,wire_packet,rejection_packet


class HostDrawPreparationTests(unittest.TestCase):
    def test_fetch_preserves_raw_packed_bits_fixed_defaults_and_normalized_endpoints(self):
        packed=struct.pack('<I',0x7fc00001) # A valid raw uint pattern that is NaN if misinterpreted as float.
        self.assertEqual(fetch_attribute(packed,0x16),packed+struct.pack('<3f',0,0,1))
        self.assertEqual(fetch_attribute(struct.pack('<2h',-32768,32767),0x21),struct.pack('<4f',-1,1,0,1))
        self.assertEqual(fetch_attribute(bytes([0,255,127,64]),0x40),
                         struct.pack('<4f',127/255,1,0,64/255))
        with self.assertRaisesRegex(ValueError,'Unknown/truncated'):
            fetch_attribute(packed,0x36)
        with self.assertRaisesRegex(ValueError,'Nonfinite'):
            fetch_attribute(packed,0x12)

    def test_actual_wire_preserves_stream_windows_and_keeps_expected_buffers_outside_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,data):
                (root/name).write_bytes(data)
                return dict(file=name,size=len(data),sha256=hashlib.sha256(data).hexdigest())
            fixed=struct.pack('<64f',*([.25,.5,.75,1]*16))
            raw=b''.join(struct.pack('<3fI',float(i),float(i+1),float(i+2),0x7fc00001+i)
                         for i in range(3))
            manifest={'target':dict(width=8,height=8,color_format='bgra8unorm',depth_format='depth32float_stencil8',
                orientation='top_left',clear_color=[0,0,0,0],clear_depth=1.,clear_stencil=0),
                'fixed_attributes':write('fixed.bin',fixed),
                'vertex_streams':[dict(write('stream.bin',raw),stream=0,stride=16,offset=0,first_vertex=10)],
                'vertex_declaration':dict(packed_mask=2,elements=[dict(register=0,stream=0,offset=0,type=0x32),
                    dict(register=1,stream=0,offset=12,type=0x16)]),
                'draw':dict(indexed=True,index_buffer=write('indices.bin',struct.pack('<3H',10,11,12)),
                    index_type='uint16',index_count=3,index_offset_bytes=0,base_vertex=0,primitive='triangle'),
                'shaders':dict(vertex=dict(write('vs.metal',b'actual vertex source placeholder'),entry='xgpu_vertex'),
                    fragment=dict(write('ps.metal',b'actual fragment source placeholder'),entry='xgpu_fragment')),
                'uniforms':dict(vertex=write('vu.bin',bytes(3120)),pixel=write('pu.bin',bytes(608))),
                'textures':[None]*4,
                'render_state':dict(depth=dict(enabled=True,write=True,compare='less_equal'),
                    stencil=dict(enabled=False,compare='equal',reference=0,read_mask=1,write_mask=0,
                        fail='keep',depth_fail='keep',**{'pass':'keep'}),
                    raster=dict(front_face='cw',cull='back',fill='solid',depth_bias=0.,slope_scale=0.,depth_bias_clamp=0.),
                    blend=dict(enabled=False,source='one',destination='zero',operation='add',write_mask=7),
                    viewport=dict(x=0,y=0,width=8,height=8,znear=0.,zfar=1.),scissor=dict(x=1,y=2,width=6,height=3)),
                'reference':dict(color={'file':'after-target-must-never-be-read.bin','sha256':'0'*64})}
            vertices,indices,mask,primitive,first=geometry(root,manifest)
            self.assertEqual((len(vertices),mask,primitive,first),(768,2,3,10))
            self.assertEqual(indices,struct.pack('<3I',0,1,2))
            for i in range(3):
                self.assertEqual(vertices[i*256:i*256+16],struct.pack('<4f',i,i+1,i+2,1))
                self.assertEqual(vertices[i*256+16:i*256+20],struct.pack('<I',0x7fc00001+i))
                self.assertEqual(vertices[i*256+48:i*256+64],fixed[48:64])
            listed=copy.deepcopy(manifest);listed['fixed_attributes']=[[.25,.5,.75,1] for _ in range(16)]
            self.assertEqual(geometry(root,listed),geometry(root,manifest))
            packet,info=wire_packet(root,manifest)
            self.assertEqual(info['command_count'],5)
            self.assertEqual(struct.unpack_from('<4IQ',packet),(0x4c544d48,1,len(packet),5,1))
            commands=[];offset=24
            while offset<len(packet):
                op,size=struct.unpack_from('<2I',packet,offset)
                self.assertEqual(size%8,0);commands.append((op,offset,size));offset+=size
            self.assertEqual([c[0] for c in commands],[10,10,4,7,9])
            program_offset=commands[-2][1]
            self.assertEqual(struct.unpack_from('<I',packet,program_offset+36)[0],0)
            # Only the named fragment PROGRAM field changes; ordinary draw
            # inputs and legacy safe compiler packets keep their prior bytes.
            from metal_draw_replay import FRAGMENT_FAST_OPTIONS,sha256
            source=root/'policy.mm';source.write_bytes(b'fixed primary compiler source')
            digest=sha256(source.read_bytes())
            evidence=dict(kind='angle_shader_evidence',complete=True,source_revision='c053bf85793b',
                source_files={'policy.mm':dict(file=str(source),sha256=digest)},evidence=dict(
                    compiler_options_inferred_from_pinned_source=dict(disableFastMath=False,usesInvariance_fragment=False,
                        mathMode_ifSDK_andRuntimeMacOS15='Fast',mathFloatingPointFunctions_ifSDK_andRuntimeMacOS15='Fast',legacy_fastMathEnabled=True)))
            import json
            opted=copy.deepcopy(manifest)
            opted['shaders']['fragment'].update(compile_options=dict(FRAGMENT_FAST_OPTIONS),
                compiler_evidence=write('fragment-evidence.json',json.dumps(evidence).encode()),
                compiler_baseline=write('fragment-baseline.glsl',b'void main() { gl_FragColor=vec4(0); }'))
            with patch.dict('metal_draw_replay.PINNED_ANGLE_COMPILER_SOURCES',{'policy.mm':digest},clear=True):
                fast_packet,_=wire_packet(root,opted)
                expected=bytearray(packet);struct.pack_into('<I',expected,program_offset+36,1)
                self.assertEqual(fast_packet,bytes(expected))
                opted['shaders']['fragment']['compile_options']['preserve_invariance']=True
                with self.assertRaisesRegex(ValueError,'Unverified fragment'):wire_packet(root,opted)
            op,offset,size=commands[-1]
            for field,data in ((392,vertices),(396,indices),(400,bytes(3120)),(404,bytes(608))):
                location=struct.unpack_from('<I',packet,offset+field)[0]
                self.assertEqual(location%16,0)
                self.assertEqual(packet[location:location+len(data)],data)
                self.assertLessEqual(location+len(data),offset+size)
            negative,relocated=rejection_packet(packet,8,8)
            self.assertEqual(struct.unpack_from('<4IQ',negative),(0x4c544d48,1,len(negative),2,2))
            self.assertEqual(relocated['draw'],96)
            self.assertEqual(struct.unpack_from('<2I',negative,24),(4,72))
            self.assertEqual(struct.unpack_from('<I',negative,68)[0],165)
            self.assertEqual(struct.unpack_from('<5f',negative,72),(1.,0.,1.,1.,0.))
            # Every actual input payload survives exactly; only offsets and
            # command padding change when the original draw is relocated.
            for field,data in ((392,vertices),(396,indices),(400,bytes(3120)),(404,bytes(608))):
                location=struct.unpack_from('<I',negative,96+field)[0]
                self.assertEqual(location%16,0)
                self.assertEqual(negative[location:location+len(data)],data)
                self.assertGreaterEqual(location,96+416)
            self.assertEqual(negative[104:96+392],packet[offset+8:offset+392])
            self.assertEqual(negative[96+408:96+416],packet[offset+408:offset+416])
            damaged=bytearray(packet);struct.pack_into('<I',damaged,offset+392,offset)
            with self.assertRaisesRegex(ValueError,'payload exceeds'):
                rejection_packet(damaged,8,8)
            without_draw=bytearray(packet[:offset]);struct.pack_into('<2I',without_draw,8,offset,4)
            with self.assertRaisesRegex(ValueError,'does not end'):
                rejection_packet(without_draw,8,8)
            state=state_bytes(manifest['render_state'])
            self.assertEqual(len(state),152)
            self.assertEqual(struct.unpack_from('<3I',state,64),(0,2,0)) # CW/back/clip
            self.assertEqual(struct.unpack_from('<4I',state,104),(1,2,6,3)) # No scissor Y flip
            poisoned=copy.deepcopy(manifest);poisoned['reference']['color']['file']='another-missing-after-target.bin'
            self.assertEqual(wire_packet(root,poisoned)[0],packet)
            bad=copy.deepcopy(manifest);bad['render_state']['blend']['source']='unknown'
            with self.assertRaisesRegex(ValueError,'Unsupported blend source'):
                wire_packet(root,bad)
            bad=copy.deepcopy(manifest);bad['target']['initial_depth']=write('wrong-depth.bin',struct.pack('<64f',*([.5]*64)))
            with self.assertRaisesRegex(ValueError,'independent clear'):
                wire_packet(root,bad)


if __name__=='__main__':unittest.main()
