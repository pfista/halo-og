#!/usr/bin/env python3
"""Capture completeness and native-input safety checks; no GPU or game needed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from metal_shader_validate import PixelKey, load_corpus


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.status=dict(schema_version=1,kind='capture',complete=True,frame=420,
                         vertex_count=1,pixel_count=1,use_count=1)
        self.vertex=dict(schema_version=1,kind='vertex',id=0,frame=420,
                         instruction_count=1,packed_mask=0,instructions=[0,0,0,1])
        key=PixelKey()
        self.pixel=dict(schema_version=1,kind='pixel',id=0,frame=420)
        for name,_ in key._fields_:
            value=getattr(key,name);self.pixel[name]=list(value) if hasattr(value,'__len__') else value
        self.use=dict(schema_version=1,frame=420,use=0,vertex_id=0,pixel_id=0,
                      program_id=7,declaration_id=8,immediate=0)
        self.write()

    def tearDown(self):self.temp.cleanup()

    def write(self):
        for name,data in [('status.json',self.status),('vertex-0000.json',self.vertex),('pixel-0000.json',self.pixel)]:
            (self.folder/name).write_text(json.dumps(data))
        (self.folder/'uses.jsonl').write_text(json.dumps(self.use)+'\n')

    def test_complete_pair_and_provenance(self):
        records,uses,status,hashes=load_corpus(self.folder)
        self.assertEqual(len(records),2);self.assertEqual(uses[0]['program_id'],7)
        self.assertTrue(status['complete']);self.assertEqual(len(hashes),4)

    def test_incomplete_capture_rejected(self):
        self.status['complete']=False;self.write()
        with self.assertRaisesRegex(RuntimeError,'incomplete'):load_corpus(self.folder)

    def test_instruction_count_cannot_overread(self):
        self.vertex['instruction_count']=2;self.write()
        with self.assertRaisesRegex(RuntimeError,'instruction array'):load_corpus(self.folder)

    def test_words_cannot_wrap_at_native_boundary(self):
        for value in (-1,2**32,True):
            with self.subTest(value=value):
                self.vertex['instructions'][0]=value;self.write()
                with self.assertRaisesRegex(RuntimeError,'instruction array'):load_corpus(self.folder)

    def test_truncated_key_rejected(self):
        self.pixel['combiner_state'].pop();self.write()
        with self.assertRaisesRegex(RuntimeError,'pixel key'):load_corpus(self.folder)

    def test_draw_missing_shader_rejected(self):
        self.use['pixel_id']=1;self.write()
        with self.assertRaisesRegex(RuntimeError,'missing shader'):load_corpus(self.folder)

    def test_count_mismatch_rejected(self):
        self.status['vertex_count']=2**32-1;self.write()
        with self.assertRaisesRegex(RuntimeError,'ids or count mismatch'):load_corpus(self.folder)


if __name__=='__main__':unittest.main()
