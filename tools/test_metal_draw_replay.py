#!/usr/bin/env python3
"""Byte/layout regressions for captured draw import, without a GPU or game."""
from pathlib import Path
import copy
import json
import struct
import tempfile
import unittest
from unittest.mock import patch

from metal_draw_replay import (Package, convert_texel, sampler_state, sha256,
                               split_uniforms, texture_description, texture_mipmaps, prepare,
                               freeze_raw_capture, pixel_depth_contract, fragment_compile_contract,
                               fragment_wire_contract, FRAGMENT_FAST_OPTIONS)
from metal_shader_validate import PixelKey


def header(fmt, width_exp, height_exp, levels):
    return 2 << 4 | fmt << 8 | levels << 16 | width_exp << 20 | height_exp << 24


class ReplayImportTests(unittest.TestCase):
    def test_fragment_policy_is_per_key_fail_closed_and_source_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); output=folder/'output'; output.mkdir()
            policy_source=folder/'pinned-policy.mm'; policy_source.write_bytes(b'fixed primary policy source')
            digest=sha256(policy_source.read_bytes())
            evidence=dict(kind='angle_shader_evidence',complete=True,source_revision='c053bf85793b',
                source_files={'policy.mm':dict(file=str(policy_source),sha256=digest)},
                evidence=dict(compiler_options_inferred_from_pinned_source=dict(disableFastMath=False,
                    usesInvariance_fragment=False,usesInvariance_vertex=True,
                    mathMode_ifSDK_andRuntimeMacOS15='Fast',
                    mathFloatingPointFunctions_ifSDK_andRuntimeMacOS15='Fast',legacy_fastMathEnabled=True)))
            evidence_path=folder/'evidence.json'; evidence_path.write_text(json.dumps(evidence))
            package=Package(folder,output)
            class Library: nv2a_pixel_shader_to_glsl=object()
            original_glsl='void main() { gl_FragColor=vec4(0.25); }'
            with patch.dict('metal_draw_replay.PINNED_ANGLE_COMPILER_SOURCES',{'policy.mm':digest},clear=True):
                with patch('metal_draw_replay.generated',return_value=original_glsl) as emitter:
                    options,proof,baseline=fragment_compile_contract(Library(),PixelKey(),evidence_path,package)
                emitter.assert_called_once()
                self.assertEqual(options,FRAGMENT_FAST_OPTIONS)
                self.assertIs(options['preserve_invariance'],False)
                self.assertEqual((output/baseline['file']).read_text(),original_glsl)
                self.assertEqual(package.hashes[str(policy_source)],digest)
                description=dict(compile_options=options,compiler_evidence=proof,compiler_baseline=baseline)
                loader=lambda d:(output/d['file']).read_bytes()
                self.assertEqual(fragment_wire_contract({},loader),0)
                self.assertEqual(fragment_wire_contract(description,loader),1)
                for policy in (None,False,0,[],dict(options,unknown_option=True),dict(options,contract='unknown')):
                    with self.subTest(policy=policy), self.assertRaisesRegex(ValueError,'policy'):
                        fragment_wire_contract(dict(description,compile_options=policy),loader)
                with self.assertRaisesRegex(ValueError,'explicit contract'):
                    fragment_wire_contract(dict(compiler_evidence=proof),loader)
                for flag in ('isnan','isinf','invariant'):
                    with patch('metal_draw_replay.generated',return_value=original_glsl+flag), self.assertRaisesRegex(ValueError,'flags'):
                        fragment_compile_contract(Library(),PixelKey(),evidence_path,package)
                for field,value in [('usesInvariance_fragment',True),('disableFastMath',True),('disableFastMath',0)]:
                    bad=copy.deepcopy(evidence);bad['evidence']['compiler_options_inferred_from_pinned_source'][field]=value
                    evidence_path.write_text(json.dumps(bad))
                    with patch('metal_draw_replay.generated',return_value=original_glsl), self.assertRaisesRegex(ValueError,'noninvariant fast'):
                        fragment_compile_contract(Library(),PixelKey(),evidence_path,package)
                evidence_path.write_text(json.dumps(evidence))
                bad=copy.deepcopy(description);bad['compile_options']['preserve_invariance']=0
                with self.assertRaisesRegex(ValueError,'policy'):fragment_wire_contract(bad,loader)
                bad=copy.deepcopy(description);bad.pop('compiler_baseline')
                with self.assertRaisesRegex(ValueError,'Missing pinned'):fragment_wire_contract(bad,loader)
                policy_source.write_bytes(b'stale policy source')
                with self.assertRaisesRegex(ValueError,'stale or unknown'):fragment_wire_contract(description,loader)

    def test_uniform_packing_preserves_float_bits_and_padding(self):
        constants = struct.pack('<768f', *[float(i)-384 for i in range(768)])
        draw = bytearray(struct.pack('<159f', *[float(i)+.25 for i in range(159)]))
        # Preserve negative zero, which cannot be reconstructed by JSON's
        # semantic float comparisons or arithmetic conversion.
        draw[616:620] = bytes.fromhex('00000080')
        vertex, pixel = split_uniforms(constants, bytes(draw))
        self.assertEqual(len(vertex), 3120)
        self.assertEqual(vertex[:3072], constants)
        self.assertEqual(vertex[3072:3108], draw[:36])
        self.assertEqual(vertex[3108:3112], bytes.fromhex('00000080'))
        self.assertEqual(vertex[3112:], bytes(8))
        self.assertEqual(len(pixel), 608)
        self.assertEqual(pixel[:324], draw[36:360])
        self.assertEqual(pixel[324:336], bytes(12))
        self.assertEqual(pixel[336:592], draw[360:616])
        self.assertEqual(pixel[592:], draw[620:636])
        with self.assertRaises(ValueError):
            split_uniforms(constants[:-4], bytes(draw))

    def test_authored_compressed_mips_are_not_decoded_or_regenerated(self):
        description = texture_description(header(12, 3, 2, 3), 0)
        raw = bytes(range(32))
        levels = texture_mipmaps(raw+b'alignment', description)
        self.assertEqual([(m['width'], m['height'], m['source_offset'], m['source_size'])
                          for m in levels], [(8, 4, 0, 16), (4, 2, 16, 8), (2, 1, 24, 8)])
        self.assertEqual(b''.join(m['data'] for m in levels), raw)
        self.assertTrue(all(m['pixel_format'] == 'bc1_rgba' for m in levels))
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            texture_mipmaps(raw[:-1], description)

    def test_depth_replace_uses_original_target_not_angle_backing(self):
        key = PixelKey(); key.texture_modes = 0x54421
        capture = dict(pixel_depth_contract=dict(version=1, kind='xbox_raw_d24'),
                       original_depth_request=dict(auto_depth_stencil_format=42,
                           actual_port_surface_format_word=0x2e21, floating_point_zbuffer_byte=0),
                       render_state=dict(viewport=dict(znear=.25, zfar=.75)))
        contract = pixel_depth_contract(capture, key)
        self.assertEqual(contract['raw_range'], 16777215)
        vertex, pixel = split_uniforms(bytes(3072), bytes(636), contract)
        self.assertEqual(len(pixel), 608)
        self.assertEqual(struct.unpack('<3f', pixel[324:336]),
                         (struct.unpack('<f', struct.pack('<f', 1 / 16777215))[0], .25, .75))
        for field, value in (('auto_depth_stencil_format', 43), ('auto_depth_stencil_format', 40),
                             ('actual_port_surface_format_word', 0x2f21),
                             ('actual_port_surface_format_word', None),
                             ('floating_point_zbuffer_byte', 1), ('floating_point_zbuffer_byte', False)):
            bad = copy.deepcopy(capture); bad['original_depth_request'][field] = value
            with self.assertRaisesRegex(ValueError, 'integer D24'):
                pixel_depth_contract(bad, key)
        bad = copy.deepcopy(capture); bad.pop('pixel_depth_contract')
        with self.assertRaisesRegex(ValueError, 'explicit captured'):
            pixel_depth_contract(bad, key)
        bad = copy.deepcopy(capture); bad['render_state']['viewport']['znear'] = .9
        with self.assertRaisesRegex(ValueError, 'viewport depth bounds'):
            pixel_depth_contract(bad, key)
        key.texture_modes = 1
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            pixel_depth_contract(capture, key)

    def test_rectangular_morton_channels_and_linear_pitch(self):
        # A 2x4 L8 Morton image stores rows0/1 in its first four texels;
        # row-major expected bytes are independently specified here.
        mip = texture_mipmaps(bytes([1, 2, 3, 4, 5, 6, 7, 8]),
                             texture_description(header(0, 1, 2, 1), 0))[0]
        expected = b''.join(bytes([v, v, v, 255]) for v in [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(mip['data'], expected)
        # Linear3x2L8 uses source64-byte pitch but uploads tightly packed RGBA.
        raw = bytes([11, 12, 13])+bytes(61)+bytes([21, 22, 23])+bytes(61)
        mip = texture_mipmaps(raw, texture_description(0x13 << 8 | 0x20, 2 | 1 << 12))[0]
        self.assertEqual(mip['bytes_per_row'], 12)
        self.assertEqual(mip['data'], b''.join(bytes([v, v, v, 255])
                         for v in [11, 12, 13, 21, 22, 23]))

    def test_channel_formats_and_bit_expansion(self):
        self.assertEqual(convert_texel('a8r8g8b8', bytes([10, 20, 30, 40])), (30, 20, 10, 40))
        self.assertEqual(convert_texel('g8b8', bytes([10, 20])), (10, 20, 0, 255))
        # Five-bit8 expands to66 via hardware bit replication, not65 via
        # integer floor(8*255/31). Keep the same raw texture upload meaning.
        self.assertEqual(convert_texel('r5g6b5', struct.pack('<H', 8 << 11)), (66, 0, 0, 255))
        self.assertEqual(convert_texel('a8', b'\x7f'), (255, 255, 255, 127))
        self.assertEqual(convert_texel('al8', b'\x7f'), (127,)*4)
        with self.assertRaisesRegex(ValueError, 'palette'):
            convert_texel('p8', b'\x01')
        palette = bytearray(1024)
        palette[4:8] = bytes([10, 20, 30, 40])
        self.assertEqual(convert_texel('p8', b'\x01', palette), (30, 20, 10, 40))

    def test_cube_faces_keep_authored_mips_alignment_and_morton_restart(self):
        description = texture_description(header(7, 2, 2, 3)|4, 0)
        self.assertTrue(description['cube_map'])
        # Each4x4 XRGB chain is64+16+4 bytes then128-byte face alignment.
        # Distinct face, mip and texel channels make swaps/regeneration visible.
        raw = bytearray()
        for face in range(6):
            raw.extend(b''.join(bytes([index, level, face, 17])
                               for level, count in ((0, 16), (1, 4), (2, 1))
                               for index in range(count)))
            raw.extend(bytes([0xee])*44)
        levels = texture_mipmaps(raw, description)
        self.assertEqual([(m['level'],m['width'],m['height']) for m in levels],
                         [(0,4,4),(1,2,2),(2,1,1)])
        order = [0,1,4,5,2,3,6,7,8,9,12,13,10,11,14,15]
        for face in range(6):
            base = levels[0]['faces'][face]
            self.assertEqual((base['face'],base['source_offset'],base['source_size']),
                             (face,face*128,64))
            self.assertEqual(base['data'], b''.join(bytes([face,0,index,255]) for index in order))
            self.assertEqual(levels[1]['faces'][face]['source_offset'],face*128+64)
            self.assertEqual(levels[1]['faces'][face]['data'],
                             b''.join(bytes([face,1,index,255]) for index in range(4)))
            self.assertEqual(levels[2]['faces'][face]['source_offset'],face*128+80)
            self.assertEqual(levels[2]['faces'][face]['data'],bytes([face,2,0,255]))
        with self.assertRaisesRegex(ValueError,'Truncated captured cube'):
            texture_mipmaps(raw[:-1],description)
        with self.assertRaisesRegex(ValueError,'square'):
            texture_description(header(7,2,1,2)|4,0)
        with self.assertRaisesRegex(ValueError,'square'):
            texture_description(header(0x1e,2,2,1)|4,0)

    def test_actual_bc1_cube_header_preserves_blocks_mips_and_padded_face_pitch(self):
        # Actual original frame420 uses5–8: BC1 64x64, 5 authored levels,
        # 2728 meaningful bytes per face padded to2816 (total16896 bytes).
        description = texture_description(107285549, 0)
        self.assertEqual((description['width'], description['height'], description['levels']), (64,64,5))
        lengths = [2048,512,128,32,8]
        raw = b''.join(b''.join(bytes([face,level,11,22,33,44,55,66])*(length//8)
                               for level,length in enumerate(lengths))+bytes([0xee])*88
                       for face in range(6))
        self.assertEqual(len(raw),16896)
        mips = texture_mipmaps(raw, description)
        for level,mip in enumerate(mips):
            self.assertEqual(mip['pixel_format'],'bc1_rgba')
            self.assertEqual((mip['width'],mip['height']),(64>>level,64>>level))
            for face in mip['faces']:
                start = face['face']*2816+sum(lengths[:level])
                self.assertEqual((face['source_offset'],face['source_size']),(start,lengths[level]))
                self.assertEqual(face['data'],raw[start:start+lengths[level]])
                self.assertEqual(face['bytes_per_row'],[128,64,32,16,8][level])
                self.assertEqual(face['bytes_per_image'],lengths[level])
        with self.assertRaisesRegex(ValueError,'Truncated captured cube'):
            texture_mipmaps(raw[:-1],description)

    def test_p8_uses_exact_palette_for_each_authored_mip(self):
        palette = b''.join(bytes([i,255-i,i//2,i]) for i in range(256))
        raw = bytes([1,2,3,4,5])
        levels = texture_mipmaps(raw,texture_description(header(0x0b,1,1,2),0),palette)
        self.assertEqual(levels[0]['data'],b''.join(bytes([i//2,255-i,i,i]) for i in (1,2,3,4)))
        self.assertEqual(levels[1]['data'],bytes([2,250,5,5]))
        with self.assertRaisesRegex(ValueError,'palette'):
            texture_mipmaps(raw,texture_description(header(0x0b,1,1,2),0),palette[:-1])

    def test_unverified_header_and_sampler_states_reject(self):
        for word in (header(0x08, 1, 1, 1), header(12, 2, 1, 1)|4,
                     header(12, 1, 1, 1)|0x30, header(12, 1, 1, 4)):
            with self.subTest(word=word), self.assertRaises(ValueError):
                texture_description(word, 0)
        state = dict(min_filter=2, mag_filter=2, mip_filter=2,
                     address_u=1, address_v=4, address_w=1,
                     max_mip_level=1, max_anisotropy=4)
        sampler = sampler_state(state, 7, 2)
        self.assertEqual((sampler['address_u'], sampler['address_v']), ('repeat', 'clamp_to_edge'))
        self.assertEqual((sampler['lod_min'], sampler['lod_max'], sampler['max_anisotropy']), (1, 6, 1))
        with self.assertRaisesRegex(ValueError, 'disagree'):
            sampler_state(state, 7, 0)
        with self.assertRaisesRegex(ValueError, 'filter'):
            sampler_state(dict(state, min_filter=5), 7, 2)
        self.assertEqual(sampler_state(dict(state, address_u=5), 7, 2)['address_u'], 'clamp_to_edge')
        self.assertEqual(sampler_state(dict(state, address_w=4), 7, 2, 1)['address_w'], 'clamp_to_edge')
        with self.assertRaisesRegex(ValueError, 'W border'):
            sampler_state(dict(state, address_w=4), 7, 2, 3)
        with self.assertRaisesRegex(ValueError, 'sampler dimension'):
            sampler_state(state, 7, 2, 2)

    def test_payload_hashes_and_paths_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source, output = folder/'source', folder/'output'
            source.mkdir(); output.mkdir()
            raw = b'actual resource'
            (source/'buffer').write_bytes(raw)
            package = Package(source, output)
            descriptor = dict(file='buffer', size=len(raw), sha256=sha256(raw))
            self.assertEqual(package.read(descriptor), raw)
            with self.assertRaisesRegex(ValueError, 'hash'):
                package.read(dict(descriptor, sha256='0'*64))
            with self.assertRaisesRegex(ValueError, 'escapes'):
                package.read(dict(descriptor, file='../outside'))

    def test_prepare_pairs_emitted_stages_with_complete_captured_inputs(self):
        # A minimal test-only capture verifies the package contract. This is
        # not an original-game visual fixture or evidence of renderer parity.
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            corpus, output = folder/'corpus', folder/'replay'
            corpus.mkdir()
            def write(name, value):
                raw = value if isinstance(value, bytes) else json.dumps(value).encode()
                (folder/name).write_bytes(raw)
                return dict(file=name, size=len(raw), sha256=sha256(raw))
            status = dict(schema_version=1, kind='capture', complete=True, frame=42,
                          vertex_count=1, pixel_count=1, use_count=1)
            write('corpus/status.json', status)
            write('corpus/vertex-0000.json', dict(schema_version=1, kind='vertex', id=0,
                  frame=42, instruction_count=1, packed_mask=0, instructions=[0, 0, 0, 1]))
            pixel = dict(schema_version=1, kind='pixel', id=0, frame=42)
            key = PixelKey()
            for name, _ in key._fields_:
                value = getattr(key, name)
                pixel[name] = list(value) if hasattr(value, '__len__') else value
            write('corpus/pixel-0000.json', pixel)
            use = dict(schema_version=1, frame=42, use=0, vertex_id=0, pixel_id=0,
                       program_id=2, declaration_id=2, immediate=0)
            write('corpus/uses.jsonl', (json.dumps(use)+'\n').encode())
            corpus_hashes = {path.name: sha256(path.read_bytes()) for path in corpus.iterdir()}
            state = dict(viewport=dict(x=0, y=0, width=8, height=8, znear=0., zfar=1.),
                scissor=dict(x=0, y=0, width=8, height=8),
                depth=dict(enabled=False, write=False, compare='always'),
                raster=dict(front_face='cw', cull='none', fill='solid', depth_bias=0., slope_scale=0., depth_bias_clamp=0.),
                blend=dict(enabled=False, source='one', destination='zero', operation='add', write_mask=15),
                stencil=dict(enabled=False, compare='always', reference=0, read_mask=255, write_mask=0,
                             fail='keep', depth_fail='keep', **{'pass':'keep'}))
            capture = dict(use, kind='captured_draw', complete=True, shader_corpus='corpus',
                shader_corpus_sha256=corpus_hashes,
                vertex_constants=write('constants.bin', bytes(3072)),
                draw_uniforms=write('draw-uniforms.bin', bytes(636)),
                fixed_attributes=write('attributes.bin', struct.pack('<64f', *([0., 0., 0., 1.]*16))),
                vertex_declaration=dict(elements=[], packed_mask=0), vertex_streams=[],
                draw=dict(primitive='point', indexed=False, vertex_start=0, vertex_count=1),
                textures=[None]*4, render_state=state, state_sha256='1'*64,
                reference=dict(color=dict(write('reference-color.bin', bytes(8*8*4)),
                    format='rgba8unorm', width=8, height=8, orientation='top_left')),
                target=dict(width=8, height=8, color_format='bgra8unorm',
                            depth_format='depth32float_stencil8', orientation='top_left',
                            clear_color=[0., 0., 0., 0.], clear_depth=1., clear_stencil=0))
            write('capture.json', capture)
            manifest = prepare(folder/'capture.json', output)
            self.assertEqual(manifest['shaders']['vertex']['entry'], 'xgpu_vertex')
            self.assertEqual(manifest['shaders']['fragment']['entry'], 'xgpu_fragment')
            self.assertEqual(manifest['uniforms']['vertex']['size'], 3120)
            self.assertEqual(manifest['uniforms']['pixel']['size'], 608)
            self.assertEqual(manifest['textures'], [None]*4)
            self.assertEqual(len(manifest['source_capture']['inputs']), 9)
            self.assertEqual(manifest['source_capture']['state_sha256'], '1'*64)
            self.assertEqual(manifest['reference']['color']['format'], 'rgba8unorm')
            self.assertEqual(manifest['reference']['color']['orientation'], 'top_left')
            self.assertTrue(all(Path(path).is_absolute() for path in manifest['source_sha256']))
            # Keep the captured corpus and original uniforms paired under their
            # byte hashes; reused numeric IDs alone cannot establish identity.
            def reject(edited, reason):
                write('capture.json', edited)
                with self.assertRaisesRegex(ValueError, reason):
                    prepare(folder/'capture.json', output)
            reject(dict(capture, complete=False), 'Incomplete')
            reject(dict(capture, program_id=9), 'pairing mismatch')
            reject(dict(capture, textures=[None]*3), 'four texture slots')
            bad_state = copy.deepcopy(state)
            bad_state['blend']['operation'] = 'multiply'
            reject(dict(capture, render_state=bad_state), 'blend state')
            bad_state['blend'].update(operation='add', source='blend_color')
            reject(dict(capture, render_state=bad_state), 'captured blend color')
            bad_hashes = dict(corpus_hashes)
            bad_hashes['vertex-0000.json'] = '0'*64
            reject(dict(capture, shader_corpus_sha256=bad_hashes), 'corpus is stale')
            original_fixed = (folder/'attributes.bin').read_bytes()
            (folder/'attributes.bin').write_bytes(bytes([1])+original_fixed[1:])
            reject(capture, 'hash mismatch')
            (folder/'attributes.bin').write_bytes(original_fixed)
            original_uniforms = (folder/'draw-uniforms.bin').read_bytes()
            (folder/'draw-uniforms.bin').write_bytes(bytes([1])+original_uniforms[1:])
            reject(capture, 'hash mismatch')
            (folder/'draw-uniforms.bin').write_bytes(original_uniforms)
            # Prepare-level coverage binds original sampler enums1(2D)/3(cube)
            # to distinct resource headers and the actual emitted MSL types.
            original_pixel = (corpus/'pixel-0000.json').read_bytes()
            textured_pixel = copy.deepcopy(pixel)
            textured_pixel['texture_modes'] = 1|(3<<15)
            textured_pixel['sampler_type'] = [1,0,0,3]
            write('corpus/pixel-0000.json',textured_pixel)
            textured_capture = copy.deepcopy(capture)
            textured_capture['shader_corpus_sha256'] = {path.name:sha256(path.read_bytes()) for path in corpus.iterdir()}
            sampler = dict(min_filter=2,mag_filter=2,mip_filter=2,address_u=3,address_v=3,
                           address_w=3,max_mip_level=0,max_anisotropy=1,mip_lod_bias=0)
            palette = b''.join(bytes([i,255-i,i//2,i]) for i in range(256))
            textured_capture['textures'][0] = dict(write('p8.bin',bytes([1,2,3,4,5])),
                format_word=header(0x0b,1,1,2),size_word=0,width=2,height=2,depth=1,levels=2,
                palette=dict(write('palette.bin',palette),format='argb32_little_endian'),sampler=sampler)
            textured_capture['textures'][0]['sampler'] = dict(sampler,address_w=4)
            cube = b''.join(bytes([face,level,31,0])*count+bytes(padding)
                           for face in range(6) for level,count,padding in ((0,4,0),(1,1,108)))
            textured_capture['textures'][3] = dict(write('cube.bin',cube),
                format_word=header(7,1,1,2)|4,size_word=0,width=2,height=2,depth=1,levels=2,sampler=sampler)
            write('capture.json',textured_capture)
            imported = prepare(folder/'capture.json',output)
            self.assertEqual([t['type'] if t else None for t in imported['textures']],['2d',None,None,'cube'])
            self.assertEqual(imported['textures'][3]['face_order'],
                ['positive_x','negative_x','positive_y','negative_y','positive_z','negative_z'])
            self.assertIn('texturecube<float> tex3', (output/'fragment.metal').read_text())
            self.assertIn('tex3.sample(sampler3, (xT3).xyz', (output/'fragment.metal').read_text())
            for level,mip in enumerate(imported['textures'][3]['mipmaps']):
                self.assertEqual([face['face'] for face in mip['faces']],list(range(6)))
                for face in mip['faces']:
                    self.assertEqual((output/face['file']).read_bytes(),
                        bytes([31,level,face['face'],255])*(4 if level==0 else 1))
            self.assertEqual((output/imported['textures'][0]['mipmaps'][1]['file']).read_bytes(),bytes([2,250,5,5]))
            self.assertEqual(imported['textures'][0]['source_palette']['sha256'],sha256(palette))
            self.assertEqual(imported['textures'][0]['source_sampler']['address_w'],4)
            self.assertEqual(imported['textures'][0]['sampler']['address_w'],'clamp_to_edge')
            compressed_capture = copy.deepcopy(textured_capture)
            compressed = b''.join(bytes([face,level,11,22,33,44,55,66])+bytes(padding)
                                  for face in range(6) for level,padding in ((0,0),(1,112)))
            compressed_capture['textures'][3] = dict(write('bc1-cube.bin',compressed),
                format_word=header(12,1,1,2)|4,size_word=0,width=2,height=2,depth=1,levels=2,sampler=sampler)
            write('capture.json',compressed_capture)
            compressed_import = prepare(folder/'capture.json',output)['textures'][3]
            self.assertEqual(compressed_import['pixel_format'],'bc1_rgba')
            self.assertEqual(compressed_import['source_face_pitch_bytes'],128)
            for level,mip in enumerate(compressed_import['mipmaps']):
                for face in mip['faces']:
                    self.assertEqual((output/face['file']).read_bytes(),
                                     bytes([face['face'],level,11,22,33,44,55,66]))
            for format_id in (14,15):
                unsupported = copy.deepcopy(compressed_capture)
                unsupported['textures'][3]['format_word'] = header(format_id,1,1,2)|4
                reject(unsupported,'only captured BC1')
            mismatched = copy.deepcopy(textured_capture)
            mismatched['textures'][3]['format_word'] &= ~4
            reject(mismatched,'sampler type differs')
            missing_palette = copy.deepcopy(textured_capture)
            del missing_palette['textures'][0]['palette']
            reject(missing_palette,'exact captured ARGB32 palette')
            wrong_palette = copy.deepcopy(textured_capture)
            wrong_palette['textures'][0]['palette']['format'] = 'rgba32_little_endian'
            reject(wrong_palette,'exact captured ARGB32 palette')
            wrong_header = copy.deepcopy(textured_capture)
            wrong_header['textures'][0]['levels'] = 1
            reject(wrong_header,'levels differs')
            truncated = copy.deepcopy(textured_capture)
            truncated['textures'][3].update(write('short-cube.bin',cube[:-1]))
            reject(truncated,'Truncated captured cube')
            (folder/'palette.bin').write_bytes(bytes([1])+palette[1:])
            reject(textured_capture,'hash mismatch')
            (folder/'palette.bin').write_bytes(palette)
            # The complete prepare path must not opt in from an ANGLE backing
            # format or a shader key alone. Bind the original request, explicit
            # contract and unchanged uniform payload hashes as one package.
            depth_pixel = copy.deepcopy(pixel)
            depth_pixel['texture_modes'] = 0x54421
            depth_pixel['sampler_type'] = [1, 1, 0, 0]
            depth_pixel['combiner_state'][56] = 0x110000
            write('corpus/pixel-0000.json', depth_pixel)
            depth_capture = copy.deepcopy(textured_capture)
            depth_capture['shader_corpus_sha256'] = {p.name:sha256(p.read_bytes()) for p in corpus.iterdir()}
            depth_capture['textures'][1] = copy.deepcopy(depth_capture['textures'][0])
            depth_capture['textures'][3] = None
            reject(depth_capture, 'explicit captured Xbox D24')
            depth_capture['pixel_depth_contract'] = dict(version=1, kind='xbox_raw_d24')
            depth_capture['original_depth_request'] = dict(auto_depth_stencil_format=43,
                actual_port_surface_format_word=0x2f21, floating_point_zbuffer_byte=1)
            reject(depth_capture, 'integer D24')
            depth_capture['original_depth_request'].update(auto_depth_stencil_format=42,
                actual_port_surface_format_word=0x2e21, floating_point_zbuffer_byte=0)
            write('capture.json', depth_capture)
            depth_manifest = prepare(folder/'capture.json', output)
            self.assertEqual(depth_manifest['pixel_depth_contract']['raw_range'], 16777215)
            self.assertIn('[[depth(any)]]', (output/'fragment.metal').read_text())
            depth_bytes = (output/depth_manifest['uniforms']['pixel']['file']).read_bytes()
            self.assertEqual(struct.unpack('<3f', depth_bytes[324:336]),
                (struct.unpack('<f', struct.pack('<f', 1 / 16777215))[0], 0., 1.))
            self.assertIn('original GLES DOT_ZW fallback omits depth replacement', depth_manifest['limitations'])
            (corpus/'pixel-0000.json').write_bytes(original_pixel)
            # The original renderer makes GLrow0 logical Xbox picturetop. A
            # physical GLbottom-left label must not cause a byte reversal.
            raw = copy.deepcopy(capture)
            # The raw collector supplies a palette descriptor without hashes.
            # Freeze must bind those bytes as well as the texture index data,
            # even if this particular shader does not consume the bound slot.
            raw['textures'][0] = copy.deepcopy(textured_capture['textures'][0])
            raw['textures'][0]['palette'].pop('sha256')
            raw['textures'][0]['palette'].pop('size')
            raw['textures'][0]['palette']['bytes'] = 1024
            raw['target'].update(color_format='rgba8unorm', depth_format='depth24_stencil8')
            raw['viewport'] = dict(origin_x=1, origin_y=2, width=6, height=3, znear=0., zfar=1.)
            raw['scissor'] = dict(enabled=True, box_gl=[1, 2, 6, 3])
            raw['render_state_d3d'] = dict(depth_enable=1, depth_write=0, depth_compare=515,
                cull=2305, front_face=2304, color_write=0x10101, blend_enable=1,
                blend_source=1, blend_destination=1, blend_op=32774, offset_enable=1,
                offset_slope=-2., offset_units=-8., stencil_enable=1, stencil_compare=514,
                stencil_ref=0, stencil_read_mask=1, stencil_write_mask=0,
                stencil_fail=7680, stencil_depth_fail=7680, stencil_pass=7680)
            reference_bytes = b''.join(bytes([row, 0, 0, 0])*8 for row in range(8))
            raw['reference']['color'].update(write('raw-color.rgba', reference_bytes), orientation='bottom_left')
            write('raw-capture.json', raw)
            write('test-only-reference-runner', b'fixture provenance, never executed')
            frozen = freeze_raw_capture(folder/'raw-capture.json', folder/'test-only-reference-runner')
            normalized = json.loads(frozen.read_bytes())
            self.assertEqual((folder/normalized['reference']['color']['file']).read_bytes(), reference_bytes)
            self.assertEqual(normalized['reference']['color']['orientation'], 'top_left')
            self.assertFalse(normalized['readback_contract']['transformed'])
            self.assertEqual(normalized['render_state']['scissor'],
                             dict(x=1, y=2, width=6, height=3))
            self.assertEqual(normalized['render_state']['raster']['front_face'], 'cw')
            self.assertEqual(normalized['render_state']['raster']['cull'], 'back')
            self.assertEqual(normalized['render_state']['blend']['write_mask'], 7)
            self.assertEqual(normalized['textures'][0]['palette']['sha256'],sha256(palette))
            self.assertEqual(normalized['textures'][0]['palette']['size'],1024)


if __name__ == '__main__':
    unittest.main()
