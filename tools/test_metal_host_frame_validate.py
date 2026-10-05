import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import metal_host_frame_validate as f

class OrderedFrameWireTests(unittest.TestCase):
    def execution_fixture(self,root):
        prepared={'execution_command':['host','guest','original-addresses']}
        (root/'prepared.json').write_text(json.dumps(prepared))
        stdout=root/'native.stdout';stdout.write_text('original host output')
        (root/'native.stderr').write_text('original host diagnostics')
        record={'schema_version':1,'kind':'ordered_frame_host_execution','complete':True,'returncode':0,
            'command':prepared['execution_command'],'prepared_sha256':f.sha(root/'prepared.json'),
            'stdout_sha256':f.sha(stdout),'stderr_sha256':f.sha(root/'native.stderr'),'executor_sha256':f.sha(Path(f.__file__))}
        (root/'execution.json').write_text(json.dumps(record))
        return prepared,stdout,record

    def test_execution_record_binds_actual_exit_to_command_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);prepared,stdout,record=self.execution_fixture(root)
            self.assertEqual(f.validate_execution(root,stdout,prepared)['returncode'],0)
            record['returncode']=-9;(root/'execution.json').write_text(json.dumps(record))
            self.assertEqual(f.validate_execution(root,stdout,prepared)['returncode'],-9)
            # Nonzero is a valid observation; consume's success gate requires zero.

    def test_execution_missing_or_wrong_identity_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);prepared,stdout,record=self.execution_fixture(root)
            for field,value in [('command',['another-host']),('prepared_sha256','0'*64),
                                ('executor_sha256','0'*64),('returncode',None),('returncode',False)]:
                with self.subTest(field=field,value=value):
                    changed=dict(record);changed[field]=value;(root/'execution.json').write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):f.validate_execution(root,stdout,prepared)
            (root/'execution.json').unlink()
            with self.assertRaisesRegex(ValueError,'Missing tool-observed'):f.validate_execution(root,stdout,prepared)

    def test_execution_output_tampering_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);prepared,stdout,record=self.execution_fixture(root)
            stdout.write_text('replaced output')
            with self.assertRaisesRegex(ValueError,'output changed'):f.validate_execution(root,stdout,prepared)

    def test_failed_host_cannot_pass_even_with_successful_guest_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);prepared,stdout,execution=self.execution_fixture(root)
            guest={'kind':'native_metal_ilp32_ordered_frame','guest_pointer_bits':32,'guest_result':0}
            stdout.write_text(json.dumps(guest));execution.update(returncode=1,stdout_sha256=f.sha(stdout))
            (root/'execution.json').write_text(json.dumps(execution))
            fixture={'manifest':'unused','steps':[],'readbacks':[],'source_capture':{'frame':420},
                     'attachments_only_diagnostic':False,'limits':[]}
            (root/'fixture.json').write_text(json.dumps(fixture));native=root/'native';native.mkdir()
            report=[0]*16;report[0]=1;report[1]=4;report[8]=420
            (native/'checkpoints.json').write_text(json.dumps({'report':report,'checkpoints':[]}))
            with patch.object(f,'validate_prepared_inputs'),self.assertRaises(SystemExit):f.consume(root,stdout)
            result=json.loads((root/'result.json').read_text())
            self.assertFalse(result['complete']);self.assertFalse(result['attachment_gate']);self.assertEqual(result['returncode'],1)

    def test_execute_prepared_never_overwrites_a_previous_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.execution_fixture(root)
            with patch.object(f.subprocess,'run') as run,self.assertRaisesRegex(ValueError,'preserve earlier'):
                f.execute_prepared(root)
            run.assert_not_called()

    def test_default_full_mode_rejects_queries_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'manifest.json';output=root/'output'
            manifest.write_text(json.dumps({'commands':[{'kind':'visibility_begin','event':9}]}))
            argv=['tool','--manifest',str(manifest),'--output',str(output),'--rebase-plugin','unused']
            with patch('sys.argv',argv),self.assertRaisesRegex(ValueError,'full-mode submission rejected'):f.main()
            self.assertFalse(output.exists())

    def test_after_reference_bytes_never_enter_initial_seed_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);initial=bytes([17])*16;after=bytes([171])*16
            (root/'initial.bin').write_bytes(initial);(root/'after.bin').write_bytes(after)
            target={'generation':0,'width':2,'height':2,'initial':{'color':{
                'file':'initial.bin','size':16,'sha256':f.hashlib.sha256(initial).hexdigest()}},
                'reference_after':{'file':'after.bin','size':16,'sha256':f.hashlib.sha256(after).hexdigest()}}
            packet=f.wire.Packet(1);f.append_initial(packet,root,1,target);raw=packet.finish()
            command=struct.unpack_from('<18I',raw,24)
            self.assertEqual(command[0],11);self.assertEqual(command[16],1)
            self.assertEqual(raw[command[14]:command[14]+command[15]],initial)
            self.assertNotIn(after,raw)
            target['generation']=1
            with self.assertRaisesRegex(ValueError,'version0'):f.append_initial(f.wire.Packet(1),root,1,target)

    def test_checkpoint_identity_is_derived_from_recorded_version(self):
        manifest={'reference_checkpoints':{'83:5':{'width':128,'height':128,'color':{'file':'original.bin','size':65536,'sha256':'a'*64}}}}
        result=f.checkpoint_records(manifest,41,[{'target_id':83,'version':5},None])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['target_id'],83);self.assertEqual(result[0]['version'],5);self.assertEqual(result[0]['event'],41)
        self.assertEqual(result[0]['expected']['file'],'original.bin')
        with self.assertRaises(KeyError):f.checkpoint_records(manifest,41,[{'target_id':83,'version':4}])

    def test_query_scope_pairs_distinct_scratch_saved_slots_and_boolean_result(self):
        commands=[{'kind':'visibility_cpu_result','event':0,'slot':0,'result':0},
            {'kind':'visibility_begin','event':39,'slot':4096,'atomic_counters':False},
            {'kind':'visibility_end','event':41,'slot':0,'gl_query':2,'atomic_counters':False},
            {'kind':'visibility_gpu_result','event':136,'slot':0,'source_event':41,'gl_query':2,'available':True,'any_samples_passed':0}]
        result=f.query_plan(commands)
        self.assertEqual(result[39]['resource'],result[41]['resource'])
        self.assertEqual(result[136]['resource'],result[39]['resource']);self.assertEqual(result[136]['expected_value'],0)
        commands[-1]['source_event']=40
        with self.assertRaisesRegex(ValueError,'not paired'):f.query_plan(commands)

    def test_native_query_diagnostic_does_not_authorize_default_full_mode(self):
        m={'commands':[{'kind':'visibility_begin','event':9}]}
        self.assertEqual(len(f.query_gate(m,False,True)),1)
        with self.assertRaisesRegex(ValueError,'full-mode submission rejected'):f.query_gate(m,False)

    def test_fragment_policy_requires_exact_flags_and_provenance(self):
        shader={'entry':'xgpu_fragment'}
        self.assertEqual(f.fragment_contract(shader,Path('.')),0)
        shader['compile_options']={'contract':'angle_metal_fast_fragment_v1','fast_math':True,
            'preserve_invariance':False,'math_mode':'fast','floating_point_functions':'fast'}
        with self.assertRaisesRegex(ValueError,'Missing pinned fragment'):f.fragment_contract(shader,Path('.'))
        shader.update(compiler_evidence={'file':'original-evidence'},compiler_baseline={'file':'original-glsl'})
        shader['compile_options']['preserve_invariance']=True
        with self.assertRaisesRegex(ValueError,'Unverified fragment'):f.fragment_contract(shader,Path('.'))

if __name__=='__main__':unittest.main()
