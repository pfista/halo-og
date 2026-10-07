"""Synthetic ordered HUD-chain lowering and native capacity boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.map_pipeline import hud_anchors as anchors
from tools.map_pipeline.backend import ConversionError
from tools.community_maps import digest

NAME = "authored/custom.weapon_hud_interface"


def definition(parent=None, anchor="top_left", statics=("from_parent", "center", "from_parent")):
    result = {"child_hud": parent, "anchor": anchor, "cutoffs": [9, 8, 7, 6], "flags": {"unchanged": True},
              "messaging": {"token": "authored"}, "crosshairs": [{"data": "keep exact"}],
              "screen_effect": [{"data": "keep exact too"}]}
    for array in anchors.ARRAYS:
        values = statics if array == "static_elements" else ()
        result[array] = [{"anchor": value, "authored_payload": f"{array}:{index}", "scale": 1.25}
                         for index, value in enumerate(values)]
    return result


class Editor:
    def __init__(self, mutation=None):
        self.commands, self.mutation = [], mutation

    def count(self, root, tag, field):
        return len(json.loads((root / tag).read_text())[field])

    def get(self, root, tag, field):
        value = json.loads((root / tag).read_text())
        match = re.fullmatch(r"([a-z_]+)\[(\d+)\]\.anchor", field)
        if match:
            return value[match[1]][int(match[2])]["anchor"]
        return value[field] or anchors.SUFFIX

    def run(self, tool, *args):
        if tool != "edit":
            raise AssertionError(tool)
        self.commands.append(args)
        root, tag = Path(args[args.index("-t") + 1]), args[-1]
        path = root / tag
        value = json.loads(path.read_text())
        index = 2
        while index < len(args) - 1:
            operation, field = args[index:index + 2]
            index += 2
            match = re.fullmatch(r"([a-z_]+)\[(\d+|\*)\](?:\.anchor)?", field)
            if operation == "-E":
                if match[2] == "*":
                    value[match[1]] = []
                else:
                    del value[match[1]][int(match[2])]
            elif operation == "-S":
                target = args[index]
                index += 1
                if match:
                    value[match[1]][int(match[2])]["anchor"] = target
                else:
                    value[field] = target or None
            else:
                raise AssertionError(operation)
        path.write_text(json.dumps(value, sort_keys=True))
        if self.mutation:
            callback, self.mutation = self.mutation, None
            callback()
        return ""


class AnchorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.tags, self.workspace = self.root / "tags", self.root / "workspace"
        self.tags.mkdir(); self.workspace.mkdir()
        self.required, self.steps, self.repairs, self.protected = set(), [], [], {}
        self.tag(NAME, definition())

    def tag(self, name, value):
        path = self.tags / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))
        self.required.add(name)
        return path

    def convert(self, editor=None):
        return anchors.normalize_weapon_hud_anchors(editor or Editor(), [self.tags], self.required,
                                                     self.workspace, self.steps, self.repairs, self.protected)

    def test_contiguous_groups_preserve_full_order_payloads_and_original_owner(self):
        source = definition()
        source["meter_elements"] = [{"anchor": "center", "authored_payload": "meter:0", "scale": 1.25}]
        source["number_elements"] = [{"anchor": "center", "authored_payload": "number:0", "scale": 1.25}]
        source["overlay_elements"] = [{"anchor": "top_left", "authored_payload": "overlay:0", "scale": 1.25}]
        path = self.tag(NAME, source)
        before = path.read_bytes()
        editor = Editor()
        overlay = self.convert(editor)
        self.assertEqual(path.read_bytes(), before)
        change = self.repairs[0]
        self.assertEqual([node["anchor"] for node in change["nodes"]], ["top_left", "center", "top_left", "center", "top_left"])
        reconstructed = []
        previous = None
        for node in change["nodes"]:
            value = json.loads((overlay / node["tag"]).read_text())
            self.assertEqual(value["child_hud"], previous)
            self.assertEqual(value["anchor"], node["anchor"])
            for field in ("cutoffs", "flags", "messaging"):
                self.assertEqual(value[field], source[field])
            self.assertEqual(value["crosshairs"], source["crosshairs"] if node["tag"] == NAME else [])
            self.assertEqual(value["screen_effect"], source["screen_effect"] if node["tag"] == NAME else [])
            for element in node["elements"]:
                stored = value[element["array"]][element["target_index"]]
                expected = copy.deepcopy(source[element["array"]][element["source_index"]])
                expected["anchor"] = "from_parent"
                self.assertEqual(stored, expected)
                reconstructed.append((element["array"], element["source_index"]))
            previous = node["tag"]
        original = [(array, index) for array in anchors.ARRAYS for index in range(len(source[array]))]
        self.assertEqual(reconstructed, original)
        self.assertEqual(change["draw_order_before"], change["draw_order_after"])
        self.assertTrue(change["draw_order_preserved"])
        self.assertTrue(editor.commands)
        snapshot = overlay.parent / "source-snapshots" / NAME
        self.assertEqual(snapshot.read_bytes(), before)
        self.assertEqual(self.protected[snapshot], digest(snapshot))

    def test_original_parent_precedes_generated_nodes_and_lower_precedence_input_is_preserved(self):
        parent = "shared/parent.weapon_hud_interface"
        self.tag(parent, definition(statics=("from_parent",)))
        self.tag(NAME, definition(parent))
        lower = self.root / "lower"
        (lower / NAME).parent.mkdir(parents=True)
        (lower / NAME).write_bytes(b"not selected")
        overlay = anchors.normalize_weapon_hud_anchors(Editor(), [self.tags, lower], self.required,
                                                       self.workspace, self.steps, self.repairs, self.protected)
        self.assertEqual(self.repairs[0]["nodes"][0]["parent"], parent)
        self.assertEqual((lower / NAME).read_bytes(), b"not selected")
        self.assertFalse((overlay / parent).exists())

    def test_repeated_explicit_root_anchor_needs_no_extra_nodes(self):
        self.tag(NAME, definition(statics=("top_left", "from_parent", "top_left")))
        overlay = self.convert()
        self.assertEqual(self.repairs[0]["chain_depth_after"], 1)
        self.assertEqual(len(list(overlay.rglob("*" + anchors.SUFFIX))), 1)
        self.assertTrue(all(item["anchor"] == "from_parent" for item in json.loads((overlay / NAME).read_text())["static_elements"]))

    def test_inherited_only_is_noop(self):
        self.tag(NAME, definition(statics=("from_parent",)))
        editor = Editor()
        self.assertIsNone(self.convert(editor))
        self.assertFalse(editor.commands)
        self.assertFalse((self.workspace / "native-hud-anchors").exists())
        self.assertEqual(self.steps[0]["status"], "unchanged")

    def test_extended_root_child_and_parent_paths_rejected_before_mutation(self):
        for value in (definition(anchor="top_center"), definition(statics=("right_center",)),
                      definition(parent="../other.weapon_hud_interface")):
            with self.subTest(value=value):
                self.protected.clear()
                self.tag(NAME, value)
                editor = Editor()
                with self.assertRaises(ConversionError) as caught:
                    self.convert(editor)
                self.assertEqual(caught.exception.stage, "presentation_anchors")
                self.assertFalse(editor.commands)
                self.assertFalse((self.workspace / "native-hud-anchors").exists())

    def test_cycle_and_absent_parent_fail_before_output(self):
        self.tag(NAME, definition(parent=NAME))
        with self.assertRaisesRegex(ConversionError, "cycle"):
            self.convert()
        self.protected.clear()
        self.tag(NAME, definition(parent="missing/parent.weapon_hud_interface"))
        with self.assertRaisesRegex(ConversionError, "absent"):
            self.convert()
        self.assertFalse((self.workspace / "native-hud-anchors").exists())

    def test_known_native_definitions_keep_native_fields_but_validate_parent_chain(self):
        self.tag(NAME, definition(statics=("right_center",)))
        editor = Editor()
        self.assertIsNone(anchors.normalize_weapon_hud_anchors(
            editor, [self.tags], self.required, self.workspace, self.steps, self.repairs,
            self.protected, native_tags={NAME}))
        self.assertFalse(editor.commands)
        self.assertEqual(self.steps[0]["canonical_native_definitions_skipped"], 1)
        self.protected.clear()
        self.tag(NAME, definition(parent=NAME))
        with self.assertRaisesRegex(ConversionError, "cycle"):
            anchors.normalize_weapon_hud_anchors(
                Editor(), [self.tags], self.required, self.workspace, [], [], {}, native_tags={NAME})

    def test_fifteen_native_definitions_fit_but_sixteen_and_expansion_fail(self):
        graph = {f"n{index}": f"n{index-1}" if index else None for index in range(15)}
        self.assertEqual(anchors._depths(graph)["n14"], 15)
        graph["n15"] = "n14"
        with self.assertRaisesRegex(ConversionError, "fifteen"):
            anchors._depths(graph)
        previous = None
        for index in range(14):
            name = f"parents/p{index:02}{anchors.SUFFIX}"
            self.tag(name, definition(parent=previous, statics=("from_parent",)))
            previous = name
        self.tag(NAME, definition(parent=previous, statics=("from_parent", "center")))
        editor = Editor()
        with self.assertRaisesRegex(ConversionError, "fifteen"):
            self.convert(editor)
        self.assertFalse(editor.commands)
        self.assertFalse((self.workspace / "native-hud-anchors").exists())

    def test_generated_identity_collision_fails_before_output(self):
        source = definition(statics=("from_parent", "center"))
        path = self.tag(NAME, source)
        elements = [{"array": "static_elements", "source_index": index, "source_anchor": value,
                     "effective_anchor": "top_left" if value == "from_parent" else value}
                    for index, value in enumerate(("from_parent", "center"))]
        groups = anchors._groups(elements)
        identity = hashlib.sha256(json.dumps({"tag": NAME, "source_sha256": digest(path), "groups": groups}, sort_keys=True).encode()).hexdigest()[:24]
        collision = self.tags / f"__native_hud/anchors/{identity}_0{anchors.SUFFIX}"
        collision.parent.mkdir(parents=True)
        collision.write_bytes(b"existing data")
        with self.assertRaisesRegex(ConversionError, "collides"):
            self.convert()
        self.assertEqual(collision.read_bytes(), b"existing data")
        self.assertFalse((self.workspace / "native-hud-anchors").exists())

    def test_mutated_input_and_existing_output_are_rejected(self):
        path = self.tags / NAME
        with self.assertRaises(ConversionError) as caught:
            self.convert(Editor(lambda: path.write_bytes(b"changed source")))
        self.assertEqual(caught.exception.code, "input_changed")
        folder = self.workspace / "native-hud-anchors"
        (folder / "keep").write_bytes(b"keep prior output")
        with self.assertRaisesRegex(ConversionError, "fresh"):
            self.convert()
        self.assertEqual((folder / "keep").read_bytes(), b"keep prior output")


if __name__ == "__main__":
    unittest.main()
