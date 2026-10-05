"""CPU guards for optional native build-proof inputs and linked implementations."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import metal_live_build_proof as proof


BASE_NAMES = ('d3d8_metal', 'metal_packet_room', 'xbox_xapi')
FIXED = 'metal_fixed_function'
FIXED_SOURCES = ['port/linux/src/metal_fixed_function.c', 'port/linux/src/metal_fixed_function.h']
FIXED_OBJECT = 'build/macos-metal/guest/obj/port/linux/src/metal_fixed_function.o'
FIXED_SYMBOLS = ('metal_fixed_function_pack_unlit_immediate', 'metal_fixed_function_vertex_to_msl')
DISPLAY_NAMES = ('port_config', 'halo_frame_pacing', 'metal_render_scale')
DISPLAY_SOURCES = ['port/linux/src/port_config.c', 'port/linux/src/halo_frame_pacing.c',
                   'port/linux/src/halo_frame_pacing.h', 'port/linux/src/metal_render_scale.c',
                   'port/linux/src/metal_render_scale.h']
DISPLAY_OBJECTS = [f'build/macos-metal/guest/obj/port/linux/src/{name}.o' for name in DISPLAY_NAMES]
DISPLAY_TESTS = ['tools/test_halo_frame_pacing.py', 'tools/test_metal_render_scale.py',
                 'tools/test_metal_live_build_proof.py']
DISPLAY_SYMBOLS = {
    'port_config': ('config_integer',),
    'halo_frame_pacing': ('halo_frame_pacing_reset', 'halo_frame_pacing_deadline'),
    'metal_render_scale': ('halo_metal_render_target_dimensions', 'halo_metal_render_scale_rectangle',
                          'halo_metal_render_presentation_box', 'halo_metal_render_window_point'),
}
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


def graph(fixed=False, display=False):
    names = BASE_NAMES + ((FIXED,) if fixed else ()) + (DISPLAY_NAMES if display else ())
    edges = [f'build build/macos-metal/guest/obj/port/linux/src/{name}.o: cc port/linux/src/{name}.c'
             for name in names]
    edges.append('build build/macos-metal/halo_guest.elf: link ' + ' '.join(
        f'build/macos-metal/guest/obj/port/linux/src/{name}.o' for name in names))
    return '\n'.join(edges)


def compile_line(name=FIXED):
    return ('clang --target=arm64_32-apple-watchos -DHALO_MACOS_NATIVE_METAL=1 '
            '-ffp-contract=off -c port/linux/src/' + name + '.c')


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

    def test_display_opt_in_adds_config_helpers_objects_and_tests(self):
        for contract in ('original', 'copy-volume', 'copy-volume-depth', 'copy-volume-depth-border'):
            with self.subTest(contract=contract):
                old_primary, old_evidence = proof.binding_paths(reference(), contract, fixed_function=True)
                primary, evidence = proof.binding_paths(reference(), contract, fixed_function=True, display_options=True)
                self.assertEqual(primary, old_primary + DISPLAY_SOURCES)
                self.assertEqual(evidence, old_evidence + DISPLAY_OBJECTS + DISPLAY_TESTS)
                self.assertEqual(len(set(primary + evidence)), len(primary + evidence))
        primary, evidence = proof.binding_paths(reference(), 'copy-volume-depth-border', True, True)
        self.assertEqual((len(primary), len(evidence)), (41, 23))

    def test_display_requires_fixed_function_before_any_path_access(self):
        with self.assertRaisesRegex(ValueError, 'require.*fixed-function'):
            proof.binding_paths(None, display_options=True)
        with self.assertRaisesRegex(ValueError, 'require.*fixed-function'):
            proof.graph_checks('', display_options=True)
        with patch.object(Path, 'read_bytes') as read:
            with self.assertRaisesRegex(ValueError, 'require.*fixed-function'):
                proof.prepare(Path('/tmp/unused'), Path('/tmp/unused'), Path('/tmp/unused'), display_options=True)
            read.assert_not_called()


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


class DisplayGraphTests(unittest.TestCase):
    def check(self, text):
        return proof.graph_checks(text, fixed_function=True, display_options=True)

    def test_all_actual_source_edges_and_linked_objects_are_required(self):
        result = self.check(graph(True, True))
        self.assertEqual(set(result['source_edges']), set(BASE_NAMES + (FIXED,) + DISPLAY_NAMES))
        for name, object_path in zip(DISPLAY_NAMES, DISPLAY_OBJECTS):
            with self.subTest(name=name):
                lines = graph(True, True).splitlines()
                without_source = '\n'.join(line for line in lines if not line.startswith('build ' + object_path + ':'))
                with self.assertRaisesRegex(ValueError, 'source edge'):
                    self.check(without_source)
                lines[-1] = lines[-1].replace(' ' + object_path, '')
                with self.assertRaisesRegex(ValueError, 'link omits'):
                    self.check('\n'.join(lines))

    def test_similar_source_and_object_names_do_not_count(self):
        for name, object_path in zip(DISPLAY_NAMES, DISPLAY_OBJECTS):
            with self.subTest(name=name, kind='source'):
                source = f'port/linux/src/{name}.c'
                with self.assertRaisesRegex(ValueError, 'exact display-options source edge'):
                    self.check(graph(True, True).replace(source, source + '.old'))
            with self.subTest(name=name, kind='object'):
                text = (object_path + '.old').join(graph(True, True).rsplit(object_path, 1))
                with self.assertRaisesRegex(ValueError, 'exact display-options object'):
                    self.check(text)

    def test_duplicate_source_and_gl_dependencies_still_reject(self):
        for name in DISPLAY_NAMES:
            duplicate = next(line for line in graph(True, True).splitlines() if f'/{name}.o:' in line)
            with self.assertRaisesRegex(ValueError, 'source edge'):
                self.check(graph(True, True) + '\n' + duplicate)
        with self.assertRaisesRegex(ValueError, 'GL dependency'):
            self.check(graph(True, True) + '\nbuild build/macos-metal/guest/bad.o: cc port/linux/src/d3d8_gl.c')

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


class DisplayImplementationTests(unittest.TestCase):
    def test_each_helper_export_is_present_in_object_and_final_guest(self):
        for name, required in DISPLAY_SYMBOLS.items():
            proof.implementation_checks(name, required, symbols(required), symbols(required), compile_line(name), True)
            for symbol in required:
                retained = symbols(tuple(item for item in required if item != symbol))
                with self.subTest(name=name, symbol=symbol, location='object'):
                    with self.assertRaisesRegex(ValueError, 'object omits'):
                        proof.implementation_checks(name, required, retained, symbols(required), compile_line(name), True)
                with self.subTest(name=name, symbol=symbol, location='guest'):
                    with self.assertRaisesRegex(ValueError, 'guest omits'):
                        proof.implementation_checks(name, required, symbols(required), retained, compile_line(name), True)

    def test_ilp32_flags_exact_source_and_no_gl_boundary(self):
        for name, required in DISPLAY_SYMBOLS.items():
            for flag in ('--target=arm64_32-apple-watchos', '-DHALO_MACOS_NATIVE_METAL=1', '-ffp-contract=off'):
                with self.subTest(name=name, flag=flag), self.assertRaisesRegex(ValueError, 'compile flags'):
                    proof.implementation_checks(name, required, symbols(required), symbols(required),
                                                compile_line(name).replace(flag,''), True)
            with self.assertRaisesRegex(ValueError, 'exact display-options compile source'):
                proof.implementation_checks(name, required, symbols(required), symbols(required),
                                            compile_line(name).replace(name + '.c', name + '.c.old'), True)
            with self.assertRaisesRegex(ValueError, 'GL boundary'):
                proof.implementation_checks(name, required, symbols(required) + '\n U _host_gl_draw',
                                            symbols(required), compile_line(name), True)


class DisplayConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.text = (proof.ROOT / 'port/linux/src/port_config.c').read_text()

    def test_actual_config_has_integer_compatibility_defaults_and_no_environment(self):
        self.assertEqual(proof.display_configuration_checks(self.text), {
            'display.frame_limit': {'type':'integer','default':0,'environment':None,'native_metal_only':True},
            'display.render_height': {'type':'integer','default':480,'environment':None,'native_metal_only':True},
        })

    def test_type_default_env_and_platform_changes_are_rejected(self):
        for name, default in (('display.frame_limit','0'),('display.render_height','480')):
            original = f'"{name}", _config_integer, "{default}", NULL, _environment_value, _platform_all'
            for replacement in (original.replace('_config_integer','_config_boolean'),
                                original.replace(f'"{default}"','"720"'),
                                original.replace('NULL','"HALO_NEW_SETTING"'),
                                original.replace('_platform_all','_platform_android')):
                with self.subTest(name=name, replacement=replacement), self.assertRaisesRegex(ValueError, 'type/default/environment'):
                    proof.display_configuration_checks(self.text.replace(original,replacement))

    def test_guard_missing_negative_and_else_branch_reject(self):
        native = '#if defined(HALO_MACOS_NATIVE_METAL) && HALO_MACOS_NATIVE_METAL'
        for replacement in ('#if 1','#if !defined(HALO_MACOS_NATIVE_METAL)',
                            '#if defined(HALO_MACOS_NATIVE_METAL) && HALO_MACOS_NATIVE_METAL\n#else'):
            with self.assertRaisesRegex(ValueError, 'not native Metal guarded'):
                proof.display_configuration_checks(self.text.replace(native,replacement))

    def test_commented_entries_are_ignored_and_duplicate_real_entry_rejects(self):
        entry = '{ "display.frame_limit", _config_integer, "0", NULL, _environment_value, _platform_all, "example" },'
        self.assertEqual(proof.display_configuration_checks(self.text),
                         proof.display_configuration_checks('/* '+entry+' */\n// '+entry+'\n'+self.text))
        with self.assertRaisesRegex(ValueError, 'one native display config entry'):
            proof.display_configuration_checks(self.text + '\n'+entry)

    def test_multiline_fields_are_supported(self):
        text = self.text.replace('"display.frame_limit", _config_integer, "0", NULL,',
                                 '"display.frame_limit",\n _config_integer,\n "0",\n NULL,')
        self.assertEqual(proof.display_configuration_checks(text), proof.display_configuration_checks(self.text))


class DisplayResultTests(unittest.TestCase):
    def test_opt_in_marker_and_evidence_require_full_freeze_path(self):
        """Synthetic observer/binary fixtures exercise prepare without a build.

        This is proof-tool validation, never retained build or GPU evidence.
        """
        config_text = (proof.ROOT / 'port/linux/src/port_config.c').read_text()
        unchanged = ('port/macos/include/halo_metal_abi.h','port/macos/host/host_metal.mm',
                     'port/linux/src/metal_guest_transport.c','port/linux/src/metal_guest_transport.h')
        all_symbols = symbols(('halo_metal_flush_pending','halo_metal_packet_room','XLaunchNewImageA',
                               *FIXED_SYMBOLS, *[symbol for row in DISPLAY_SYMBOLS.values() for symbol in row]))
        with tempfile.TemporaryDirectory(prefix='halo-display-proof-unit-') as directory:
            root = Path(directory).resolve()
            fixture_reference = {'source_bindings': [{'path': path} for path in
                (*unchanged, *(f'fixture/base-{n}' for n in range(25)))]}
            primary, evidence = proof.binding_paths(fixture_reference, fixed_function=True, display_options=True)
            for path in primary + evidence + ['build/macos-metal/host/host_import_table.c','port/macos/metal_imports.list']:
                target = root / path
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text('unit fixture\n')
            (root/'port/linux/src/port_config.c').write_text(config_text)
            (root/'build.ninja').write_text(graph(True,True))
            for item in fixture_reference['source_bindings']:
                item['sha256'] = hashlib.sha256((root/item['path']).read_bytes()).hexdigest()
            reference_path = root/'build/reference.json'
            reference_path.write_text(json.dumps(fixture_reference))
            log = root/'build/observer.log'
            log.write_text('synthetic build observer test fixture\n')
            execution = root/'build/observer.json'
            execution.write_text(json.dumps({'returncode':0,'command':['fixture-only'],'log':{
                'path':'build/observer.log','sha256':hashlib.sha256(log.read_bytes()).hexdigest()}}))

            def command(output,name,arguments):
                if name.endswith('-compile-command'):
                    text = compile_line(name.removesuffix('-compile-command'))
                elif name == 'guest-defined' or name.endswith('-symbols'):
                    text = all_symbols
                else:
                    text = ''
                proof.write_new(output/(name+'.stdout'),text.encode())
                proof.write_new(output/(name+'.stderr'),b'')
                return text, {'command':[str(word) for word in arguments],'returncode':0}

            with (patch.object(proof,'ROOT',root), patch.object(proof,'__file__',str(root/'tools/metal_live_build_proof.py')),
                  patch.object(proof,'record_command',side_effect=command), patch('builtins.print')):
                for enabled in (False,True):
                    output = root / ('proof-display' if enabled else 'proof-existing')
                    proof.prepare(output,execution,reference_path,fixed_function=True,display_options=enabled)
                    result = json.loads((output/'result.json').read_text())
                    if enabled:
                        self.assertIs(result['display_options'],True)
                        self.assertEqual(result['display_configuration'],proof.display_configuration_checks(config_text))
                        self.assertTrue(set(DISPLAY_NAMES).issubset(result['native_compiled_objects']))
                        for path in DISPLAY_SOURCES + DISPLAY_OBJECTS + DISPLAY_TESTS:
                            self.assertTrue((output/'snapshot'/path).is_file())
                    else:
                        self.assertNotIn('display_options',result)
                        self.assertNotIn('display_configuration',result)
                        self.assertFalse(set(DISPLAY_NAMES) & set(result['native_compiled_objects']))
                    self.assertFalse(result['gameplay_gate'])
                    self.assertFalse(result['performance_improvement_gate'])


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

    def test_display_flag_requires_fixed_and_is_explicitly_forwarded(self):
        with patch.object(sys,'argv',['metal_live_build_proof.py','--output','/tmp/proof',
                '--execution','/tmp/execution.json','--fixed-function','--display-options']), patch.object(proof,'prepare') as prepare:
            proof.main()
            self.assertTrue(prepare.call_args.kwargs['fixed_function'])
            self.assertTrue(prepare.call_args.kwargs['display_options'])
        with (patch.object(sys,'argv',['metal_live_build_proof.py','--output','/tmp/proof',
                '--execution','/tmp/execution.json','--display-options']), patch.object(proof,'prepare') as prepare,
              patch('sys.stderr')):
            with self.assertRaises(SystemExit) as failure:
                proof.main()
            self.assertEqual(failure.exception.code,2)
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
