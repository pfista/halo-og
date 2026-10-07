"""Synthetic stock-shell closure, source preservation and Unicode boundaries."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from tools.map_pipeline import presentation as shell
from tools.map_pipeline.backend import ConversionError
from tools.community_maps import digest


def unicode_tag(strings):
    header = bytearray(64)
    header[36:40], header[60:64] = b"ustr", b"blam"
    struct.pack_into(">I", header, 44, 64)
    struct.pack_into(">HH", header, 56, 1, 255)
    # Deliberately retain metadata which a reconstruction must not discard.
    header[4:12] = b"metadata"
    reflexive = struct.pack(">III", len(strings), 0x12345678, 0xABCDEF01)
    values = [(text + "\0").encode("utf-16-le") for text in strings]
    entries = [struct.pack(">IIIII", len(value), index + 1, 0x1234, 0x5678, 0x9ABC)
               for index, value in enumerate(values)]
    body = reflexive + b"".join(entries) + b"".join(values)
    struct.pack_into(">I", header, 40, zlib.crc32(body) ^ 0xFFFFFFFF)
    return bytes(header) + body


class FakeInvader:
    def __init__(self, stock, graph=None, mutation=None):
        self.stock, self.graph = stock, graph or {}
        self.calls, self.mutation = [], mutation

    def closure(self, name):
        found, pending = set(), list(self.graph.get(name, []))
        while pending:
            dependency = pending.pop()
            if dependency not in found:
                found.add(dependency)
                pending.extend(self.graph.get(dependency, []))
        return found

    def run(self, tool, *args):
        self.calls.append((tool, args))
        root = Path(args[args.index("-t") + 1])
        name = args[-1]
        path = root / name
        if self.mutation:
            callback, self.mutation = self.mutation, None
            callback()
        if tool == "dependency":
            if name in {shell.IMPLICIT_COLLECTION, shell.COLLECTION}:
                seeds = json.loads(path.read_text())
                result = set(seeds) | self.closure(name)
                for seed in seeds:
                    result.update(self.closure(seed))
                return "\n".join(sorted(result))
            return "\n".join(sorted(self.closure(name)))
        if tool != "edit":
            raise AssertionError(tool)
        if "-C" in args:
            key = args[args.index("-C") + 1]
            return str(len(shell._unicode(path.read_bytes())[3]) if key == "strings"
                       else len(json.loads(path.read_text())))
        if "-G" in args:
            key = args[args.index("-G") + 1]
            return json.loads(path.read_text())[int(key.split("[")[1].split("]")[0])]
        refs = [] if "-N" in args or "-E" in args else json.loads(path.read_text())
        count = int(args[args.index("-I") + 2])
        position = args[args.index("-I") + 3]
        position = len(refs) if position == "end" else int(position)
        refs[position:position] = [None] * count
        for index, arg in enumerate(args):
            if arg == "-S":
                key = args[index + 1]
                refs[int(key.split("[")[1].split("]")[0])] = args[index + 2]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(refs))
        return ""


class ShellOverlayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.stock, self.authored, self.workspace = [self.root / value for value in ("stock", "authored", "workspace")]
        for path in (self.stock, self.authored, self.workspace):
            path.mkdir()
        for name in shell.SEEDS:
            self.tag(self.stock, name, ("canonical:" + name).encode())
            self.tag(self.authored, name, ("imported:" + name).encode())
        self.canonical_references = list(shell.SEEDS[:3])
        self.tag(self.stock, shell.COLLECTION, json.dumps(self.canonical_references).encode())
        self.extra = "sound/sfx/ui/confirmation.sound"
        self.tag(self.stock, self.extra, b"canonical confirmation")
        self.tag(self.authored, self.extra, b"authored confirmation")
        self.graph = {shell.PAUSE_PREFIX + "quit_netgame_button.ui_widget_definition": [self.extra]}
        self.strings = [f"authored entry {index}" for index in range(191)]
        self.strings[72], self.strings[73], self.strings[100] = "ESCAPE = Quit    ENTER = Continue", "ESCAPE = Quit", 'Hold "%s" for score'
        self.text = self.tag(self.authored, shell.TEXT_TAG, unicode_tag(self.strings))
        self.tag(self.stock, shell.TEXT_TAG, unicode_tag([f"stock {index}" for index in range(36)]))
        self.protected, self.steps, self.repairs = {}, [], []

    def tag(self, root, name, data):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_overlay(self, tool=None):
        return shell.canonical_shell_overlay(tool or FakeInvader(self.stock, self.graph), self.stock,
                                             [self.authored, self.stock], self.workspace,
                                             self.steps, self.repairs, self.protected)

    def test_stock_closure_wins_authored_ui_without_gameplay_import(self):
        weapon = self.tag(self.stock, "weapons/ar/ar.weapon", b"stock gameplay must remain separate")
        gameplay = self.tag(self.authored, "weapons/custom/custom.weapon", b"authored gameplay")
        before = {path: digest(path) for root in (self.stock, self.authored) for path in root.rglob("*") if path.is_file()}
        overlay = self.run_overlay()
        for name in (*shell.SEEDS, self.extra):
            if name != shell.COLLECTION:
                self.assertEqual((overlay / name).read_bytes(), (self.stock / name).read_bytes())
        self.assertFalse((overlay / weapon.relative_to(self.stock)).exists())
        self.assertFalse((overlay / gameplay.relative_to(self.authored)).exists())
        self.assertEqual({path: digest(path) for path in before}, before)
        self.assertTrue(set(before).issubset(self.protected))
        residency = json.loads((overlay / shell.IMPLICIT_COLLECTION).read_text())
        self.assertEqual(residency, list(shell.SEEDS))
        compiled = json.loads((overlay / shell.COLLECTION).read_text())
        self.assertEqual(compiled[:len(self.canonical_references)], self.canonical_references)
        self.assertEqual(set(compiled), set(shell.SEEDS) - {shell.COLLECTION})
        self.assertNotIn(shell.IMPLICIT_COLLECTION, compiled)
        soul = next(action for action in self.repairs if action["tag"] == shell.COLLECTION)
        self.assertTrue(soul["compiled_residency_root"])
        self.assertTrue(soul["existing_references_preserved"])
        self.assertFalse(soul["payload_copy_exact"])
        self.assertEqual(soul["sha256_after"], digest(overlay / shell.COLLECTION))
        copied = next(action for action in self.repairs if action["tag"] == shell.SEEDS[0])
        self.assertEqual(copied["sha256_before"], digest(self.authored / shell.SEEDS[0]))
        self.assertEqual(copied["sha256_after"], digest(self.stock / shell.SEEDS[0]))
        self.assertTrue(copied["payload_copy_exact"])
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertTrue(record["source_unchanged"])
        self.assertFalse(record["engine_rules_changed"])
        self.assertEqual(record["presentation_validation"], "pending")

    def test_only_selected_strings_and_size_crc_fields_change(self):
        before = shell._unicode(self.text.read_bytes())
        overlay = self.run_overlay()
        output = (overlay / shell.TEXT_TAG).read_bytes()
        after = shell._unicode(output)
        self.assertEqual(after[0][:40] + after[0][44:], before[0][:40] + before[0][44:])
        self.assertEqual(after[1], before[1])
        for index in range(191):
            if index in shell.FALLBACK_TEXT:
                self.assertEqual(after[3][index], (shell.FALLBACK_TEXT[index] + "\0").encode("utf-16-le"))
                self.assertEqual(after[2][index][4:], before[2][index][4:])
            else:
                self.assertEqual(after[2][index], before[2][index])
                self.assertEqual(after[3][index], before[3][index])
        self.assertEqual(struct.unpack_from(">I", output, 40)[0], zlib.crc32(output[64:]) ^ 0xFFFFFFFF)
        change = next(item for item in self.repairs if item["kind"] == "native_multiplayer_text")
        self.assertEqual(change["entries_replaced"], 3)
        self.assertEqual(change["entries_preserved"], 188)
        self.assertTrue(change["native_reparse_verified"])

    def test_available_stock_strings_are_preferred(self):
        strings = [f"verified Xbox {index}" for index in range(101)]
        self.tag(self.stock, shell.TEXT_TAG, unicode_tag(strings))
        overlay = self.run_overlay()
        values = shell._unicode((overlay / shell.TEXT_TAG).read_bytes())[3]
        for index in shell.FALLBACK_TEXT:
            self.assertEqual(values[index].decode("utf-16-le")[:-1], strings[index])

    def test_fully_resident_stock_collection_is_exact_and_has_no_duplicate_insertions(self):
        refs = [name for name in shell.SEEDS if name != shell.COLLECTION]
        self.tag(self.stock, shell.COLLECTION, json.dumps(refs).encode())
        overlay = self.run_overlay()
        self.assertEqual((overlay / shell.COLLECTION).read_bytes(), (self.stock / shell.COLLECTION).read_bytes())
        action = next(item for item in self.repairs if item["tag"] == shell.COLLECTION)
        self.assertEqual(action["inserted_references"], [])
        self.assertTrue(action["payload_copy_exact"])

    def test_short_authored_list_uses_native_fallback_without_extending_or_copying(self):
        self.text.write_bytes(unicode_tag(["authored short"] * 36))
        overlay = self.run_overlay()
        self.assertFalse((overlay / shell.TEXT_TAG).exists())
        self.assertEqual(self.steps[-1]["text_entries_replaced"], 0)

    def test_existing_stock_implicit_collection_drops_gameplay_edges(self):
        self.tag(self.stock, shell.IMPLICIT_COLLECTION, json.dumps(["weapons/stock.weapon"]).encode())
        overlay = self.run_overlay()
        self.assertEqual(json.loads((overlay / shell.IMPLICIT_COLLECTION).read_text()), list(shell.SEEDS))
        action = next(item for item in self.repairs if item["tag"] == shell.IMPLICIT_COLLECTION)
        self.assertIsNotNone(action["source_sha256"])
        self.assertFalse(action["payload_copy_exact"])

    def test_disallowed_missing_and_unsafe_dependencies_fail_before_output(self):
        for name in ("weapons/custom.weapon", "levels/other.scenario", "globals/globals.globals",
                     "../escape.bitmap", "/absolute.bitmap", "ui/missing.bitmap"):
            with self.subTest(name=name):
                if name.endswith((".weapon", ".scenario", ".globals")):
                    self.tag(self.stock, name, b"not UI")
                tool = FakeInvader(self.stock, {shell.COLLECTION: [name]})
                with self.assertRaises(ConversionError):
                    self.run_overlay(tool)
                self.assertFalse((self.workspace / "native-shell").exists())
                self.assertFalse(self.repairs)

    def test_missing_seed_and_linked_input_rejected(self):
        seed = self.stock / shell.SEEDS[0]
        seed.unlink()
        with self.assertRaises(ConversionError):
            self.run_overlay()
        target = self.root / "external"
        target.write_bytes(b"linked input")
        seed.symlink_to(target)
        with self.assertRaises((ConversionError, ValueError)):
            self.run_overlay()
        self.assertFalse((self.workspace / "native-shell").exists())

    def test_mutated_source_and_prior_protected_hash_rejected(self):
        tool = FakeInvader(self.stock, self.graph, lambda: self.text.write_bytes(b"mutated source"))
        with self.assertRaisesRegex(ConversionError, "changed"):
            self.run_overlay(tool)
        self.assertFalse((self.workspace / "native-shell").exists())
        self.protected[self.text] = "0" * 64
        with self.assertRaisesRegex(ConversionError, "changed before"):
            self.run_overlay()

    def test_existing_overlay_is_preserved(self):
        folder = self.workspace / "native-shell"
        folder.mkdir()
        (folder / "keep").write_bytes(b"prior output")
        tool = FakeInvader(self.stock, self.graph)
        with self.assertRaisesRegex(ConversionError, "fresh"):
            self.run_overlay(tool)
        self.assertEqual((folder / "keep").read_bytes(), b"prior output")
        self.assertFalse(tool.calls)

    def test_unicode_bounds_termination_and_surrogates_rejected(self):
        original = unicode_tag(["okay"])
        cases = [original[:-1], original + b"trailing"]
        for offset, value in [(64, 801), (76, 1), (76, 32770), (44, 128)]:
            modified = bytearray(original)
            struct.pack_into(">I", modified, offset, value)
            cases.append(bytes(modified))
        bad = bytearray(original)
        bad[-2:] = b"x\0"
        cases.append(bytes(bad))
        bad = bytearray(original)
        bad[-4:-2] = b"\0\xd8"
        cases.append(bytes(bad))
        for data in cases:
            with self.subTest(data=data.hex()):
                with self.assertRaises(ConversionError):
                    shell._unicode(data)


if __name__ == "__main__":
    unittest.main()
