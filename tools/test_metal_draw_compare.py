#!/usr/bin/env python3
"""Independent spatial/readback and stale-provenance gates for original draw replay."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from metal_draw_compare import ComparisonError, color_metrics, compare, depth_metrics


class DrawComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='halo-draw-compare-')
        self.folder = Path(self.temporary.name)
        self.manifest_path = self.folder/'replay.json'
        self.reference_path = self.folder/'angle.json'
        self.native_path = self.folder/'metal.json'
        self.capture = dict(self.payload('capture.json',b'{"frame":420,"use":63,"state":"original"}'),
                            frame=420,use=63)
        self.manifest = dict(schema_version=1,kind='nv2a_draw_replay',
                             source_capture=self.capture,
                             source_sha256={str(self.folder/'source.c'):
                                            self.payload('source.c',b'original emitter source')['sha256']},
                             target=dict(width=2,height=2,orientation='top_left',
                                         color_format='bgra8unorm',depth_format='depth32float_stencil8',
                                         clear_color=[0,0,0,0],clear_depth=1,clear_stencil=0),
                             shaders=dict(vertex=self.payload('vertex.metal',b'original VS'),
                                          fragment=self.payload('pixel.metal',b'original PS')))
        self.write(self.manifest_path,self.manifest)
        self.pixels = bytes([255,0,0,0, 0,255,0,0, 0,0,255,0, 0,0,0,0])
        self.reference = self.result('angle',self.pixels)
        self.native = self.result('native_metal',self.pixels)
        self.save_results()

    def tearDown(self):
        self.temporary.cleanup()

    def payload(self,name,data):
        (self.folder/name).write_bytes(data)
        return dict(file=name,sha256=hashlib.sha256(data).hexdigest())

    def write(self,path,value):
        path.write_text(json.dumps(value,sort_keys=True)+'\n')

    def result(self,backend,pixels):
        target = self.manifest['target']
        descriptor = lambda name,data,fmt:dict(self.payload(f'{backend}-{name}',data),
                                               width=target['width'],height=target['height'],
                                               orientation='top_left',format=fmt)
        return dict(schema_version=1,kind='nv2a_draw_result',complete=True,backend=backend,
                    source_capture=copy.deepcopy(self.capture),
                    manifest_sha256=hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
                    runner=self.payload(f'{backend}-runner',b'compiled executable'),
                    color=descriptor('color.rgba',pixels,'rgba8unorm'),
                    depth=descriptor('depth.f32',struct.pack('<4f',1,.5,.25,1),'float32'),
                    stencil=descriptor('stencil.u8',b'\0\0\0\0','uint8'),
                    actual_depth_format='depth32float_stencil8',
                    limits=['Independent cleared target; previous frame history omitted.'])

    def save_results(self):
        self.write(self.reference_path,self.reference)
        self.write(self.native_path,self.native)

    def compare(self,**options):
        return compare(self.manifest_path,self.reference_path,self.native_path,**options)

    def test_exact_visible_draw_and_complete_attachment_comparison(self):
        report = self.compare()
        self.assertTrue(report['color_passed'])
        self.assertTrue(report['attachment_comparison_passed'])
        self.assertEqual(report['color']['reference_nonclear_pixels'],3)
        self.assertIn('not a complete ordered frame',report['limits'][0])

    def test_equal_histogram_different_spatial_pixels_is_a_failure(self):
        swapped = self.pixels[4:8]+self.pixels[:4]+self.pixels[8:]
        self.native = self.result('native_metal',swapped)
        self.save_results()
        report = self.compare()
        self.assertFalse(report['color_passed'])
        self.assertEqual(report['color']['exact_different_pixels'],2)
        self.assertEqual(report['color']['difference_bounds'],[0,0,1,0])

    def test_alpha_is_compared_and_tolerance_is_reported(self):
        altered = bytearray(self.pixels);altered[3]=1
        self.native = self.result('native_metal',bytes(altered));self.save_results()
        self.assertFalse(self.compare()['color_passed'])
        report = self.compare(color_tolerance=1)
        self.assertTrue(report['color_passed'])
        self.assertEqual(report['color']['max_channel_error'],[0,0,0,1])
        self.assertEqual(report['color']['tolerance_unorm_units'],1)

    def test_empty_color_does_not_prove_visible_draw_replay(self):
        report = color_metrics(b'\0'*16,b'\0'*16,2,2,[0,0,0,0],0)
        self.assertFalse(report['passed']);self.assertFalse(report['visible_reference'])

    def test_bottom_left_readback_is_reoriented_without_resampling(self):
        self.reference = self.result('angle',self.pixels[8:]+self.pixels[:8])
        self.reference['color']['orientation']='bottom_left'
        self.save_results()
        self.assertTrue(self.compare()['color_passed'])

    def test_different_original_draw_is_rejected(self):
        self.reference['source_capture']['use']+=1;self.save_results()
        with self.assertRaisesRegex(ComparisonError,'different original draw'):
            self.compare()

    def test_source_capture_resource_or_compiled_runner_change_is_rejected(self):
        for name in ('capture.json','vertex.metal','source.c','native_metal-runner'):
            with self.subTest(payload=name):
                path=self.folder/name;original=path.read_bytes();path.write_bytes(original+b'changed')
                with self.assertRaisesRegex(ComparisonError,'Stale or changed payload'):
                    self.compare()
                path.write_bytes(original)

    def test_native_result_from_old_manifest_is_rejected(self):
        self.manifest['target']['clear_depth']=.5;self.write(self.manifest_path,self.manifest)
        with self.assertRaisesRegex(ComparisonError,'stale replay manifest'):
            self.compare()

    def test_truncated_or_unhashed_readback_is_rejected(self):
        self.native['color']=dict(self.payload('native_metal-color.rgba',self.pixels[:-4]),
                                  width=2,height=2,format='rgba8unorm',orientation='top_left')
        self.save_results()
        with self.assertRaisesRegex(ComparisonError,'payload size mismatch'):
            self.compare()

    def test_missing_attachment_or_depth_format_difference_cannot_close_parity(self):
        self.reference['actual_depth_format']='depth24unorm_stencil8';self.save_results()
        report=self.compare();self.assertTrue(report['color_passed'])
        self.assertFalse(report['attachment_comparison_passed'])
        self.assertTrue(any('precision parity is unverified' in text for text in report['limits']))
        self.reference['actual_depth_format']=self.native['actual_depth_format']
        del self.reference['stencil'];self.save_results()
        report=self.compare();self.assertFalse(report['attachment_comparison_passed'])

    def test_nonfinite_depth_is_rejected(self):
        with self.assertRaisesRegex(ComparisonError,'Nonfinite'):
            depth_metrics(struct.pack('<f',math_nan()),struct.pack('<f',1),0)


def math_nan():
    return float('nan')


if __name__=='__main__':unittest.main()
