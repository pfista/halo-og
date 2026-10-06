import json
from pathlib import Path
import struct
import tempfile
import tomllib
import unittest
import metal_game_content_smoke as m

class OriginalContentSmokeTests(unittest.TestCase):
    def test_original_initializer_whitelist(self):
        text=m.SOURCE_LIST.read_text()
        self.assertEqual(m.original_names(text),m.STOCK)
        with self.assertRaises(ValueError):m.original_names(text+'\n"levels\\\\test\\\\custom\\\\custom"\n')

    def test_header_scenario_category_not_filename_guess(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bloodgulch.map';h=bytearray(2048);h[:4]=b'daeh';h[2044:]=b'toof'
            struct.pack_into('<II',h,4,5,8192);h[32:42]=b'bloodgulch';h[64:77]=b'01.10.12.2276'
            struct.pack_into('<H',h,96,2);p.write_bytes(h)
            self.assertEqual(m.header_metadata(p)['scenario_type'],2)
            h[:4]=b'bad!';p.write_bytes(h)
            with self.assertRaises(ValueError):m.header_metadata(p)

    def test_controlled_configuration(self):
        folder=Path('/tmp/stock mp isolated')
        text=m.controlled_config(m.NORMAL.read_text(),folder,15);c=tomllib.loads(text)
        self.assertEqual(c['debug']['test_input'],'bot:0');self.assertEqual(c['debug']['exit_after'],15)
        self.assertFalse(any(c['bindings'].values()));self.assertFalse(c['audio']['enabled'])
        self.assertEqual(c['debug']['texture_dump_directory'],str(folder/'dumps'))
        self.assertFalse(c['network']['online']);self.assertFalse(c['network']['allow_upnp'])

    def test_inherited_shader_fallback_rejects(self):
        folder=Path('/tmp/stock mp isolated')
        text=m.set_key(m.NORMAL.read_text(),'debug','gpu_debug_expression','"float4(1)"')
        with self.assertRaises(ValueError):m.controlled_config(text,folder,15)

    def test_duration_gate_and_section_scoping(self):
        with self.assertRaises(ValueError):m.controlled_config(m.NORMAL.read_text(),Path('/tmp/smoke'),30)
        text='[first]\nkey = 1\n[second]\nkey = 2\n'
        c=tomllib.loads(m.set_key(text,'second','key','3'))
        self.assertEqual(c,{'first':{'key':1},'second':{'key':3}})

    def test_failure_before_first_statistics_is_retained(self):
        log='Metal API Validation Enabled\nNative unsupported NV2A program: vertex 1 pixel 0\nhalo-linux: Native Metal: translate original NV2A program failed (-2), frame 3, command 4294967295: unsupported original renderer state\n'
        r=m.parse_log(log)
        self.assertEqual(r['statistics'],[]);self.assertIsNone(r['guest_exit'])
        self.assertEqual(len(r['native_renderer_failures']),1);self.assertEqual(len(r['failure_diagnostics']),1)
        self.assertTrue(r['gpu_api_validation_enabled'])

    def test_statistics_not_final_image_counter(self):
        r=m.parse_log('Native frame 420: 70123 original draws, 128 texture resources, 83 programs\nGame exited (0)\n')
        self.assertEqual(r['guest_exit'],0);self.assertEqual(r['statistics'][-1]['frame'],420)
        self.assertEqual(r['statistics'][-1]['original_draws'],70123)

    def test_original_cache_scenario_identity(self):
        c=m.Cache(m.MAPS/'bloodgulch.map');group,offset,name=c.tag(c.u32(c.tag_offset+4))
        self.assertEqual((group,name),('scnr','levels\\test\\bloodgulch\\bloodgulch'))
        self.assertEqual(c.unpack('<h',offset+60)[0],1)

if __name__=='__main__':unittest.main()
