"""Read-only GitHub fixtures cover complete, immutable release changelogs."""

import copy
import re
import unittest

from tools import release_changelog as changelog


def sha(number):
    return f"{number:040x}"


LEGACY = "test-v0.3.0-net11-setup2"


def published(tag, *, draft=False, date="2026-10-04T12:00:00Z"):
    return {"tag_name": tag, "draft": draft, "published_at": date}


def commit(number, subject=None):
    return {"sha": sha(number), "commit": {"message": subject or f"Change {number}"}}


class HistoryAPI:
    def __init__(self, count=2):
        self.head = sha(count + 1)
        self.releases = [published(LEGACY)]
        self.refs = {LEGACY: {"sha": sha(1), "type": "commit"}}
        self.annotations, self.comparisons, self.overrides, self.calls = {}, {}, {}, []
        self.compare(sha(1), [commit(number) for number in range(2, count + 2)])

    def compare(self, baseline, commits, *, status="ahead", behind=0):
        self.comparisons[baseline] = {"base_commit": {"sha": baseline},
            "merge_base_commit": {"sha": baseline}, "status": status,
            "ahead_by": len(commits), "behind_by": behind,
            "total_commits": len(commits), "commits": commits}

    def add(self, tag, baseline, commits, *, status="ahead", behind=0, date=None):
        self.releases.append(published(tag, date=date or "2026-10-04T12:00:00Z"))
        self.refs[tag] = {"sha": baseline, "type": "commit"}
        self.compare(baseline, commits, status=status, behind=behind)

    def get(self, path, *, missing_ok=False):
        self.calls.append(path)
        if match := re.fullmatch(r"releases\?per_page=100&page=(\d+)", path):
            start = (int(match[1]) - 1) * 100
            return copy.deepcopy(self.releases[start:start + 100])
        if path.startswith("git/ref/tags/"):
            value = self.refs.get(path.removeprefix("git/ref/tags/"))
            return {"object": copy.deepcopy(value)} if value else None
        if path.startswith("git/tags/"):
            return copy.deepcopy(self.annotations[path.removeprefix("git/tags/")])
        if match := re.fullmatch(r"compare/([0-9a-f]{40})\.\.\.([0-9a-f]{40})\?per_page=100&page=(\d+)", path):
            baseline, head, page = match[1], match[2], int(match[3])
            if head != self.head:
                raise AssertionError("Comparison must use the immutable selected head")
            result = copy.deepcopy(self.comparisons[baseline])
            start = (page - 1) * 100
            if isinstance(result["commits"], list):
                result["commits"] = result["commits"][start:start + 100]
            result.update(copy.deepcopy(self.overrides.get((baseline, page), {})))
            return result
        raise AssertionError("Unexpected GitHub read: " + path)


