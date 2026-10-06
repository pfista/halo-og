import copy,tempfile,tomllib,unittest
from pathlib import Path
import metal_campaign_content_smoke as c

class CampaignSmokeTests(unittest.TestCase):
    def test_original_campaign_source_whitelist(self):
        text=(c.ROOT/'source/main/main.c').read_text();self.assertEqual(c.original_names(text),c.CAMPAIGN)
        with self.assertRaises(ValueError):c.original_names(text.replace('"levels\\\\a10\\\\a10"','"levels\\\\test\\\\bloodgulch"',1))
    def test_literal_hs_init_no_python_bell_or_slayer(self):
        data=c.campaign_init('a10').encode('ascii');self.assertEqual(data,b'game_difficulty_set normal\nmap_name levels\\a10\\a10\n')
        c.validate_init(data,'a10');self.assertNotIn(b'\x07',data)
        for invalid in (data.replace(b'\\a',b'\x07'),b'\xef\xbb\xbf'+data,data+b'cinematic_skip\n',data.replace(b'normal',b'legendary'),data.replace(b'levels\\a10',b'levels\\a30')):
            with self.assertRaises(ValueError):c.validate_init(invalid,'a10')
    def test_mp_ui_and_unknown_campaign_rejected(self):
        for name in ('bloodgulch','ui','a99','a10;cheat'):
            with self.assertRaises(ValueError):c.campaign_init(name)
    def test_unskipped_opening_configuration(self):
        folder=Path('/tmp/campaign isolated');text=c.controlled_config(c.mp.NORMAL.read_text(),folder,30,'');x=tomllib.loads(text)
        self.assertEqual(x['debug']['test_input'],'');self.assertEqual(x['debug']['exit_after'],30)
        self.assertFalse(any(x['bindings'].values()));self.assertFalse(x['audio']['enabled']);self.assertFalse(x['network']['online'])
        self.assertEqual(x['debug']['texture_dump_directory'],str(folder/'dumps'))
    def test_duration_input_and_online_guards(self):
        folder=Path('/tmp/campaign');template=c.mp.NORMAL.read_text()
        for duration in (19,31):
            with self.assertRaises(ValueError):c.controlled_config(template,folder,duration,'')
        x=tomllib.loads(c.controlled_config(template,folder,20,'bot:0'));x['network']['online']=True
        with self.assertRaises(ValueError):c.validate_config(x,folder,20,'bot:0')
        with self.assertRaises(ValueError):c.controlled_config(template,folder,30,'sound:0')
    def test_campaign_cache_type_guard_precedes_payload(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'a10.map';raw=bytearray(2048);raw[:4]=b'daeh';raw[2044:]=b'toof'
            import struct
            struct.pack_into('<II',raw,4,5,2048);struct.pack_into('<H',raw,96,1);path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'not campaign'):c.CampaignCache(path)
            struct.pack_into('<H',raw,96,0);struct.pack_into('<I',raw,8,c.MAX_CACHE_BYTES+1);path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'size/version'):c.CampaignCache(path)
    def test_actual_campaign_large_cache_scenario_identity(self):
        cache=c.CampaignCache(c.mp.MAPS/'a10.map');self.assertGreater(len(cache.data),128*1024*1024)
        group,offset,name=cache.tag(cache.u32(cache.tag_offset+4));self.assertEqual((group,name),('scnr','levels\\a10\\a10'))
        self.assertEqual(cache.unpack('<h',offset+60)[0],0)
    def test_frozen_mp_helper_contract(self):c.verify_helper()
if __name__=='__main__':unittest.main()
