#!/usr/bin/env python3
"""Compare a recorded ILP32 frame run using explicit historical source restores.

Prepared evidence is immutable. A restored source must match its originally
recorded SHA, and every generated packet is independently rederived before
attachment comparison. No expected attachment is submitted to the GPU.
"""
import argparse
import array
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

def compare(out,restores,report_path=None):
    report_path=Path(report_path) if report_path else out/'comparison.json'
    require(not report_path.exists(),'Comparison report already exists; preserve earlier evidence')
    self_hash=sha(__file__);prepared=json.loads((out/'prepared.json').read_text());fixture=json.loads((out/'fixture.json').read_text())
    require(sha(out/'fixture.json')==prepared['fixture_sha256'],'Recorded fixture changed')
    require(sha(fixture['manifest'])==fixture['manifest_sha256'],'Original frame manifest changed')
    resolutions={}
    for original,digest in prepared['source_and_binary_sha256'].items():
        actual=Path(restores.get(original,original)).resolve()
        require(sha(actual)==digest,f'Historical source/binary does not match recorded SHA: {original}')
        resolutions[original]=dict(file=str(actual),sha256=digest,restored=str(actual)!=original)
    require(set(restores)<=set(resolutions),'Restoration map includes an unrecorded source')
    for collection in ('packet_payload_sha256','independent_expected_payloads'):
        for path,digest in fixture[collection].items():require(sha(path)==digest,f'Recorded payload changed: {path}')
    sys.path.insert(0,str(ROOT/'tools'))
    helper_path=resolutions[str(ROOT/'tools/metal_host_draw_validate.py')]['file']
    helper=load_module('metal_host_draw_validate',helper_path);helper.ROOT=ROOT
    producer_path=resolutions[str(ROOT/'tools/metal_host_frame_validate.py')]['file']
    producer=load_module('metal_host_frame_validate_recorded',producer_path)
    manifest_path=Path(fixture['manifest']);manifest=json.loads(manifest_path.read_text())
    producer.frame.verify_replay(manifest_path)
    steps,details=(producer.make_steps(manifest_path.parent,manifest,fixture['attachments_only_diagnostic'],True)
        if fixture.get('native_query_diagnostic') else producer.make_steps(manifest_path.parent,manifest,fixture['attachments_only_diagnostic']))
    require(len(steps)==len(fixture['steps']),'Rederived ordered step count differs')
    for step,recorded in zip(steps,fixture['steps']):
        require(hashlib.sha256(step['packet']).hexdigest()==recorded['packet']['sha256'],'Rederived original packet differs')
        require(all(step.get(k)==recorded.get(k) for k in ('event','kind','use','readonly_visibility_query','checkpoints')),
            'Rederived ordered event/checkpoint metadata differs')
    require(json.loads(json.dumps(details))==fixture['details'],'Rederived original execution details differ')
    native=out/'native';run=json.loads((out/'native.stdout').read_text());dump=json.loads((native/'checkpoints.json').read_text())
    require(run.get('kind')=='native_metal_ilp32_ordered_frame' and run.get('guest_pointer_bits')==32,'Not an actual ILP32 frame run')
    report=dump['report'];require(len(report)==16 and report[0]==1 and report[6]==len(steps) and
        report[7]==len(fixture['readbacks']) and report[8]==fixture['source_capture']['frame'] and
        report[9]==int(fixture['attachments_only_diagnostic']),'Guest report belongs to another original fixture')
    expected={(r['event'],r['target_id'],r['version'],r['plane']):r for r in fixture['readbacks']}
    comparisons=[];first=None;actual_hashes={}
    for r in dump['checkpoints']:
        key=(r['event'],r['target_id'],r['version'],r['plane']);require(key in expected,'Unexpected native checkpoint')
        e=expected.pop(key);require(all(r[k]==e[k] for k in ('event','target_id','version','plane','width','height','bytes')),'Native checkpoint shape differs')
        name=f"event-{r['event']}-target-{r['target_id']}-version-{r['version']}-plane-{r['plane']}.bin"
        require(r['file']==name,'Native path differs from fixed event identity')
        actual=(native/name).read_bytes();reference=(struct.pack('<Q',e['expected_value']) if e['plane']==8 else helper.payload(manifest_path.parent,e['expected']))
        require(len(actual)==len(reference)==e['bytes'],'Native checkpoint byte count differs')
        digest=hashlib.sha256(actual).hexdigest();expected_digest=hashlib.sha256(reference).hexdigest();equal=digest==expected_digest
        entry=dict(event=r['event'],target_id=r['target_id'],version=r['version'],plane=r['plane'],
            different_bytes=0,first_different_byte=None,actual_sha256=digest,expected_sha256=expected_digest)
        if e['plane']==8:entry.update(actual_value=struct.unpack('<Q',actual)[0],expected_value=e['expected_value'],source_event=e['source_event'])
        if not equal:
            entry['different_bytes']=sum(a!=b for a,b in zip(actual,reference))
            entry['first_different_byte']=next(i for i,(a,b) in enumerate(zip(actual,reference)) if a!=b)
            if r['plane']==1:
                entry['different_pixels']=sum(actual[i:i+4]!=reference[i:i+4] for i in range(0,len(actual),4))
                entry['max_channel_error']=max(abs(a-b) for a,b in zip(actual,reference))
            elif r['plane']==2:
                require(sys.byteorder=='little','Float32 diagnostic requires little-endian source words')
                a=array.array('f');a.frombytes(actual);b=array.array('f');b.frombytes(reference)
                entry['different_depth_samples']=sum(x!=y for x,y in zip(a,b))
                entry['max_depth_error']=max((abs(float(x)-float(y)) for x,y in zip(a,b) if math.isfinite(x) and math.isfinite(y)),default=None)
                u=array.array('I');u.frombytes(actual);v=array.array('I');v.frombytes(reference)
                def ordered(bits):return (~bits & 0xffffffff) if bits & 0x80000000 else bits | 0x80000000
                entry['max_depth_ulps']=max(abs(ordered(x)-ordered(y)) for x,y in zip(u,v))
            if first is None:first=entry
        comparisons.append(entry);actual_hashes[str(native/name)]=digest
    execution=None
    if (out/'execution.json').exists():
        require(callable(getattr(producer,'validate_execution',None)),'Recorded producer lacks an execution contract')
        execution=producer.validate_execution(out,out/'native.stdout',prepared)
    host_exit=execution is not None and execution['returncode']==0
    checkpoint_transport=run.get('guest_result')==0 and report[1]==4 and report[13]==len(fixture['readbacks']) and report[14]==len(steps)
    transport=host_exit and checkpoint_transport
    exact=transport and not expected and first is None
    queries=[c for c in comparisons if c['plane']==8];attachments=[c for c in comparisons if c['plane']!=8]
    proof=dict(prepared,kind='ordered_frame_ilp32_attachment_diagnostic',complete=transport,build_only=False,full_frame_gate=False,
        attachment_gate=transport and not expected and all(c['different_bytes']==0 for c in attachments),
        native_query_gate=transport and bool(queries) and report[15]==len(queries) and all(c['different_bytes']==0 for c in queries),
        original_cpu_query_timing_gate=False,presentation_gate=False,guest_run=run,guest_report=report,source_closure_resolutions=resolutions,packet_rederivation_passed=True,
        native_host_exit_gate=host_exit,returncode=execution['returncode'] if execution else None,
        checkpoint_transport_gate=checkpoint_transport,
        execution_record=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')) if execution else None,
        comparison_tool=dict(file=str(Path(__file__).resolve()),sha256=self_hash),compared_checkpoints=len(comparisons),missing_checkpoints=len(expected),
        first_difference=first,comparisons=comparisons,native_payload_sha256=actual_hashes,stdout_sha256=sha(out/'native.stdout'),
        checkpoint_metadata_sha256=sha(native/'checkpoints.json'),limits=fixture['limits'])
    for original,record in resolutions.items():require(sha(record['file'])==record['sha256'],f'Source changed during comparison: {original}')
    require(sha(__file__)==self_hash,'Comparison source changed while running')
    require(sha(fixture['manifest'])==fixture['manifest_sha256'] and sha(out/'fixture.json')==prepared['fixture_sha256'],'Original inputs changed during comparison')
    if execution is not None:require(sha(out/'execution.json')==proof['execution_record']['sha256'],'Execution record changed during comparison')
    report_path.write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({k:proof[k] for k in ('complete','full_frame_gate','attachment_gate','native_host_exit_gate','packet_rederivation_passed','compared_checkpoints','missing_checkpoints','first_difference')},indent=2));print(report_path)
    if not exact:raise SystemExit('Ordered attachment diagnostic differs; immutable evidence retained')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--source-restore-map',type=Path)
    p.add_argument('--report',type=Path,help='Fresh comparison report path (default: comparison.json; never overwrites result.json)')
    a=p.parse_args();restores=json.loads(a.source_restore_map.read_text()) if a.source_restore_map else {}
    compare(a.output.resolve(),restores,a.report.resolve() if a.report else None)
if __name__=='__main__':main()
