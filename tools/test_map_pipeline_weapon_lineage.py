"""Reviewed lineage is exact source binding, never admission by tag name."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.map_pipeline import profiles, weapon_lineage as lineage


WEAPON = "weapons/recovered/prototype.weapon"
MODEL = "weapons/recovered/prototype.gbxmodel"


def catalog_fixture(outcome="original-completion"):
    return {"schema_version": 1, "id": "reviewed-halo1", "version": "1.0.0", "entries": [{
        "asset_id": "prototype", "variant_id": "reviewed-v1", "weapon": WEAPON,
        "weapon_sha256": "a" * 64,
        "identity": {"model": MODEL, "weapon_type": "undefined", "label": "ar"},
        "closure_sha256": {WEAPON: "a" * 64, MODEL: "b" * 64}, "outcome": outcome,
        "ancestor": {"kind": "recovered-halo1", "asset_id": "halo1-prototype", "stock_weapon": None},
        "evidence": [{"title": "Reviewed original-source evidence", "url": "https://example.org/review/halo1"}],
        "reason": "Exact reviewed recovered Halo 1 implementation; runtime validation pending"}]}


def approval_fixture():
    return {"kind": "user-decision", "date": "2026-10-08",
            "reference": "thread://01a116b1-1414-7ea2-ad25-7cdf34ebce54",
            "statement": "User explicitly permits this exact community weapon variant without asserting Halo 1 ancestry"}


class CatalogTests(unittest.TestCase):
    def test_exact_raw_gbxmodel_match_and_validation_do_not_mutate_input(self):
        source = catalog_fixture()
        before = copy.deepcopy(source)
        catalog = lineage.validate_catalog(source)
        entry = catalog["entries"][0]
        matched, mismatch = lineage.match_variant(catalog, WEAPON, entry["identity"], entry["closure_sha256"])
        self.assertEqual((matched, mismatch), (entry, []))
        matched["reason"] = "changed return value"
        catalog["entries"][0]["evidence"][0]["title"] = "changed validated value"
        self.assertEqual(source, before)

    def test_hash_bound_loader_records_exact_file_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalog.json"
            data = json.dumps(catalog_fixture(), indent=2).encode()
            path.write_bytes(data)
            expected = hashlib.sha256(data).hexdigest()
            loaded = lineage.load_catalog(path, expected)
            self.assertEqual(lineage.catalog_metadata(loaded),
                             {"id": "reviewed-halo1", "version": "1.0.0", "sha256": expected})
            self.assertEqual(loaded["path"], str(path.resolve()))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                lineage.load_catalog(path, "c" * 64)
            path.write_bytes(data + b"\n")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                lineage.load_catalog(path, expected)

    def test_unknown_weapon_never_matches_by_basename(self):
        catalog = lineage.validate_catalog(catalog_fixture())
        entry = catalog["entries"][0]
        match, errors = lineage.match_variant(catalog, "other/prototype.weapon", entry["identity"],
                                              entry["closure_sha256"])
        self.assertIsNone(match)
        self.assertIn("No reviewed", errors[0]["reason"])

    def test_complete_closure_reports_changed_missing_and_extra_dependencies(self):
        catalog = lineage.validate_catalog(catalog_fixture())
        entry = catalog["entries"][0]
        actual = {WEAPON: "c" * 64, "other/effect.effect": "d" * 64}
        match, errors = lineage.match_variant(catalog, WEAPON, entry["identity"], actual)
        self.assertIsNone(match)
        self.assertEqual(errors[0]["missing_tags"], [MODEL])
        self.assertEqual(errors[0]["extra_tags"], ["other/effect.effect"])
        self.assertEqual(errors[0]["changed_dependencies"], {WEAPON: {"expected": "a" * 64, "actual": "c" * 64}})

    def test_raw_identity_changes_are_not_hidden_by_working_model_conversion(self):
        catalog = lineage.validate_catalog(catalog_fixture())
        entry = catalog["entries"][0]
        identity = {"model": MODEL.replace(".gbxmodel", ".model"), "weapon_type": "rifle", "label": "br"}
        match, errors = lineage.match_variant(catalog, WEAPON, identity, entry["closure_sha256"])
        self.assertIsNone(match)
        self.assertEqual(set(errors[0]["identity_changes"]), {"model", "weapon_type", "label"})

    def test_matching_unsupported_and_unverified_outcomes_stay_explicit(self):
        for outcome in ("unsupported", "unverified"):
            value = catalog_fixture(outcome)
            value["entries"][0].update(ancestor=None, evidence=[])
            catalog = lineage.validate_catalog(value)
            entry = catalog["entries"][0]
            match, errors = lineage.match_variant(catalog, WEAPON, entry["identity"], entry["closure_sha256"])
            self.assertEqual(match["outcome"], outcome)
            self.assertNotIn(outcome, lineage.ADMITTED)
            self.assertEqual(errors, [])

    def test_explicit_community_exception_has_approval_instead_of_fabricated_ancestor(self):
        value = catalog_fixture("approved-community")
        entry = value["entries"][0]
        entry.update(ancestor=None, evidence=[], approval=approval_fixture())
        before = copy.deepcopy(value)
        validated = lineage.validate_catalog(value)
        match, errors = lineage.match_variant(validated, WEAPON, entry["identity"], entry["closure_sha256"])
        self.assertEqual(errors, [])
        self.assertEqual(match["outcome"], "approved-community")
        self.assertIsNone(match["ancestor"])
        self.assertEqual(match["approval"], approval_fixture())
        self.assertIn(match["outcome"], lineage.ADMITTED)
        self.assertEqual(value, before)
        mutated = {**entry["closure_sha256"], MODEL: "c" * 64}
        self.assertIsNone(lineage.match_variant(validated, WEAPON, entry["identity"], mutated)[0])
        for changes in ({"ancestor": catalog_fixture()["entries"][0]["ancestor"]}, {"approval": None}):
            candidate = copy.deepcopy(value)
            candidate["entries"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                lineage.validate_catalog(candidate)
        entry.pop("approval")
        with self.assertRaisesRegex(ValueError, "user approval"):
            lineage.validate_catalog(value)

    def test_original_completion_user_confirmation_retains_ancestry_requirements(self):
        value = catalog_fixture()
        value["entries"][0]["approval"] = approval_fixture()
        self.assertEqual(lineage.validate_catalog(value), value)
        for changes in ({"ancestor": None}, {"evidence": []}, {"outcome": "unverified"}):
            candidate = copy.deepcopy(value)
            candidate["entries"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                lineage.validate_catalog(candidate)

    def test_explicit_omission_requires_approval_and_exact_variant_without_admission(self):
        value = catalog_fixture("omit")
        approval = {**approval_fixture(), "statement": "Omit this exact weapon variant's references and report every omission"}
        entry = value["entries"][0]
        entry.update(ancestor=None, evidence=[], approval=approval)
        catalog = lineage.validate_catalog(value)
        match, errors = lineage.match_variant(catalog, WEAPON, entry["identity"], entry["closure_sha256"])
        self.assertEqual(errors, [])
        self.assertEqual((match["outcome"], match["approval"], match["ancestor"]), ("omit", approval, None))
        self.assertNotIn("omit", lineage.ADMITTED)
        mutated = {**entry["closure_sha256"], MODEL: "c" * 64}
        match, errors = lineage.match_variant(catalog, WEAPON, entry["identity"], mutated)
        self.assertIsNone(match)
        self.assertEqual(errors[0]["changed_dependencies"][MODEL]["actual"], "c" * 64)
        for changes in ({"approval": None}, {"ancestor": catalog_fixture()["entries"][0]["ancestor"]}):
            candidate = copy.deepcopy(value)
            candidate["entries"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                lineage.validate_catalog(candidate)
        entry.pop("approval")
        with self.assertRaisesRegex(ValueError, "user approval"):
            lineage.validate_catalog(value)

    def test_approval_schema_rejects_invalid_dates_references_types_and_controls(self):
        invalid = [None, {}, {**approval_fixture(), "extra": True}]
        invalid += [{**approval_fixture(), **changes} for changes in (
            {"kind": "author-claim"}, {"date": "2026-02-29"}, {"date": "2026-13-01"},
            {"date": "20261008"}, {"date": True}, {"date": "2026-10-08\n"},
            {"reference": "https://example.org/approval"},
            {"reference": "thread://01A116b1-1414-7ea2-ad25-7cdf34ebce54"},
            {"reference": approval_fixture()["reference"] + "?hostId=local"},
            {"reference": approval_fixture()["reference"] + "\n"},
            {"statement": ""}, {"statement": "changed\nline"}, {"statement": "control\u0085"},
            {"statement": "a" * 4097}, {"statement": False})]
        for approval in invalid:
            value = catalog_fixture("approved-community")
            value["entries"][0].update(ancestor=None, evidence=[], approval=approval)
            with self.subTest(approval=approval), self.assertRaises(ValueError):
                lineage.validate_catalog(value)
        value["entries"][0]["approval"] = {**approval_fixture(), "date": "2024-02-29"}
        self.assertEqual(lineage.validate_catalog(value), value)

    def test_admitted_variants_require_ancestor_evidence_and_native_canonical_target(self):
        for changes in ({"ancestor": None}, {"evidence": []}, {"outcome": "canonical-stock"}):
            value = catalog_fixture()
            value["entries"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                lineage.validate_catalog(value)
        value = catalog_fixture("canonical-stock")
        value["entries"][0]["ancestor"].update(kind="retail-xbox", stock_weapon="weapons/pistol/pistol.weapon")
        self.assertEqual(lineage.validate_catalog(value), value)

    def test_strict_schema_rejects_invalid_fields_types_and_hashes(self):
        changes = [{"extra": True}, {"weapon_sha256": "A" * 64}, {"weapon_sha256": "b" * 64},
                   {"closure_sha256": {}}, {"outcome": "admit"}, {"identity": {"model": MODEL}},
                   {"identity": {"model": {}, "weapon_type": "undefined", "label": "ar"}},
                   {"ancestor": {"kind": {}, "asset_id": "a", "stock_weapon": None}},
                   {"reason": "contains\ncontrol"}, {"variant_id": "../outside"},
                   {"evidence": [{"title": "Credentials", "url": "https://user:pass@example.org/"}]}]
        for changes in changes:
            value = catalog_fixture()
            value["entries"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                lineage.validate_catalog(value)
        for changes in ({"schema_version": True}, {"schema_version": 2}, {"entries": {}}, {"extra": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                lineage.validate_catalog({**catalog_fixture(), **changes})

    def test_portable_paths_reject_escape_aliases_and_wrong_tag_classes(self):
        for path in ("/absolute.weapon", "../escape.weapon", "a/../escape.weapon", "a//b.weapon",
                     "a/./b.weapon", "a\\b.weapon", "C:/a.weapon", "a.weapon\n", ".weapon", "a.bitmap"):
            value = catalog_fixture()
            value["entries"][0]["weapon"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                lineage.validate_catalog(value)

    def test_duplicate_ids_and_conflicting_exact_variants_rejected(self):
        value = catalog_fixture()
        value["entries"].append(copy.deepcopy(value["entries"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            lineage.validate_catalog(value)
        value["entries"][1].update(variant_id="different-id", outcome="unsupported")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            lineage.validate_catalog(value)

    def test_duplicate_json_keys_symlinks_and_oversized_files_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalog.json"
            path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaisesRegex(ValueError, "duplicate key"):
                lineage.load_catalog(path)
            link = path.with_name("link.json")
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlink"):
                lineage.load_catalog(link)
            with path.open("wb") as stream:
                stream.truncate(lineage.MAX_CATALOG_BYTES + 1)
            with self.assertRaisesRegex(ValueError, "8 MiB"):
                lineage.load_catalog(path)


class CatalogProfileTests(unittest.TestCase):
    def profile(self):
        value = json.loads((profiles.PROFILE_ROOT / "authored-xbox-v5.json").read_text())
        value["weapon_policy"] = "bungie-originals"
        return value

    def test_legacy_profile_defaults_to_no_lineage_catalog_and_hash_changes_when_selected(self):
        source = self.profile()
        before = copy.deepcopy(source)
        normalized = profiles.validate_profile(source)
        self.assertIsNone(normalized["weapon_lineage_catalog"])
        self.assertEqual(source, before)
        selected = {"file": "catalogs/reviewed.json", "sha256": "a" * 64}
        explicit = profiles.validate_profile({**source, "weapon_lineage_catalog": selected})
        self.assertNotEqual(explicit["sha256"], normalized["sha256"])
        self.assertNotEqual(profiles.validate_profile({**source, "weapon_lineage_catalog": {**selected, "sha256": "b" * 64}})["sha256"], explicit["sha256"])

    def test_catalog_selection_requires_original_weapons_authored_priority_and_portable_json(self):
        selected = {"file": "catalogs/reviewed.json", "sha256": "a" * 64}
        for changes in ({"weapon_policy": "preserve"}, {"dependency_policy": "stock-first"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                profiles.validate_profile({**self.profile(), "weapon_lineage_catalog": selected, **changes})
        for path in ("../a.json", "/a.json", "a//b.json", "a\\b.json", "a.json/../b.json", ".json", "a.map"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                profiles.validate_profile({**self.profile(), "weapon_lineage_catalog": {**selected, "file": path}})

    def test_loaded_catalog_metadata_and_paths_do_not_change_portable_profile_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            catalog = base / "catalogs/reviewed.json"
            catalog.parent.mkdir()
            catalog.write_text(json.dumps(catalog_fixture()))
            source = {**self.profile(), "weapon_lineage_catalog": {
                "file": "catalogs/reviewed.json", "sha256": hashlib.sha256(catalog.read_bytes()).hexdigest()}}
            profile_file = base / "profile.json"
            profile_file.write_text(json.dumps(source))
            loaded = profiles.load_profile(profile_file)
            self.assertEqual(loaded["sha256"], profiles.validate_profile(source)["sha256"])
            self.assertEqual(loaded["weapon_lineage_catalog_path"], str(catalog.resolve()))
            self.assertEqual(loaded["weapon_lineage"]["sha256"], source["weapon_lineage_catalog"]["sha256"])
            catalog.write_text(json.dumps(catalog_fixture()) + "\n")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                profiles.load_profile(profile_file)

    def test_catalog_parent_symlink_cannot_escape_profile_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            catalog = outside / "reviewed.json"
            catalog.write_text(json.dumps(catalog_fixture()))
            profile_root = base / "profiles"
            profile_root.mkdir()
            (profile_root / "catalogs").symlink_to(outside, target_is_directory=True)
            source = {**self.profile(), "weapon_lineage_catalog": {
                "file": "catalogs/reviewed.json", "sha256": hashlib.sha256(catalog.read_bytes()).hexdigest()}}
            profile_file = profile_root / "profile.json"
            profile_file.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, "symlinks"):
                profiles.load_profile(profile_file)


if __name__ == "__main__":
    unittest.main()
