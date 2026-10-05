"""Independent preparation/provenance checks for the intended loading fixture."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_fixed_function_validate as fixture

DEFAULT=ROOT/'build/metal-poc/intended-fixed-loading-current-attempt3'


def rederive(out):
    prepared,package=fixture.verify(out)
    with tempfile.TemporaryDirectory(prefix='halo-fixed-oracle-') as directory:
        production=fixture.Production(Path(directory))
        actual,controls=fixture.fixture(production)
    expected_actions=b''.join(struct.pack('<12I',*a) for a in actual.actions)
    if expected_actions!=(out/'actions.bin').read_bytes() or bytes(actual.inputs)!=(out/'inputs.bin').read_bytes():
        raise ValueError('Prepared guest inputs/actions differ from rederived original-source fixture')
    if len(actual.packets)!=len(package['packets']) or len(actual.readbacks)!=len(package['readbacks']):
        raise ValueError('Prepared fixture coverage differs')
    for current,record in zip(actual.packets,package['packets']):
        if bytes.fromhex(current['bytes'])!=Path(record['file']).read_bytes():
            raise ValueError('Prepared transport packet differs from independent rederivation')
        for field in ('sequence','status','failed_command','label'):
            if current[field]!=record[field]:raise ValueError('Prepared packet expectation differs')
    for current,record in zip(actual.readbacks,package['readbacks']):
        expected=bytes.fromhex(current.pop('expected'))
        if expected!=Path(record['expected_file']).read_bytes():
            raise ValueError('Prepared independent expected bytes differ')
        for field in current:
            if current[field]!=record[field]:raise ValueError('Prepared expected metadata differs')
    if controls!=package['controls']:raise ValueError('Prepared matrix/coordinate controls differ')
    return prepared,package,actual


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.prepared,cls.package,cls.actual=rederive(DEFAULT)

    def test_real_packets_rederive_and_no_after_oracle_uploads(self):
        self.assertEqual(len(self.actual.readbacks),31)
        self.assertEqual(sum(bool(a[5]) for a in self.actual.actions if a[0]==2),16)
        self.assertTrue(all(struct.unpack_from('<I',self.actual.inputs,a[1])[0] not in (3,11)
                            for a in self.actual.actions if a[0]==2))
        self.assertFalse(self.package['expected_after_gpu_uploaded'])

    def test_bounds_are_narrow_and_strict_controls_are_not_relaxed(self):
        bounded=[r for r in self.package['readbacks'] if r['maximum_byte_error']]
        self.assertEqual(len(bounded),3)
        self.assertTrue(all('gradient' in r['label'] and r['maximum_byte_error']==1 for r in bounded))
        self.assertEqual(self.package['controls']['half_pixel_control']['coverage'],64*64)
        self.assertEqual(self.package['controls']['nonidentity_matrix_control']['coverage'],323*241)
        labels=[r['label'] for r in self.package['readbacks']]
        self.assertTrue(all(f'exact-independent-texture-stage-{n}' in labels for n in range(4)))
        self.assertTrue(all(f'exact-distinct-coordinate-v{9+n}' in labels for n in range(4)))

    def test_shader_and_register_provenance(self):
        self.assertEqual(self.package['fixed_vertex_compiler_contract'],0)
        self.assertEqual(self.package['original_pixel_compiler_contract'],1)
        for name,program in [('blur',54),('regular',55)]:
            self.assertEqual((DEFAULT/'generated'/f'{name}-pixel.metal').read_bytes(),
                (fixture.history.FAILED/'dumps'/f'native-failure-frame464-program-{program}-pixel.metal').read_bytes())
        self.assertEqual(fixture.sha(ROOT/'port/linux/src/d3d8_metal.c'),
                         '69c524bcc0c9b02111ba8bd650edb7b75263b099866023155323e98a1ad64b98')

    def test_changed_fixture_rejects_before_execution(self):
        with tempfile.TemporaryDirectory(prefix='halo-fixed-stale-') as directory:
            path=Path(directory)
            (path/'prepared.json').write_text(json.dumps(self.prepared))
            changed=dict(self.package);changed['readbacks']=[]
            (path/'fixture.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'Fixture changed'):fixture.verify(path)


if __name__=='__main__':
    if '--closure' in sys.argv:
        index=sys.argv.index('--closure');output=Path(sys.argv[index+1]).resolve();del sys.argv[index:index+2]
        prepared,package,actual=rederive(DEFAULT)
        result_path=DEFAULT/'result.json';result=json.loads(result_path.read_text())
        execution=DEFAULT/'execution.json';observed=json.loads(execution.read_text())
        if result.get('passed') is not True or result.get('returncode')!=0 or observed.get('returncode')!=0:
            raise ValueError('GPU fixture lacks an observed successful execution')
        if observed['prepared_sha256']!=fixture.sha(DEFAULT/'prepared.json') or observed['executor_sha256']!=fixture.sha(fixture.__file__):
            raise ValueError('Execution source/preparation changed')
        if observed['command']!=prepared['execution_command'] or observed['validation_environment']!=prepared['validation_environment']:
            raise ValueError('Execution command/environment changed')
        if observed['stdout_sha256']!=fixture.sha(DEFAULT/'native.stdout') or observed['stderr_sha256']!=fixture.sha(DEFAULT/'native.stderr'):
            raise ValueError('Observed execution bytes changed')
        checkpoint=json.loads((DEFAULT/'native/checkpoints.json').read_text())
        if len(checkpoint['checkpoints'])!=31 or checkpoint['report'][12]!=16 or checkpoint['report'][:2]!=[1,4]:
            raise ValueError('Missing real ILP32 helper calls/readbacks')
        if checkpoint['report'][6:10]!=[21,1,31,5] or checkpoint['report'][10]!=21:
            raise ValueError('Missing real successful submissions/atomic byte/version controls')
        bound={r['event']:r for r in package['readbacks']};reported={r['event']:r for r in result['comparisons']}
        observed_bytes={};independent=[]
        for r in checkpoint['checkpoints']:
            e=bound.pop(r['event']);c=reported.pop(r['event'])
            data_path=DEFAULT/'native'/r['file'];raw=data_path.read_bytes();expected=Path(e['expected_file']).read_bytes()
            if len(raw)!=len(expected):raise ValueError('Independent readback extent differs')
            if any(r[field]!=e[field] for field in ('event','target_id','version','plane','bytes','width','height')) or r['wire_content_version']!=e['version'] or r['completed_sequence']!=e['sequence']:
                raise ValueError('Independent readback version/sequence/extent differs')
            differences=fixture.np.abs(fixture.np.frombuffer(raw,fixture.np.uint8).astype(fixture.np.int16)-fixture.np.frombuffer(expected,fixture.np.uint8).astype(fixture.np.int16))
            maximum=int(differences.max(initial=0));count=int(fixture.np.count_nonzero(differences))
            if maximum>e['maximum_byte_error'] or maximum!=c['maximum_byte_error'] or count!=c['different_bytes'] or c['allowed_maximum_byte_error']!=e['maximum_byte_error'] or fixture.sha(data_path)!=c['sha256']:
                raise ValueError('Independent raw-byte comparison differs')
            observed_bytes[e['label']]=raw
            independent.append(dict(event=e['event'],label=e['label'],sha256=fixture.sha(data_path),different_bytes=count,
                                    maximum_byte_error=maximum,declared_bound=e['maximum_byte_error'],version=e['version'],sequence=e['sequence']))
        if bound or reported:raise ValueError('Independent checkpoint coverage incomplete')
        if observed_bytes['save-actual-gradient-result']!=observed_bytes['present-copy-bounded-gradient-actual-byte-identity']:
            raise ValueError('GPU history copy did not preserve every actual byte')
        build_path=ROOT/'build/macos-metal/fixed-loading-build-proof/result.json'
        if fixture.sha(build_path)!='1fc22efafffd296cbfd0786331865ca40d9290ccd790e2956697051c17431ff0':
            raise ValueError('Actual fixed-function game build proof changed')
        build=json.loads(build_path.read_text());bindings=build['source_bindings']+build['evidence_bindings']
        if len(bindings)!=53 or build.get('passed') is not True or build.get('actual_build_tool_exit')!=0:
            raise ValueError('Incomplete actual game/helper build binding')
        for binding in bindings:
            current=ROOT/binding['path'];frozen=ROOT/build['source_snapshot']/binding['path']
            if fixture.sha(current)!=binding['sha256'] or fixture.sha(frozen)!=binding['sha256']:
                raise ValueError('Current/frozen actual game build binding differs: '+binding['path'])
        helper=build['native_compiled_objects']['metal_fixed_function']
        if helper['linked_in_guest'] is not True or helper['native_ilp32_flags'] is not True or helper['symbol']!='metal_fixed_function_pack_unlit_immediate' or 'metal_fixed_function_vertex_to_msl' not in helper['additional_linked_symbols']:
            raise ValueError('Production fixed helper not linked into actual guest')
        if fixture.sha(ROOT/helper['object']['path'])!=helper['object']['sha256']:
            raise ValueError('Production fixed helper object changed')
        closure=dict(schema_version=1,kind='independent_intended_fixed_loading_closure',complete=True,passed=True,
            verifier_sha256=fixture.sha(__file__),prepared_sha256=fixture.sha(DEFAULT/'prepared.json'),
            result_sha256=fixture.sha(result_path),execution_sha256=fixture.sha(execution),
            rederived_packets=len(actual.packets),readbacks=31,exact_controls=28,bounded_gradient_controls=3,
            maximum_declared_gradient_error=1,actual_gradient_copy_byte_identity=True,ilp32_production_helper_calls=16,
            successful_submissions=21,atomic_rejections=1,saved_actual_byte_version_controls=5,
            actual_game_build_proof=dict(path=str(build_path),sha256=fixture.sha(build_path),
                current_and_frozen_binding_count=53,production_helper_object=helper['object']),
            independent_raw_comparisons=independent,host_returncode=0,guest_returncode=0,frontend_executed=False,physical_xbox_fixed_function_gate=False,
            live_map_transition_gate=False,full_game_gate=False,limits=package['limits'])
        output.write_text(json.dumps(closure,indent=2)+'\n');print(json.dumps(closure,indent=2));sys.exit(0)
    unittest.main()
