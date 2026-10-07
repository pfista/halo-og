"""Synthetic metadata identity and portable diagnostic boundaries; no game data."""
import copy
import json
import unittest

from tools.map_pipeline import diagnostics, metadata


SOURCE_HASH = "a" * 64
CACHE_HASH = "b" * 64
PROFILE_HASH = "c" * 64
PREVIEW_HASH = "d" * 64


class AuthoredMetadataTests(unittest.TestCase):
    def setUp(self):
        self.editorial = {
            "schema_version": 1, "display_name": "A Test Map", "creator_username": "mapmaker",
            "contributors": ["lighting_artist"], "map_version": "1.2", "description": "A compact arena.\nBuilt for duels.",
            "recommended_players": {"min": 2, "max": 4}, "modes": ["slayer", "ctf"],
            "source_url": "https://example.test/maps/test-map", "preview": None,
            "field_provenance": {"recommended_players": {"origin": "author", "reference": "readme.txt"}},
        }
        self.source = {"version": 609, "sha256": SOURCE_HASH, "path": "/Users/private/input.map"}
        self.cache = {"version": 5, "build": "01.10.12.2276", "sha256": CACHE_HASH}
        self.profile = {"id": "reviewed-ce", "version": 1, "sha256": PROFILE_HASH}

    def test_unknown_factual_values_stay_null_and_no_spawn_inference(self):
        result = metadata.build_metadata("test_map", {**self.source, "spawn_count": 32}, self.cache, self.profile)
        self.assertEqual(result["display_name"], "test_map")
        for field in ("creator_username", "map_version", "description", "recommended_players", "source_url", "preview"):
            self.assertIsNone(result[field])
        self.assertEqual(result["contributors"], [])
        self.assertEqual(result["modes"], [])
        self.assertEqual(result["gameplay_validation"], "pending")
        self.assertEqual(result["source"], {"sha256": SOURCE_HASH, "cache_version": 609})
        self.assertEqual(result["conversion"]["profile_sha256"], PROFILE_HASH)
        self.assertNotIn("path", result["source"])

    def test_editorial_and_preview_changes_do_not_change_gameplay_identity(self):
        before = copy.deepcopy(self.editorial)
        first = metadata.build_metadata("test_map", self.source, self.cache, self.profile, self.editorial)
        modified = {**self.editorial, "description": "A corrected editorial description.", "creator_username": "actual_creator"}
        preview = {"file": "previews/test map.png", "sha256": PREVIEW_HASH, "origin": "generated_capture"}
        second = metadata.build_metadata("test_map", self.source, self.cache, self.profile, modified, preview)
        self.assertEqual(first["cache"], second["cache"])
        self.assertEqual(first["cache"]["sha256"], CACHE_HASH)
        self.assertEqual(first["source"], second["source"])
        self.assertEqual(first["conversion"], second["conversion"])
        self.assertEqual(second["preview"]["sha256"], PREVIEW_HASH)
        self.assertEqual(second["field_provenance"]["preview"]["origin"], "generated_capture")
        self.assertEqual(self.editorial, before)

    def test_preserve_authored_case_text_and_provenance_without_mutating_input(self):
        value = metadata.validate_metadata(self.editorial)
        self.assertEqual(value["description"], self.editorial["description"])
        self.assertEqual(value["map_version"], "1.2")
        value["field_provenance"]["recommended_players"]["origin"] = "modified"
        self.assertEqual(self.editorial["field_provenance"]["recommended_players"]["origin"], "author")

    def test_unknown_keys_and_bad_schema_are_rejected(self):
        for changed in ({"creator": "typo"}, {"schema_version": True}, {"schema_version": 2}, {"spawn_count": 16}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                metadata.validate_metadata({**self.editorial, **changed})
        with self.assertRaises(ValueError):
            metadata.validate_metadata({"schema_version": 1})

    def test_invalid_strings_modes_and_json_provenance_are_rejected(self):
        for field, value in (("display_name", " "), ("creator_username", "creator\x00"),
                             ("description", "x" * 2049), ("map_version", 1),
                             ("contributors", ["same", "same"]), ("modes", ["unsupported"]),
                             ("modes", ["slayer", "slayer"]),
                             ("field_provenance", {"unknown_field": "guess"}),
                             ("field_provenance", {"display_name": float("nan")}),
                             ("field_provenance", {"description": b"asset bytes"})):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                metadata.validate_metadata({**self.editorial, field: value})

    def test_player_recommendation_is_bounded_and_distinct_from_engine_limit(self):
        for players in ({"min": True, "max": 4}, {"min": 4, "max": 2}, {"min": 0, "max": 4},
                        {"min": 2, "max": 17}, {"min": 2.0, "max": 4}, {"min": 2, "max": 4, "spawns": 32}):
            with self.subTest(players=players), self.assertRaises(ValueError):
                metadata.validate_metadata({**self.editorial, "recommended_players": players})

    def test_preview_paths_hashes_and_origins_are_strict(self):
        preview = {"file": "preview.png", "sha256": PREVIEW_HASH, "origin": "author"}
        for changed in ({"file": "../preview.png"}, {"file": "/Users/private/preview.png"},
                        {"file": "C:\\private\\preview.png"}, {"file": "a//b.png"},
                        {"file": "./preview.png"}, {"file": "~/preview.png"},
                        {"file": " preview.png "}, {"sha256": "D" * 64}, {"origin": "unknown"},
                        {"origin": ["author"]}, {"extra": 1}):
            # Surrounding whitespace is canonicalized; it does not escape the
            # relative path root and is therefore accepted deliberately.
            if changed == {"file": " preview.png "}:
                self.assertEqual(metadata.validate_preview({**preview, **changed})["file"], "preview.png")
                continue
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                metadata.validate_preview({**preview, **changed})

    def test_source_urls_reject_credentials_local_paths_and_bad_ports(self):
        for url in ("file:///Users/private/input.map", "https://name:secret@example.test/map",
                    "https://example.test:bad/map", "https://example.test/white space", "https://"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                metadata.validate_metadata({**self.editorial, "source_url": url})

    def test_generated_sidecar_provenance_has_no_local_absolute_path(self):
        editorial = {**self.editorial, "field_provenance": {
            "description": {"reference": "/Users/private person/notes/readme.txt"}}}
        result = metadata.build_metadata("test_map", self.source, self.cache, self.profile, editorial)
        self.assertNotIn("private person", json.dumps(result))
        self.assertEqual(result["field_provenance"]["description"]["reference"], "<local-path>/readme.txt")

    def test_identity_fields_reject_bad_hash_version_and_map_ids(self):
        for source, cache, profile, map_id in (
            ({**self.source, "sha256": "unknown"}, self.cache, self.profile, "test_map"),
            (self.source, {**self.cache, "version": 7}, self.profile, "test_map"),
            (self.source, self.cache, {**self.profile, "version": True}, "test_map"),
            (self.source, self.cache, self.profile, "../map"),
        ):
            with self.subTest(map_id=map_id), self.assertRaises(ValueError):
                metadata.build_metadata(map_id, source, cache, profile)


class PortableDiagnosticTests(unittest.TestCase):
    def test_invader_context_missing_dependency_and_fields_are_attributed(self):
        output = (
            "ERROR: Weapon::magazine_index must be at least 0; value: -1\n"
            "...in weapons/test rifle/test rifle.weapon\n"
            "ERROR: Failed to find effects/missing.effect\n"
            "Failed to compile tag weapons/test rifle/test rifle.weapon\n"
        )
        result = diagnostics.parse_tool_output(output, "compile")
        self.assertEqual(result[0]["code"], "invalid_tag_field")
        self.assertEqual(result[0]["tag"], "weapons/test rifle/test rifle.weapon")
        self.assertEqual(result[0]["field"], "Weapon::magazine_index")
        self.assertEqual(result[0]["value"], "-1")
        self.assertEqual(result[1]["code"], "missing_tag")
        self.assertEqual(result[1]["tag"], "effects/missing.effect")
        self.assertEqual(result[2]["tag"], "weapons/test rifle/test rifle.weapon")
        self.assertNotIn("dependency_chain", result[1])

    def test_codec_hs_warning_and_unknown_cause_are_retained(self):
        result = diagnostics.parse_tool_output(
            "FATAL ERROR: Sound permutation #2 uses Ogg Vorbis which does not exist on the target engine.\n"
            "...in sound/weapon.sound\n"
            "script.hsc:3:4: error: unknown function 'mcc_only_function'\n"
            "WARNING (minor): Autoaim angles were changed due to building a stock scenario\n"
            "...in characters/player.biped\n"
            "ERROR: Operation did not succeed.\n", "compile")
        self.assertEqual([item["code"] for item in result], ["sound_codec", "unsupported_hs_function", "tool_warning", "tool_error"])
        self.assertEqual(result[2]["severity"], "warning")
        self.assertEqual(result[2]["tag"], "characters/player.biped")
        self.assertNotIn("tag", result[3])
        self.assertNotIn("field", result[3])
        self.assertNotIn("value", result[3])

    def test_paths_are_portable_in_messages_context_and_nested_keys(self):
        result = diagnostics.parse_tool_output(
            "\x1b[31mERROR: Failed to open '/Users/secret name/input/tags/weapons/test rifle.weapon'\x1b[0m\n"
            "...in /Users/secret name/input/tags/weapons/test rifle.weapon\n"
            "C:\\Users\\secret\\script.hsc:2:3: error: unknown function 'unsupported'\n", "compile")
        self.assertEqual(result[0]["tag"], "weapons/test rifle.weapon")
        text = json.dumps(result)
        self.assertNotIn("secret", text)
        self.assertNotIn("/Users", text)
        self.assertNotIn("\\x1b", text)
        record = {"id": "test_map", "diagnostics": result, "nested": {
            "/Users/secret/work/a.map": {"path": "C:\\Users\\secret\\b.map"},
            "message": "Source /home/private/map.map could not be read.",
            "source_url": "https://example.test/maps/map",
        }, "payload": "private encoded asset", "asset_bytes": b"private asset", "file_bytes": 4096}
        portable = diagnostics.shareable_report(record)
        text = json.dumps(portable)
        self.assertNotIn("secret", text)
        self.assertNotIn("private", text)
        self.assertNotIn("payload", portable)
        self.assertNotIn("asset_bytes", portable)
        self.assertEqual(portable["file_bytes"], 4096)
        self.assertEqual(portable["nested"]["source_url"], "https://example.test/maps/map")

    def test_wrapped_context_does_not_invent_or_carry_a_cause(self):
        result = diagnostics.parse_tool_output(
            "ERROR: Sound permutation #1 uses IMA ADPCM which does not exist on\n"
            "the target engine.\n"
            "...in sound/author.sound\n"
            "Successfully compiled another tag\n"
            "ERROR: Failed operation\n"
            "...in scenery/other.scenery\n", "compile")
        self.assertIn("the target engine.", result[0]["message"])
        self.assertEqual(result[0]["tag"], "sound/author.sound")
        self.assertEqual(result[1]["tag"], "scenery/other.scenery")
        self.assertNotIn("field", result[1])

    def test_riat_extensionless_dependencies_and_wrapped_codec_are_preserved(self):
        result = diagnostics.parse_tool_output(
            'script.hsc:2:3: error: can\'t find weapon tag "weapons/authored rifle"\n'
            'FATAL ERROR: Sound permutation #3 uses\n'
            'Ogg Vorbis which does not exist on the target engine.\n'
            '...in sound/authored.sound\n', "compile")
        self.assertEqual(result[0]["tag"], "weapons/authored rifle.weapon")
        self.assertEqual(result[0]["code"], "missing_tag")
        self.assertEqual(result[1]["code"], "sound_codec")
        self.assertNotIn("field", result[1])

    def test_shareable_preserves_source_policy_but_omits_script_asset_data(self):
        record = {"steps": [{"script_source": "tags"}, {"script_source": "(script startup private_script ...)"}],
                  "message": "Input file:///Users/secret/input.map is unavailable", "home": "~private/input.map",
                  "extra": float("nan")}
        result = diagnostics.shareable_report(record)
        self.assertEqual(result["steps"][0]["script_source"], "tags")
        self.assertNotIn("script_source", result["steps"][1])
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("private", json.dumps(result))
        json.dumps(result, allow_nan=False)

    def test_diagnostic_context_stays_explicit_and_report_sections_remain_distinct(self):
        entry = diagnostics.diagnostic("missing_tag", "resources", "Missing reviewed resource", tag="bitmaps/test.bitmap",
                                       dependency_chain=["levels/test.scenario", "bitmaps/test.bitmap"], suggested_fix="Supply matching resource cache.")
        report = {"id": "test_map", "status": "needs_profile", "source": {"version": 13, "sha256": SOURCE_HASH},
                  "diagnostics": [entry, diagnostics.diagnostic("warning", "scripts", "Authored script removed by reviewed profile", severity="warning")],
                  "repairs": [{"tag": "hud/test.weapon_hud_interface", "reason": "Reviewed scale correction"}],
                  "omissions": [{"tag": "levels/test.scenario", "reason": "Optional training clock"}]}
        rendered = diagnostics.render_report(report)
        for text in ("## Blockers", "## Warnings", "## Repairs", "## Omissions", "Gameplay validation: **pending**", "Optional training clock", "dependency_chain:"):
            self.assertIn(text, rendered)
        self.assertIn("Compilation and static checks do not establish gameplay acceptance.", rendered)


if __name__ == "__main__":
    unittest.main()