class ReleaseChangelogTests(unittest.TestCase):
    def generate(self, api, tag="v0.3.0"):
        return changelog.generate_changelog(api, changelog.REPOSITORY, api.head, tag)

    def test_strict_numeric_semantic_tags(self):
        self.assertEqual(changelog.version_tuple("v0.3.0"), (0, 3, 0))
        self.assertGreater(changelog.version_tuple("v0.10.0"), changelog.version_tuple("v0.9.9"))
        for tag in ("0.3.0", "v0.3", "v0.3.0-next", "v0.3.0+build", "v00.3.0", "v0.03.0",
                    "v0.3.00", "v-1.3.0", "v0.3.0 ", "v0.3.0\n", "v" + "1" * 79 + ".0.0", None):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                changelog.version_tuple(tag)

    def test_legacy_same_version_allows_initial_semantic_release(self):
        api = HistoryAPI()
        result = self.generate(api)
        self.assertEqual(result, {"previous_tag": LEGACY, "previous_sha": sha(1),
                                 "commits": [{"sha": sha(2), "subject": "Change 2"},
                                             {"sha": api.head, "subject": "Change 3"}]})

    def test_closest_ancestor_beats_publication_date_and_api_order(self):
        api = HistoryAPI(count=4)
        api.releases[0]["published_at"] = "2026-10-10T12:00:00Z"
        api.add("test-v0.3.0-net11-closer", sha(4), [commit(5)], date="2026-10-02T12:00:00Z")
        expected = self.generate(api)
        self.assertEqual(expected["previous_sha"], sha(4))
        self.assertEqual(expected["commits"], [{"sha": sha(5), "subject": "Change 5"}])
        api.releases.reverse()
        self.assertEqual(self.generate(api), expected)

    def test_releases_and_comparisons_paginate_past_250_commits(self):
        api = HistoryAPI(count=301)
        api.releases = [published(f"build-{number}") for number in range(105)] + api.releases
        result = self.generate(api)
        self.assertEqual(len(result["commits"]), 301)
        self.assertEqual([item["sha"] for item in result["commits"]], [sha(n) for n in range(2, 303)])
        self.assertIn("releases?per_page=100&page=2", api.calls)
        for page in range(1, 5):
            self.assertIn(f"compare/{sha(1)}...{api.head}?per_page=100&page={page}", api.calls)

    def test_annotated_and_nested_tags_peel_to_previous_commit(self):
        api = HistoryAPI()
        first, second = sha(100), sha(101)
        api.refs[LEGACY] = {"sha": first, "type": "tag"}
        api.annotations[first] = {"sha": first, "object": {"sha": second, "type": "tag"}}
        api.annotations[second] = {"sha": second, "object": {"sha": sha(1), "type": "commit"}}
        self.assertEqual(self.generate(api)["previous_sha"], sha(1))
        self.assertIn("git/tags/" + first, api.calls)
        self.assertIn("git/tags/" + second, api.calls)
        api.annotations[second]["object"] = {"sha": first, "type": "tag"}
        with self.assertRaisesRegex(RuntimeError, "does not resolve"):
            self.generate(api)

    def test_ignores_tool_upstream_draft_unpublished_and_noncanonical_tags(self):
        api = HistoryAPI()
        ignored = ["build-78", "launcher-v1.8", "content-tools-v1", "test-other", "v1.0.0-rc1",
                   "v01.0.0", "test-v0.3.0-../bad", "test-v0.3.0-dot."]
        api.releases += [published(tag) for tag in ignored]
        api.releases += [published("v9.0.0", draft=True), published("v8.0.0", date=None)]
        self.assertEqual(self.generate(api)["previous_tag"], LEGACY)
        self.assertEqual([path for path in api.calls if path.startswith("git/ref/tags/")],
                         ["git/ref/tags/" + LEGACY])

    def test_new_version_exceeds_every_published_semantic_version(self):
        api = HistoryAPI()
        api.add("v0.10.0", sha(2), [commit(3)])
        for tag in ("v0.3.0", "v0.9.9", "v0.10.0"):
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError, "must exceed"):
                self.generate(api, tag)
        self.assertEqual(self.generate(api, "v0.10.1")["previous_tag"], "v0.10.0")

    def test_semantic_name_preferred_for_same_ancestor_source(self):
        api = HistoryAPI()
        api.releases += [published("v0.3.0")]
        api.refs["v0.3.0"] = api.refs[LEGACY]
        self.assertEqual(self.generate(api, "v0.3.1")["previous_tag"], "v0.3.0")
        self.assertEqual(len([path for path in api.calls if path.startswith("compare/")]), 1)

    def test_divergent_legacy_skipped_but_highest_semantic_is_required_ancestor(self):
        api = HistoryAPI()
        api.add("test-v0.3.0-diverged", sha(99), [commit(3)], status="diverged", behind=1)
        self.assertEqual(self.generate(api)["previous_tag"], LEGACY)
        api.add("v0.3.0", sha(98), [commit(3)], status="diverged", behind=1)
        with self.assertRaisesRegex(RuntimeError, "highest semantic release"):
            self.generate(api, "v0.3.1")
        api.add("v0.3.1", sha(2), [commit(3)])
        self.assertEqual(self.generate(api, "v0.3.2")["previous_tag"], "v0.3.1")

    def test_missing_baseline_and_zero_change_range_refused(self):
        api = HistoryAPI()
        api.releases = []
        with self.assertRaisesRegex(RuntimeError, "baseline is required"):
            self.generate(api)
        api = HistoryAPI()
        api.refs[LEGACY] = {"sha": api.head, "type": "commit"}
        api.compare(api.head, [], status="identical")
        with self.assertRaisesRegex(RuntimeError, "no commits"):
            self.generate(api)
        api = HistoryAPI()
        api.comparisons[sha(1)].update(status="diverged", behind_by=1)
        with self.assertRaisesRegex(RuntimeError, "baseline is required"):
            self.generate(api)

    def test_missing_ref_invalid_target_or_annotation_never_silently_skipped(self):
        for target in (None, {"type": "tree", "sha": sha(1)}, {"type": "commit", "sha": "short"}):
            api = HistoryAPI()
            api.refs[LEGACY] = target
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self.generate(api)

    def test_duplicate_incomplete_wrong_source_and_changed_comparison_refused(self):
        api = HistoryAPI(count=101)
        api.comparisons[sha(1)]["commits"][-1] = commit(2)
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            self.generate(api)
        api = HistoryAPI()
        api.comparisons[sha(1)]["commits"].pop()
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            self.generate(api)
        api = HistoryAPI()
        api.comparisons[sha(1)]["commits"][-1] = commit(99)
        with self.assertRaisesRegex(RuntimeError, "omits the selected source"):
            self.generate(api)
        api = HistoryAPI(count=101)
        api.overrides[(sha(1), 2)] = {"total_commits": 102}
        with self.assertRaisesRegex(RuntimeError, "changed during pagination"):
            self.generate(api)
        api = HistoryAPI()
        api.comparisons[sha(1)]["base_commit"] = {"sha": sha(99)}
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.generate(api)

    def test_all_commits_include_merges_and_normalize_only_the_subject(self):
        api = HistoryAPI(count=3)
        api.comparisons[sha(1)]["commits"] = [commit(2, "  Add\tmap support\x00\nDetails\n"),
            commit(3, "Merge branch 'maps'\nMerge details"), commit(4, "Keep settings")]
        result = self.generate(api)
        self.assertEqual([item["subject"] for item in result["commits"]],
                         ["Add map support", "Merge branch 'maps'", "Keep settings"])

    def test_malformed_api_objects_and_counts_raise_clear_errors(self):
        for field, value in (("base_commit", None), ("merge_base_commit", []),
                             ("ahead_by", True), ("total_commits", -1), ("commits", None)):
            api = HistoryAPI()
            api.comparisons[sha(1)][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.generate(api)
        api = HistoryAPI()
        api.comparisons[sha(1)]["commits"][0]["commit"] = None
        with self.assertRaisesRegex(RuntimeError, "no subject"):
            self.generate(api)
        api = HistoryAPI()
        api.releases.append(published(LEGACY))
        with self.assertRaisesRegex(RuntimeError, "Duplicate published"):
            self.generate(api)

    def test_formatter_has_complete_commits_latest_unique_nonmerge_changes_and_safe_text(self):
        subjects = ["Old change", "Same change", "Same change", "Fix <xml> [link] `code` & text",
                    "Change four", "Change five", "Merge branch 'main'", "Change six"]
        result = {"previous_tag": LEGACY, "previous_sha": sha(1),
                  "commits": [{"sha": sha(number), "subject": subject}
                              for number, subject in enumerate(subjects, 2)]}
        record = {"repository": changelog.REPOSITORY, "sha": sha(9), "tag": "v0.3.0", "changelog": result}
        plain = changelog.format_changelog(record)
        markdown = changelog.format_changelog(record, markdown=True)
        for output in (plain, markdown):
            self.assertIn("All commits since " + LEGACY, output)
            self.assertIn(f"https://github.com/{changelog.REPOSITORY}/compare/{sha(1)}...{sha(9)}", output)
            for item in result["commits"]:
                self.assertIn(item["sha"][:12], output)
            key_changes = output.split("All commits since", 1)[0]
            self.assertNotIn("Old change", key_changes)
            self.assertNotIn("Merge branch", key_changes)
            self.assertEqual(key_changes.count("Same change"), 1)
        self.assertIn(r"Fix \<xml\> \[link\] \`code\` \& text", markdown)
        self.assertNotIn("<xml>", markdown)
        result["commits"][0]["subject"] = f"See [source](https://github.com/pfista/halo-og/commit/{sha(2)})"
        for markdown_mode in (False, True):
            output = changelog.format_changelog(record, markdown=markdown_mode)
            self.assertNotIn("https://github.com/pfista/halo-og/commit/", output)
            self.assertNotIn("/commit/", output.split("Full comparison", 1)[-1])


if __name__ == "__main__":
    unittest.main()
