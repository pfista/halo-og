"""CPU guards for optional native build-proof inputs and linked implementations."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import metal_live_build_proof as proof


BASE_NAMES = ('d3d8_metal', 'metal_packet_room', 'xbox_xapi')
FIXED = 'metal_fixed_function'
FIXED_SOURCES = ['port/linux/src/metal_fixed_function.c', 'port/linux/src/metal_fixed_function.h']
FIXED_OBJECT = 'build/macos-metal/guest/obj/port/linux/src/metal_fixed_function.o'
FIXED_SYMBOLS = ('metal_fixed_function_pack_unlit_immediate', 'metal_fixed_function_vertex_to_msl')
BASE_EVIDENCE = [
    'build.ninja', 'port/linux/src/xgpu_msl.h', 'tools/metal_live_build_proof.py',
    'tools/test_macos_renderer_build.py', 'tools/test_metal_packet_room.py',
    'tools/test_metal_host_frame_coalesce.py',
    'build/macos-metal/guest/gen/native_host_imports.list',
    'build/macos-metal/guest/gen/imports.s',
    'build/macos-metal/guest/obj/port/linux/src/d3d8_metal.o',
    'build/macos-metal/guest/obj/port/linux/src/metal_packet_room.o',
    'build/macos-metal/guest/obj/port/linux/src/xbox_xapi.o',
]


def reference():
    # The historical alpha build has 29 primary inputs before batching additions.
    return {'source_bindings': [{'path': f'base-input-{index}'} for index in range(29)]}


def graph(fixed=False):
    names = BASE_NAMES + ((FIXED,) if fixed else ())
    edges = [f'build build/macos-metal/guest/obj/port/linux/src/{name}.o: cc port/linux/src/{name}.c'
             for name in names]
    edges.append('build build/macos-metal/halo_guest.elf: link ' + ' '.join(
        f'build/macos-metal/guest/obj/port/linux/src/{name}.o' for name in names))
    return '\n'.join(edges)


def compile_line():
    return ('clang --target=arm64_32-apple-watchos -DHALO_MACOS_NATIVE_METAL=1 '
            '-ffp-contract=off -c port/linux/src/metal_fixed_function.c')


def symbols(names=FIXED_SYMBOLS):
    return '\n'.join(f'00000000 T _{name}' for name in names)


class BindingTests(unittest.TestCase):
    def test_default_primary_and_evidence_contract_is_unchanged(self):
        primary, evidence = proof.binding_paths(reference())
        self.assertEqual(primary, [f'base-input-{index}' for index in range(29)] + [
            'port/linux/src/metal_packet_room.c', 'port/linux/src/metal_packet_room.h',
            'port/linux/src/xbox_xapi.c'])
        self.assertEqual(evidence, BASE_EVIDENCE)
        self.assertEqual((len(primary), len(evidence)), (32, 11))

    def test_existing_extended_contracts_keep_their_counts_and_order(self):
        for contract, count in (('copy-volume', 13), ('copy-volume-depth', 16),
                                ('copy-volume-depth-border', 16)):
            with self.subTest(contract=contract):
                primary, evidence = proof.binding_paths(reference(), contract)
                self.assertEqual(len(primary), 34)
                self.assertEqual(len(evidence), count)
                self.assertEqual(primary[-2:], ['port/linux/src/metal_mip_composite.c',
                                               'port/linux/src/metal_mip_composite.h'])
                self.assertEqual(evidence[:11], BASE_EVIDENCE)
                self.assertFalse(any('metal_fixed_function' in path for path in primary + evidence))

    def test_flag_adds_only_two_sources_and_one_object(self):
        for contract in ('original', 'copy-volume', 'copy-volume-depth', 'copy-volume-depth-border'):
            with self.subTest(contract=contract):
                old_primary, old_evidence = proof.binding_paths(reference(), contract)
                primary, evidence = proof.binding_paths(reference(), contract, fixed_function=True)
                self.assertEqual(primary, old_primary + FIXED_SOURCES)
                self.assertEqual(evidence, old_evidence + [FIXED_OBJECT])
                self.assertEqual(len(set(primary + evidence)), len(primary + evidence))
        primary, evidence = proof.binding_paths(reference(), 'copy-volume-depth-border', True)
        self.assertEqual((len(primary), len(evidence), len(primary + evidence)), (36, 17, 53))

    def test_reference_with_duplicate_or_unexpected_base_bindings_rejects(self):
        duplicate = reference()
        duplicate['source_bindings'][1] = dict(duplicate['source_bindings'][0])
        extra = reference()
        extra['source_bindings'].append({'path': 'unexpected-helper'})
        for value in (duplicate, extra):
            with self.assertRaisesRegex(ValueError, '32 distinct'):
                proof.binding_paths(value, 'copy-volume-depth-border', True)


class GraphTests(unittest.TestCase):
    def test_default_accepts_existing_graph_without_fixed_helper(self):
        result = proof.graph_checks(graph())
        self.assertEqual(set(result['source_edges']), set(BASE_NAMES))
        self.assertTrue(result['no_gl_native_edges'])

    def test_flag_requires_helper_source_and_link_edge(self):
        result = proof.graph_checks(graph(True), fixed_function=True)
        self.assertIn(FIXED, result['source_edges'])
        self.assertIn(FIXED_OBJECT, result['guest_link_edge'])
        with self.assertRaisesRegex(ValueError, 'source edge'):
            proof.graph_checks(graph(), fixed_function=True)

    def test_helper_object_not_linked_rejects(self):
        lines = graph(True).splitlines()
        lines[-1] = lines[-1].replace(' ' + FIXED_OBJECT, '')
        text = '\n'.join(lines)
        with self.assertRaisesRegex(ValueError, 'link omits'):
            proof.graph_checks(text, fixed_function=True)

    def test_helper_edge_requires_its_exact_source(self):
        for replacement in ('port/linux/src/other.c', 'port/linux/src/metal_fixed_function.c.old'):
            text = graph(True).replace(FIXED_SOURCES[0], replacement)
            with self.assertRaisesRegex(ValueError, 'source edge'):
                proof.graph_checks(text, fixed_function=True)

    def test_helper_link_requires_exact_object_not_similar_name(self):
        text = graph(True).rsplit(FIXED_OBJECT, 1)
        text = (FIXED_OBJECT + '.old').join(text)
        with self.assertRaisesRegex(ValueError, 'exact fixed-function object'):
            proof.graph_checks(text, fixed_function=True)

    def test_duplicate_helper_source_edge_rejects(self):
        text = graph(True) + '\n' + graph(True).splitlines()[-2]
        with self.assertRaisesRegex(ValueError, 'source edge'):
            proof.graph_checks(text, fixed_function=True)

    def test_flag_does_not_weaken_gl_dependency_rejection(self):
        text = graph(True) + '\nbuild build/macos-metal/guest/bad.o: cc port/linux/src/d3d8_gl.c'
        with self.assertRaisesRegex(ValueError, 'GL dependency'):
            proof.graph_checks(text, fixed_function=True)


class ImplementationTests(unittest.TestCase):
    def check(self, object_symbols=None, guest_symbols=None, compilation=None):
        proof.implementation_checks(FIXED, FIXED_SYMBOLS,
            symbols() if object_symbols is None else object_symbols,
            symbols() if guest_symbols is None else guest_symbols,
            compile_line() if compilation is None else compilation)

    def test_both_actual_exported_functions_must_be_linked(self):
        self.check()
        for symbol in FIXED_SYMBOLS:
            retained = symbols(tuple(name for name in FIXED_SYMBOLS if name != symbol))
            with self.subTest(symbol=symbol, location='object'):
                with self.assertRaisesRegex(ValueError, 'object omits'):
                    self.check(object_symbols=retained)
            with self.subTest(symbol=symbol, location='guest'):
                with self.assertRaisesRegex(ValueError, 'guest omits'):
                    self.check(guest_symbols=retained)

    def test_undefined_symbol_is_not_an_exported_implementation(self):
        with self.assertRaisesRegex(ValueError, 'object omits'):
            self.check(object_symbols=symbols().replace(' T ', ' U '))

    def test_native_ilp32_flags_are_required(self):
        for flag in ('--target=arm64_32-apple-watchos', '-DHALO_MACOS_NATIVE_METAL=1', '-ffp-contract=off'):
            with self.subTest(flag=flag):
                with self.assertRaisesRegex(ValueError, 'compile flags'):
                    self.check(compilation=compile_line().replace(flag, ''))

    def test_helper_cannot_reintroduce_gl_boundary(self):
        with self.assertRaisesRegex(ValueError, 'GL boundary'):
            self.check(object_symbols=symbols() + '\n         U _host_gl_draw')


class CommandLineTests(unittest.TestCase):
    def test_flag_is_explicit_and_default_is_false(self):
        for arguments, enabled in (([], False), (['--fixed-function'], True)):
            with self.subTest(enabled=enabled), patch.object(sys, 'argv', [
                'metal_live_build_proof.py', '--output', '/tmp/proof',
                '--execution', '/tmp/execution.json', *arguments]), patch.object(proof, 'prepare') as prepare:
                proof.main()
                prepare.assert_called_once_with(Path('/tmp/proof').resolve(), Path('/tmp/execution.json').resolve(),
                    proof.ROOT / 'build/macos-metal/live-alpha-border-build-proof/result.json',
                    'original', fixed_function=enabled)


if __name__ == '__main__':
    unittest.main()
