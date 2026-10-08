"""Opt-in vertex-fetch ABI check using the configured Mac ILP32 toolchain.

Requires LLVM 22 and generated guest musl headers. Compiles the production
helper to IR/assembly; no GPU, guest execution, game, or app build is involved.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_metal_native_vertex_fetch import ROOT, SOURCE, digest


class VertexFetchIlp32Tests(unittest.TestCase):
    ilp32_summary = None

    def test_native_guards_real_ilp32_headers(self):
        llvm = Path('/opt/homebrew/opt/llvm@22/bin')
        if not (llvm/'clang').exists():
            self.fail('real ILP32 clang is required for this guest helper')
        sys.path.insert(0,str(ROOT))
        from tools.android_build import GUEST_ABI_FLAGS
        musl = ROOT/'build/android/third_party/musl-1.2.5'
        resource = Path(subprocess.check_output([llvm/'clang','-print-resource-dir'],text=True).strip())
        with tempfile.TemporaryDirectory(prefix='halo-vertex-fetch-ilp32-') as temporary:
            directory = Path(temporary)
            generated = directory/'guest-include/bits'; generated.mkdir(parents=True)
            # Use the repository's actual configured 32-bit guest musl alltypes.
            candidates = [ROOT/f'build/{name}/guest/libc_include/bits/alltypes.h'
                          for name in ('macos-metal','macos','android')]
            candidates = [p for p in candidates if p.exists()]
            self.assertTrue(candidates,'configured musl alltypes header required')
            shutil.copy2(candidates[0],generated/'alltypes.h')
            unit = directory/'ilp32.c'
            unit.write_text('#include "'+str(SOURCE)+'"\n'
                '_Static_assert(sizeof(void*)==4 && sizeof(size_t)==4,"guest pointer ABI");\n'
                '_Static_assert(sizeof(float)==4 && sizeof(uint32_t)==4,"register ABI");\n'
                '_Static_assert(sizeof(struct metal_vertex_stream)==12,"stream ABI");\n'
                '_Static_assert(sizeof(struct metal_vertex_element)==20,"element ABI");\n'
                '_Static_assert(sizeof(struct metal_vertex_declaration)==328,"declaration ABI");\n'
                '_Static_assert(sizeof(struct metal_vertex_index_plan)==16,"plan ABI");\n')
            flags = [*GUEST_ABI_FLAGS,'-std=c11','-ffreestanding','-fno-builtin','-DHALO_MACOS_NATIVE_METAL=1',
                '-isystem',resource/'include','-I',directory/'guest-include',
                '-I',ROOT/'port/android/guest/libc/arch/arm64_32','-I',musl/'arch/generic','-I',musl/'include',
                '-Wall','-Wextra','-Werror']
            ir = directory/'ilp32.ll'
            subprocess.run([llvm/'clang',*flags,'-emit-llvm','-S',unit,'-o',ir],check=True,capture_output=True)
            assembly = directory/'ilp32.s'
            subprocess.run([llvm/'llc','-mtriple=arm64_32-apple-watchos',ir,'-o',assembly],check=True,capture_output=True)
            text = ir.read_text()
            self.assertIn('p:32:32',text)
            self.assertNotRegex(text,r'@(gl|host_gl|guest_gl)[A-Z_]')
            type(self).ilp32_summary = dict(pointer_bits=32,size_t_bits=32,declaration_bytes=328,
                element_bytes=20,stream_bytes=12,index_plan_bytes=16,ir_sha256=digest(ir.read_bytes()),
                assembly_sha256=digest(assembly.read_bytes()),alltypes_source=str(candidates[0]))


if __name__ == '__main__':
    unittest.main()
