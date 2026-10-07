"""Container inventory boundaries; synthetic headers do not prove playability."""

import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

try:
    from tools.map_pipeline import formats
except ModuleNotFoundError:
    from map_pipeline import formats


def cache_bytes(version=7, *, declared=None, file_bytes=0x900, name="authored_name",
                build="01.00.00.0564", scenario_type=1, tag_offset=0x840,
                tag_bytes=0x40):
    result = bytearray(file_bytes)
    if version == 6:
        result[0x2C0:0x2C4] = struct.pack("<I", 0x45686564)  # Ehed, little endian
        result[0x5F0:0x5F4] = struct.pack("<I", 0x47666F74)  # Gfot, little endian
        offsets = {"version": 0x588, "declared": 0x5E8, "tag_offset": 0x5EC,
                   "tag_bytes": 0x2C4, "name": 0x58C, "build": 0x2C8, "type": 2}
    else:
        result[:4] = struct.pack("<I", 0x68656164)
        result[0x7FC:0x800] = struct.pack("<I", 0x666F6F74)
        offsets = {"version": 4, "declared": 8, "tag_offset": 0x10,
                   "tag_bytes": 0x14, "name": 0x20, "build": 0x40, "type": 0x60}
    for field, value in (("version", version), ("declared", file_bytes if declared is None else declared),
                         ("tag_offset", tag_offset), ("tag_bytes", tag_bytes)):
        struct.pack_into("<I", result, offsets[field], value)
    struct.pack_into("<H", result, offsets["type"], scenario_type)
    for field, value in (("name", name), ("build", build)):
        value = value.encode("ascii")
        if len(value) > 31:
            raise ValueError("fixture string is too long")
        result[offsets[field]:offsets[field] + 32] = value + bytes(32 - len(value))
    return result


def resource_bytes(kind=1):
    data = b"resource-content"
    names = b"tag\\example\0"
    names_offset = 16 + len(data)
    index_offset = names_offset + len(names)
    return bytearray(struct.pack("<4I", kind, names_offset, index_offset, 1) +
                     data + names + struct.pack("<3I", 0, len(data), 16))


class FormatInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="map-format-inventory-")
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, data, filename="different_filename.map"):
        path = self.folder / filename
        path.write_bytes(data)
        return path

    def assert_failure(self, data, code, field=None):
        path = self.write(data)
        with self.assertRaises(formats.FormatError) as captured:
            formats.inspect_cache(path)
        error = captured.exception
        self.assertEqual(error.code, code)
        if field is not None:
            self.assertEqual(error.field, field)
        self.assertTrue(error.message)
        self.assertTrue(error.suggested_fix)
        self.assertEqual(error.to_dict()["message"], str(error))
        self.assertIsInstance(error, ValueError)
        self.assertEqual(path.read_bytes(), data)
        return error

    def test_all_supported_versions_preserve_header_identity_and_source_bytes(self):
        for version, expected_format in ((5, "xbox"), (6, "pc-demo"), (7, "pc"),
                                         (609, "custom-edition"), (13, "mcc")):
            with self.subTest(version=version):
                original = cache_bytes(version)
                path = self.write(original)
                info = formats.inspect_cache(path)
                self.assertEqual(info["version"], version)
                self.assertEqual(info["format"], expected_format)
                self.assertEqual(info["name"], "authored_name")
                self.assertNotEqual(path.stem, info["name"])
                self.assertEqual(info["build"], "01.00.00.0564")
                self.assertEqual(info["type"], 1)
                self.assertEqual(info["file_bytes"], 0x900)
                self.assertEqual(info["declared_bytes"], 0x900)
                self.assertEqual(info["tag_bytes"], 0x40)
                self.assertEqual(info["tag_data_offset"], 0x840)
                self.assertEqual(info["header_layout"], "pc-demo" if version == 6 else "standard")
                self.assertEqual(info["sha256"], hashlib.sha256(original).hexdigest())
                self.assertEqual(path.read_bytes(), original)

    def test_demo_layout_uses_distinct_offsets_and_signatures(self):
        data = cache_bytes(6, name="demo_level", build="01.00.00.0576", scenario_type=0)
        # Ordinary header fields contain unrelated padding; no fallback reads.
        struct.pack_into("<I", data, 4, 0xDEADBEEF)
        data[0x20:0x40] = b"X" * 32
        data[0x40:0x60] = b"Y" * 32
        info = formats.inspect_cache(self.write(data))
        self.assertEqual((info["name"], info["build"], info["type"]),
                         ("demo_level", "01.00.00.0576", 0))
        data[0x5F0:0x5F4] = b"Gfot"  # Wrong byte order must fail.
        self.assert_failure(data, "bad_signature", "footer_signature")

    def test_demo_version_in_standard_header_is_rejected(self):
        data = cache_bytes(7)
        struct.pack_into("<I", data, 4, 6)
        self.assert_failure(data, "wrong_header_layout", "version")

    def test_non_demo_version_in_demo_header_is_rejected(self):
        data = cache_bytes(6)
        struct.pack_into("<I", data, 0x588, 7)
        self.assert_failure(data, "wrong_header_layout", "version")

    def test_zero_pc_declarations_use_file_bound_and_are_not_fabricated(self):
        for version in (6, 7, 609, 13):
            with self.subTest(version=version):
                info = formats.inspect_cache(self.write(cache_bytes(version, declared=0)))
                self.assertEqual(info["declared_bytes"], 0)
                self.assertEqual(info["file_bytes"], 0x900)

    def test_compressed_xbox_tag_range_uses_declared_size(self):
        data = cache_bytes(5, file_bytes=0x900, declared=0x20000,
                           tag_offset=0x1F000, tag_bytes=0x1000)
        info = formats.inspect_cache(self.write(data))
        self.assertGreater(info["tag_data_offset"], info["file_bytes"])
        self.assertEqual(info["declared_bytes"], 0x20000)
        # A header inventory does not decompress or certify this synthetic body.
        struct.pack_into("<I", data, 0x14, 0x1001)
        self.assert_failure(data, "invalid_tag_range", "tag_data_range")

    def test_xbox_zero_declaration_is_rejected(self):
        self.assert_failure(cache_bytes(5, declared=0), "invalid_declared_size", "declared_bytes")

    def test_uncompressed_declaration_larger_than_file_is_rejected(self):
        for version in (6, 7, 609, 13):
            with self.subTest(version=version):
                self.assert_failure(cache_bytes(version, declared=0x901),
                                    "invalid_declared_size", "declared_bytes")

    def test_invalid_tag_offset_size_and_addition_bounds(self):
        for tag_offset, tag_bytes in ((0x7FF, 0x40), (0x840, 0x27),
                                      (0x900, 0x28), (0xFFFFFFFF, 0xFFFFFFFF)):
            with self.subTest(tag_offset=tag_offset, tag_bytes=tag_bytes):
                self.assert_failure(cache_bytes(7, tag_offset=tag_offset, tag_bytes=tag_bytes),
                                    "invalid_tag_range", "tag_data_range")

    def test_tag_data_cannot_point_into_trailing_undeclared_bytes(self):
        self.assert_failure(cache_bytes(7, declared=0x830), "invalid_tag_range", "tag_data_range")

    def test_truncated_cache_and_resource_headers(self):
        for data in (b"", bytes(15), cache_bytes(7)[:0x7FF]):
            with self.subTest(length=len(data)):
                self.assert_failure(data, "truncated_header", "file_bytes")

    def test_bad_standard_signatures(self):
        data = cache_bytes(7)
        data[0x7FC:0x800] = b"foot"
        self.assert_failure(data, "bad_signature", "footer_signature")
        data[:4] = b"head"
        self.assert_failure(data, "bad_signature", "header_signature")

    def test_unknown_version_has_actionable_diagnostic(self):
        error = self.assert_failure(cache_bytes(88), "unsupported_version", "version")
        self.assertEqual(error.value, 88)
        self.assertIn("v609", error.suggested_fix)

    def test_unterminated_and_non_ascii_header_strings(self):
        for field, offset in (("name", 0x20), ("build", 0x40)):
            with self.subTest(field=field):
                data = cache_bytes(7)
                data[offset:offset + 32] = b"X" * 32
                self.assert_failure(data, "unterminated_string", field)
                data[offset:offset + 32] = b"\xFF\0" + bytes(30)
                self.assert_failure(data, "invalid_string", field)

    def test_invalid_scenario_type(self):
        self.assert_failure(cache_bytes(7, scenario_type=3), "invalid_scenario_type", "type")

    def test_resource_maps_are_classified_by_header_not_filename(self):
        for kind, resource_type in ((1, "bitmaps"), (2, "sounds"), (3, "loc")):
            with self.subTest(kind=kind):
                data = resource_bytes(kind)
                info = formats.inspect_cache(self.write(data, "renamed.map"))
                self.assertEqual(info["format"], "resource")
                self.assertEqual(info["resource_type"], resource_type)
                self.assertEqual(info["resource_entries"], 1)
                self.assertEqual(info["header_layout"], "resource")
                self.assertIsNone(info["version"])
                self.assertIsNone(info["tag_bytes"])
                self.assertEqual(info["sha256"], hashlib.sha256(data).hexdigest())

    def test_resource_filename_cannot_hide_invalid_cache(self):
        self.assert_failure(b"broken resource file!", "truncated_header")
        path = self.write(cache_bytes(13), "bitmaps.map")
        self.assertEqual(formats.inspect_cache(path)["format"], "mcc")

    def test_empty_resource_table_is_bounded(self):
        info = formats.inspect_cache(self.write(struct.pack("<4I", 1, 16, 16, 0)))
        self.assertEqual(info["resource_entries"], 0)

    def test_resource_header_table_order_count_and_end_bounds(self):
        original = resource_bytes()
        for field_offset, value in ((4, 15), (4, len(original) + 1),
                                    (8, 16), (8, len(original) + 1), (12, 0xFFFFFFFF)):
            with self.subTest(field_offset=field_offset, value=value):
                data = bytearray(original)
                struct.pack_into("<I", data, field_offset, value)
                self.assert_failure(data, "invalid_resource_header", "resource_header")

    def test_resource_entry_name_and_data_bounds(self):
        original = resource_bytes()
        index_offset = struct.unpack_from("<I", original, 8)[0]
        for field_offset, value, code in ((0, 0xFFFFFFFF, "invalid_resource_name"),
                                         (4, 0xFFFFFFFF, "invalid_resource_range"),
                                         (8, 0xFFFFFFFF, "invalid_resource_range"),
                                         (8, 0, "invalid_resource_range")):
            with self.subTest(field_offset=field_offset, value=value):
                data = bytearray(original)
                struct.pack_into("<I", data, index_offset + field_offset, value)
                self.assert_failure(data, code)
        original[index_offset - 1] = ord("X")
        self.assert_failure(original, "unterminated_resource_name", "resources[0].name")

    def test_missing_and_non_regular_sources_are_structured_errors(self):
        for path, expected in ((self.folder / "missing.map", "source_unavailable"),
                               (self.folder, "not_regular_file")):
            with self.subTest(path=path):
                with self.assertRaises(formats.FormatError) as captured:
                    formats.inspect_cache(path)
                self.assertEqual(captured.exception.code, expected)

    def test_symlink_source_is_rejected_even_when_target_is_valid(self):
        target = self.write(cache_bytes(7), "actual.map")
        link = self.folder / "alias.map"
        link.symlink_to(target)
        with self.assertRaises(formats.FormatError) as captured:
            formats.inspect_cache(link)
        self.assertEqual(captured.exception.code, "symlink_source")
        self.assertEqual(target.read_bytes(), cache_bytes(7))

    def test_replacement_during_inventory_does_not_return_stale_identity(self):
        path = self.write(cache_bytes(7))
        replacement = self.write(cache_bytes(13, name="replacement"), "replacement.map")
        inspect_header = formats._inspect_header

        def replace_after_header(header, file_bytes):
            info = inspect_header(header, file_bytes)
            replacement.replace(path)
            return info

        with patch.object(formats, "_inspect_header", side_effect=replace_after_header):
            with self.assertRaises(formats.FormatError) as captured:
                formats.inspect_cache(path)
        self.assertEqual(captured.exception.code, "source_changed")

    def test_hash_covers_more_than_first_chunk(self):
        data = cache_bytes(7, file_bytes=formats.HASH_CHUNK_BYTES + 17)
        data[-17:] = b"nonheader content"
        info = formats.inspect_cache(self.write(data))
        self.assertEqual(info["sha256"], hashlib.sha256(data).hexdigest())
        data[-1] ^= 1
        changed_info = formats.inspect_cache(self.write(data))
        self.assertNotEqual(info["sha256"], changed_info["sha256"])

    def test_discovery_includes_invalid_and_resource_entries_in_stable_order(self):
        self.write(cache_bytes(7), "Z.map")
        resource = self.write(resource_bytes(), "bitmaps.map")
        invalid = self.write(b"broken", "A.MAP")
        self.write(b"ignored", "note.txt")
        folder = self.folder / "nested"
        folder.mkdir()
        nested = folder / "b.map"
        nested.write_bytes(cache_bytes(609))
        expected = [invalid, resource, self.folder / "Z.map"]
        self.assertEqual(formats.discover_maps(self.folder), expected)
        self.assertEqual(formats.discover_maps(self.folder, recursive=True),
                         [invalid, resource, nested, self.folder / "Z.map"])
        with self.assertRaises(formats.FormatError):
            formats.inspect_cache(invalid)

    def test_discovery_keeps_map_named_directories_for_diagnostics(self):
        folder = self.folder / "bad.map"
        folder.mkdir()
        self.assertEqual(formats.discover_maps(self.folder), [folder])
        with self.assertRaises(formats.FormatError) as captured:
            formats.inspect_cache(folder)
        self.assertEqual(captured.exception.code, "not_regular_file")

    def test_discovery_rejects_dangling_map_symlink_and_recursive_directory_symlink(self):
        link = self.folder / "missing.map"
        link.symlink_to(self.folder / "no-source.map")
        with self.assertRaises(formats.FormatError) as captured:
            formats.discover_maps(self.folder)
        self.assertEqual(captured.exception.code, "symlink_source")
        link.unlink()
        nested = self.folder / "nested"
        nested.mkdir()
        (self.folder / "linked-folder").symlink_to(nested, target_is_directory=True)
        self.assertEqual(formats.discover_maps(self.folder), [])
        with self.assertRaises(formats.FormatError) as captured:
            formats.discover_maps(self.folder, recursive=True)
        self.assertEqual(captured.exception.code, "symlink_source")

    def test_discovery_rejects_invalid_root(self):
        with self.assertRaises(formats.FormatError) as captured:
            formats.discover_maps(self.folder / "missing")
        self.assertEqual(captured.exception.code, "invalid_directory")

    def test_discovery_callback_rejects_links_and_keeps_safe_siblings(self):
        first = self.write(cache_bytes(7), "A.map")
        last = self.write(resource_bytes(), "Z.map")
        dangling = self.folder / "broken.map"
        dangling.symlink_to(self.folder / "missing.map")
        nested = self.folder / "nested"
        nested.mkdir()
        child = nested / "child.map"
        child.write_bytes(cache_bytes(609))
        linked_folder = self.folder / "linked-folder"
        linked_folder.symlink_to(nested, target_is_directory=True)
        failures = []
        found = formats.discover_maps(self.folder, recursive=True,
                                      on_error=lambda entry, error: failures.append((entry, error)))
        self.assertEqual(found, [first, child, last])
        self.assertEqual([entry for entry, _ in failures], [dangling, linked_folder])
        self.assertEqual([error.code for _, error in failures], ["symlink_source"] * 2)
        self.assertEqual([error.value for _, error in failures],
                         [str(dangling), str(linked_folder)])
        self.assertEqual(len([path for path in found if path.name == "child.map"]), 1)

    def test_discovery_callback_reports_unreadable_folder_and_continues_siblings(self):
        blocked = self.folder / "blocked"
        blocked.mkdir()
        (blocked / "hidden.map").write_bytes(cache_bytes(7))
        good = self.folder / "good"
        good.mkdir()
        child = good / "child.map"
        child.write_bytes(cache_bytes(609))
        last = self.write(resource_bytes(), "Z.map")
        original_iterdir = Path.iterdir

        def iterdir(folder):
            if folder == blocked:
                raise PermissionError("synthetic unreadable directory")
            return original_iterdir(folder)

        failures = []
        with patch.object(Path, "iterdir", iterdir):
            found = formats.discover_maps(self.folder, recursive=True,
                                          on_error=lambda entry, error: failures.append((entry, error)))
        self.assertEqual(found, [child, last])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], blocked)
        self.assertEqual(failures[0][1].code, "directory_unavailable")
        self.assertEqual(failures[0][1].value, str(blocked))
        with patch.object(Path, "iterdir", iterdir):
            with self.assertRaises(formats.FormatError) as captured:
                formats.discover_maps(self.folder, recursive=True)
        self.assertEqual(captured.exception.value, str(blocked))

    def test_discovery_callback_reports_entry_stat_failure_and_keeps_other_maps(self):
        unavailable = self.write(cache_bytes(7), "A.map")
        good = self.write(resource_bytes(), "Z.map")
        original_lstat = Path.lstat

        def lstat(entry):
            if entry == unavailable:
                raise FileNotFoundError("synthetic entry removed after listing")
            return original_lstat(entry)

        failures = []
        with patch.object(Path, "lstat", lstat):
            found = formats.discover_maps(self.folder,
                                          on_error=lambda entry, error: failures.append((entry, error)))
        self.assertEqual(found, [good])
        self.assertEqual(failures[0][0], unavailable)
        self.assertEqual(failures[0][1].code, "directory_unavailable")

    def test_discovery_callback_does_not_suppress_invalid_root_or_callback_failure(self):
        failures = []
        with self.assertRaises(formats.FormatError) as captured:
            formats.discover_maps(self.folder / "missing",
                                  on_error=lambda entry, error: failures.append((entry, error)))
        self.assertEqual(captured.exception.code, "invalid_directory")
        self.assertEqual(failures, [])
        (self.folder / "broken.map").symlink_to(self.folder / "missing.map")

        def fail(entry, error):
            raise RuntimeError("callback failed")

        with self.assertRaisesRegex(RuntimeError, "callback failed"):
            formats.discover_maps(self.folder, on_error=fail)


if __name__ == "__main__":
    unittest.main()
