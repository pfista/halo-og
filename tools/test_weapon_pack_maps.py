"""Check authoring boundaries and parse real-format synthetic Xbox tag tables.

Native compilation and Fiesta inventory checks remain separate evidence. These
tests exercise unsafe inputs, source isolation, and bounded cache inspection.
"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weapon_pack_maps as pack
import build_fiesta_arsenal as arsenal
from weapon_pack_animation_audit import clip_records, compare_clips, graph_records


class WeaponPackSafetyTests(unittest.TestCase):
    def test_global_player_uses_actual_multiplayer_biped(self):
        class Reader:
            def count(self, tags, name, field):
                self.assert_mp(field)
                return 1
            def assert_mp(self, field):
                if field != "multiplayer_information":
                    raise AssertionError("Singleplayer information must not select the multiplayer player")
            def get(self, tags, name, field):
                return {"multiplayer_information[0].unit": "characters/cyborg_mp/cyborg_mp.biped",
                        "animation_graph": "characters/cyborg/cyborg.model_animations"}[field]
        with patch.object(pack, "animation_labels", return_value={"seat_weapon_labels": {"stand": ["ar"], "crouch": ["ar"]}}):
            player = pack.player_animation_labels(Reader(), Path("unused"))
        self.assertEqual(player["player"], "characters/cyborg_mp/cyborg_mp.biped")
        self.assertEqual(player["globals_unit_field"], "multiplayer_information[0].unit")

    def test_all_primary_and_fallback_roots_require_frozen_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            first, fallback = Path(folder).resolve() / "custom", Path(folder).resolve() / "stock"
            for root in (first, fallback):
                root.mkdir()
                (root / "value.weapon").write_bytes(b"reviewed")
            hashes = {"value.weapon": pack.digest(first / "value.weapon")}
            source = {"maps": {"custom": {"tag_roots": [str(first), str(fallback)], "tag_sha256": hashes},
                               "stock": {"tag_roots": [str(fallback)], "tag_sha256": hashes}}}
            self.assertEqual(arsenal.frozen_base_roots(source, ["custom"]), {first, fallback})
            (fallback / "value.weapon").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                arsenal.frozen_base_roots(source, ["custom"])
            del source["maps"]["stock"]
            with self.assertRaises(ValueError):
                arsenal.frozen_base_roots(source, ["custom"])

    def test_bounded_graph_parser_reads_stance_labels_and_signed_topology(self):
        with tempfile.TemporaryDirectory() as folder:
            header = bytearray(64)
            header[36:40], header[60:64] = b"antr", b"blam"
            root, seat, weapon, kind, node = [bytearray(size) for size in (128, 100, 188, 60, 64)]
            struct.pack_into(">I", root, 12, 1)
            struct.pack_into(">I", root, 104, 1)
            seat[:6] = b"stand\0"
            struct.pack_into(">I", seat, 88, 1)
            struct.pack_into(">I", weapon, 176, 1)
            kind[:5] = b"99ml\0"
            node[:5] = b"root\0"
            struct.pack_into(">hhh", node, 32, -1, -1, 0)
            source = Path(folder) / "graph.model_animations"
            source.write_bytes(header + root + seat + weapon + kind + node)
            parsed = graph_records(source)
            self.assertEqual(parsed["seat_weapon_labels"], {"stand": ["99ml"]})
            self.assertEqual(parsed["nodes"], [{"name": "root", "next_sibling_node_index": "-1",
                                               "first_child_node_index": "-1", "parent_node_index": "0"}])
            self.assertEqual(parsed["clips"], {})

    def test_null_first_person_dependencies_are_not_playable(self):
        class Reader:
            def run(self, tool, *args):
                field = args[args.index("-G") + 1]
                return {"weapon_flags.must_be_readied": "0", "weapon_flags.doesnt_count_toward_maximum": "0",
                        "first_person_model": ".model", "first_person_animations": ".model_animations"}[field]
        with self.assertRaises(ValueError):
            pack.playable_weapon(Reader(), [Path("unused")], "weapons/ai/ai.weapon")

    def test_fiesta_graph_refuses_bone_reordering_and_clip_checksum_mismatch(self):
        nodes = [{"name": "root", "parent_node_index": "0", "first_child_node_index": "65535",
                  "next_sibling_node_index": "65535"}]
        baseline = {"nodes": nodes, "clips": [{"node_count": "1", "node_list_checksum": "123"}]}
        pack.validate_graph_metadata(baseline, baseline, ["root"])
        for candidate, names in ((baseline, ["other"]),
                                 ({"nodes": nodes, "clips": [{"node_count": "1", "node_list_checksum": "124"}]}, ["root"]),
                                 ({"nodes": [{**nodes[0], "parent_node_index": "65535"}], "clips": baseline["clips"]}, ["root"])):
            with self.subTest(names=names), self.assertRaises(ValueError):
                pack.validate_graph_metadata(baseline, candidate, names)

    def test_global_generation_has_all_nine_uncut_and_pinned_deduplicated_list(self):
        import hashlib
        data = arsenal.weapon_list_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), arsenal.EXPECTED_WEAPON_SHA)
        names = data.decode("ascii").splitlines()
        self.assertEqual(len(names), 31)
        self.assertEqual(names, sorted(set(names)))
        self.assertTrue(data.endswith(b"\n"))
        self.assertTrue(set((arsenal.PREFIX + name).replace("/", "\\") for name in arsenal.UNCUT).issubset(names))
        self.assertIn(arsenal.CANONICAL_FLAME.replace("/", "\\"), names)
        self.assertNotIn(arsenal.IMPORTED_FLAME.replace("/", "\\"), names)
        for extra in ("weapons/needler/mp_needler", "weapons/rocket launcher/rocket launcher longshot",
                      "weapons/rocket launcher/rocket launcher empty", "weapons/ball/skull"):
            self.assertIn((arsenal.PREFIX + extra).replace("/", "\\"), names)

    def test_hidden_physical_name_is_safe_bounded_and_deterministic(self):
        import hashlib
        self.assertEqual(arsenal.physical_name("prisoner"), "_fiesta_prisoner")
        self.assertEqual(arsenal.physical_name("custom map"), "_fiesta_custom map")
        long_name = "a" * 24
        self.assertEqual(arsenal.physical_name(long_name),
                         "_fiestah_" + hashlib.sha256(long_name.encode("ascii")).hexdigest()[:16])
        self.assertLessEqual(len(arsenal.physical_name("a" * 31)), 31)
        for name in ("", "Prisoner", "../prisoner", "a" * 32, "a/b", "a\n", "ümlaut"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                arsenal.physical_name(name)

    def test_private_player_pool_prefers_global_definitions_and_canonical_flame(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base, pack_root = root / "base", root / "pack-tags"
            map_path = root / "maps/test.map"
            names = {"weapons/smg/smg", pack.PREFIX + "weapons/smg/smg",
                     arsenal.CANONICAL_FLAME, arsenal.IMPORTED_FLAME,
                     "weapons/needler/needler", pack.PREFIX + "weapons/needler/mp_needler"}
            for name in names:
                directory = pack_root if name.startswith(pack.PREFIX) else base
                at = directory / (name + ".weapon")
                at.parent.mkdir(parents=True, exist_ok=True)
                at.write_bytes(b"fixture")
            report = {"compile_command": ["builder", "-t", str(base)], "output_map": str(map_path),
                      "fiesta_player_animation_checks": {"seat_weapon_labels": {"stand": ["ar"], "crouch": ["ar"]}}}
            with patch.object(arsenal, "compiled_tag_paths", return_value={(0x77656170, name) for name in names}), \
                    patch.object(arsenal, "playable_weapon", return_value={"label": "ar"}):
                actual = arsenal.eligible_pool(None, report)
            expected = {pack.PREFIX + "weapons/smg/smg", arsenal.CANONICAL_FLAME,
                        "weapons/needler/needler", pack.PREFIX + "weapons/needler/mp_needler"}
            self.assertEqual(actual, sorted(name.replace("/", "\\") for name in expected))
    def test_tag_paths_reject_traversal_and_ambiguous_names(self):
        self.assertEqual(pack.tag_path(r"weapons\smg\smg.weapon"), "weapons/smg/smg.weapon")
        for value in ("../a.weapon", "/a.weapon", "a/../../b.weapon", "a//b.weapon",
                      "a/./b.weapon", "a.weapon\n", "C:/a.weapon", "a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pack.tag_path(value)

    def test_output_traversal_and_symlink_cannot_escape_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "build").mkdir()
            (root / "source").mkdir()
            (root / "build/link").symlink_to(root / "source", target_is_directory=True)
            with patch.object(pack, "ROOT", root):
                for value in (root / "build/../source/new", root / "build/sub/../../source/new",
                              root / "build/link/new", root / "build"):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        pack.output_path(value, [])
                self.assertEqual(pack.output_path(root / "build/new", []), root / "build/new")
                with self.assertRaises(ValueError):
                    pack.output_path(root / "build/input/new", [root / "build/input"])

    def test_ordered_inputs_and_copy_do_not_modify_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, fallback, destination = [root / name for name in ("first", "fallback", "copy")]
            for directory in (first, fallback, destination):
                directory.mkdir()
            (first / "test.weapon").write_bytes(b"reviewed overlay")
            (fallback / "test.weapon").write_bytes(b"fallback definition")
            selected = pack.resolve_tag([first, fallback], "test.weapon")
            records = pack.copy_tags({"test.weapon": selected}, destination)
            (destination / "test.weapon").write_bytes(b"copy changed")
            pack.verify_inputs(records)
            self.assertEqual((first / "test.weapon").read_bytes(), b"reviewed overlay")
            (first / "linked.weapon").symlink_to(fallback / "test.weapon")
            with self.assertRaises(ValueError):
                pack.resolve_tag([first], "linked.weapon")
            (first / "test.weapon").write_bytes(b"source changed")
            with self.assertRaises(RuntimeError):
                pack.verify_inputs(records)

    def test_namespace_cannot_be_shadowed_by_base_or_case_alias(self):
        selected = {"weapons/smg/smg.weapon": None}
        self.assertEqual(pack.namespace_mapping(selected, {}),
                         {"weapons/smg/smg.weapon": "community/weapon_pack/weapons/smg/smg.weapon"})
        with self.assertRaises(ValueError):
            pack.namespace_mapping(selected, {"Community/Weapon_Pack/weapons/SMG/smg.weapon": None})
        with self.assertRaises(ValueError):
            pack.namespace_mapping({"weapons/smg/smg.weapon": None, "weapons/SMG/smg.weapon": None}, {})

    def test_both_player_stances_must_support_original_weapon_label(self):
        player = {"seat_weapon_labels": {"stand": ["", "ar", "pb"], "crouch": ["", "ar"]}}
        checks = {"smg": {"label": "AR"}, "unarmed": {"label": "unarmed"},
                  "missile": {"label": "99ml"}, "stand_only": {"label": "pb"}}
        self.assertEqual(pack.unsupported_labels(checks, player), {"missile": "99ml", "stand_only": "pb"})
        self.assertEqual(checks["missile"]["label"], "99ml")

    def test_hsc_inputs_match_invader_scope_and_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / "levels/test/bloodgulch/scripts"
            scripts.mkdir(parents=True)
            (root / "global_scripts.hsc").write_text("(global short example 1)")
            (scripts / "original.hsc").write_text("(script startup original (sleep 1))")
            (scripts / "readme.txt").write_text("not a compiler input")
            inputs = pack.script_inputs(root, "levels/test/bloodgulch/bloodgulch.scenario")
            self.assertEqual(set(inputs), {"global_scripts.hsc", "levels/test/bloodgulch/scripts/original.hsc"})
            (scripts / "link.hsc").symlink_to(scripts / "original.hsc")
            with self.assertRaises(ValueError):
                pack.script_inputs(root, "levels/test/bloodgulch/bloodgulch.scenario")


class XboxCacheInspectionTests(unittest.TestCase):
    def cache(self, directory, compressed=False, count=1, name_pointer=None):
        arena = bytearray(512)
        base = 0x803A6000
        struct.pack_into("<4I", arena, 0, base + 32, 0, 0, count)
        struct.pack_into("<8I", arena, 32, 0x77656170, 0, 0, 0,
                         name_pointer if name_pointer is not None else base + 64, 0, 0, 0)
        name = b"community\\weapon_pack\\weapons\\smg\\smg\0"
        arena[64:64 + len(name)] = name
        header = bytearray(2048)
        header[:4], header[-4:] = b"daeh", b"toof"
        struct.pack_into("<5I", header, 4, 5, 2560, 0, 2048, len(arena))
        header[32:39] = b"fixture"
        header[64:64 + len(pack.NTSC_BUILD)] = pack.NTSC_BUILD.encode("ascii")
        struct.pack_into("<H", header, 96, 1)
        path = Path(directory) / "fixture.map"
        path.write_bytes(header + (zlib.compress(arena) if compressed else arena))
        return path

    def test_raw_and_compressed_caches_have_same_weapon_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            for compressed in (False, True):
                path = self.cache(folder, compressed=compressed)
                self.assertEqual(pack.compiled_tag_paths(path),
                                 {(0x77656170, "community/weapon_pack/weapons/smg/smg")})

    def test_external_pointers_and_excessive_tag_counts_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            for changes in ({"count": 32768}, {"name_pointer": 0x803A6000 - 1},
                            {"name_pointer": 0x803A6000 + 512}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    pack.compiled_tag_paths(self.cache(folder, **changes))

    def test_compressed_data_cannot_expand_past_declared_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.cache(folder, compressed=True)
            header = path.read_bytes()[:2048]
            path.write_bytes(header + zlib.compress(bytes(513)))
            with self.assertRaises(ValueError):
                pack.compiled_tag_paths(path)

    def test_xbox_zero_alignment_padding_is_allowed_but_extra_data_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.cache(folder, compressed=True)
            original = path.read_bytes()
            padding = bytes((-len(original)) % 4096)
            path.write_bytes(original + padding)
            self.assertEqual(len(pack.compiled_tag_paths(path)), 1)
            for extra in (padding[:-1] + b"x", padding + bytes(4096), b"extra stream"):
                path.write_bytes(original + extra)
                with self.subTest(extra_length=len(extra)), self.assertRaises(ValueError):
                    pack.compiled_tag_paths(path)

    def test_retail_padding_requires_explicit_retail_reader(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.cache(folder, compressed=True)
            original = path.read_bytes()
            header = bytearray(original[:2048])
            arena = zlib.decompress(original[2048:]) + bytes(1792)
            struct.pack_into("<I", header, 8, 2048 + len(arena))
            struct.pack_into("<I", header, 20, len(arena))
            padded = header + zlib.compress(arena, level=0)
            padded += bytes((-len(padded)) % 2048)
            self.assertNotEqual(len(padded) % 4096, 0)
            path.write_bytes(padded)
            with self.assertRaises(ValueError):
                pack.compiled_tag_paths(path)
            self.assertEqual(len(pack.compiled_tag_paths(path, retail_padding=True)), 1)


class AnimationPayloadAuditTests(unittest.TestCase):
    def graph(self, path, frame_count=2, payload=b"frames"):
        header = bytearray(64)
        header[36:40], header[60:64] = b"antr", b"blam"
        root = bytearray(128)
        struct.pack_into(">I", root, 116, 1)
        clip = bytearray(180)
        clip[:4] = b"idle"
        struct.pack_into(">H", clip, 34, frame_count)
        struct.pack_into(">H", clip, 56, 65535)
        struct.pack_into(">I", clip, 160, len(payload))
        path.write_bytes(header + root + clip + payload)

    def test_clip_payload_changes_are_distinct_from_timing_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            stock, imported = Path(folder) / "stock.model_animations", Path(folder) / "imported.model_animations"
            self.graph(stock)
            self.graph(imported, frame_count=1, payload=b"different")
            audit = compare_clips(stock, imported)
            self.assertEqual(audit["shared_clip_count"], 1)
            self.assertEqual(audit["changed_shared_headers"]["idle"]["changed_fields"],
                             {"frame_count": {"stock": 2, "imported": 1}})
            self.assertIn("idle", audit["changed_shared_payloads"])
            data = imported.read_bytes()
            imported.write_bytes(data[:-1])
            with self.assertRaises(ValueError):
                clip_records(imported)


if __name__ == "__main__":
    unittest.main()
