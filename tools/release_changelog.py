"""Read complete Halo OG release history and render an immutable changelog.

Only GitHub read APIs are used. Publication, local Git refs and downloaded build
assets belong to the caller. Existing clients require one unique source-commit
URL in release notes, so changelog entries deliberately use plain commit hashes.
"""

import re
import string
from urllib.parse import quote


REPOSITORY = "pfista/halo-og"
PAGE_SIZE = 100
MAX_PAGES = 1000
SEMANTIC_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
LEGACY_TAG = re.compile(r"test-v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9._-]*)?")
SHA = re.compile(r"[0-9a-f]{40}")


def version_tuple(tag):
    """Require the public vMAJOR.MINOR.PATCH spelling, with no suffixes."""
    match = SEMANTIC_TAG.fullmatch(tag) if isinstance(tag, str) and len(tag) <= 80 else None
    if not match:
        raise RuntimeError("Use vMAJOR.MINOR.PATCH without leading zeros or suffixes (at most 80 characters)")
    return tuple(int(part) for part in match.groups())


def _sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise RuntimeError("Release history requires full lowercase commit SHAs")
    return value


def _published_releases(api):
    releases, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        batch = api.get(f"releases?per_page={PAGE_SIZE}&page={page}")
        if not isinstance(batch, list) or len(batch) > PAGE_SIZE:
            raise RuntimeError("Invalid GitHub release-history page")
        for release in batch:
            if not isinstance(release, dict):
                raise RuntimeError("Invalid GitHub release-history record")
            tag = release.get("tag_name")
            stamp = release.get("published_at")
            if (release.get("draft") is not False or not isinstance(stamp, str)
                    or not stamp or not isinstance(tag, str)):
                continue
            try:
                version = version_tuple(tag)
            except RuntimeError:
                if (len(tag) > 80 or not LEGACY_TAG.fullmatch(tag)
                        or ".." in tag or tag.endswith(".")):
                    continue
                version = None
            if tag in seen:
                raise RuntimeError("Duplicate published release in paginated history: " + tag)
            seen.add(tag)
            releases.append((tag, version))
        if len(batch) < PAGE_SIZE:
            return releases
    raise RuntimeError("Release history exceeded the pagination limit; no incomplete changelog was generated")


def _tag_commit(api, tag):
    reference = api.get("git/ref/tags/" + quote(tag, safe=""), missing_ok=True)
    if not isinstance(reference, dict) or not isinstance(reference.get("object"), dict):
        raise RuntimeError("Published release has no resolvable Git tag: " + tag)
    target, seen = reference["object"], set()
    for _ in range(16):
        object_sha = _sha(target.get("sha"))
        if target.get("type") == "commit":
            return object_sha
        if target.get("type") != "tag" or object_sha in seen:
            raise RuntimeError("Release tag does not resolve to a commit: " + tag)
        seen.add(object_sha)
        annotation = api.get("git/tags/" + object_sha)
        if (not isinstance(annotation, dict) or annotation.get("sha") != object_sha
                or not isinstance(annotation.get("object"), dict)):
            raise RuntimeError("Invalid annotated release tag: " + tag)
        target = annotation["object"]
    raise RuntimeError("Release tag annotation nesting exceeded the limit: " + tag)


def _comparison(api, previous_sha, sha, page):
    result = api.get(f"compare/{previous_sha}...{sha}?per_page={PAGE_SIZE}&page={page}")
    base = result.get("base_commit") if isinstance(result, dict) else None
    if not isinstance(base, dict) or base.get("sha") != previous_sha:
        raise RuntimeError("Comparison does not match the selected previous release")
    counts = [result.get(key) for key in ("ahead_by", "behind_by", "total_commits")]
    if any(type(count) is not int or count < 0 for count in counts):
        raise RuntimeError("Invalid release comparison counts")
    if result.get("status") not in {"ahead", "identical", "behind", "diverged"}:
        raise RuntimeError("Invalid release comparison status")
    if not isinstance(result.get("commits"), list) or len(result["commits"]) > PAGE_SIZE:
        raise RuntimeError("Invalid release comparison commit page")
    return result


def _ancestor(result, previous_sha):
    if result["status"] not in {"ahead", "identical"}:
        return False
    merge_base = result.get("merge_base_commit")
    if (result["behind_by"] != 0 or result["total_commits"] != result["ahead_by"]
            or not isinstance(merge_base, dict) or merge_base.get("sha") != previous_sha
            or (result["status"] == "identical") != (result["ahead_by"] == 0)):
        raise RuntimeError("Inconsistent previous-release ancestry comparison")
    return True


def _subject(commit):
    detail = commit.get("commit")
    message = detail.get("message") if isinstance(detail, dict) else None
    if not isinstance(message, str):
        raise RuntimeError("Release comparison commit has no subject")
    first_line = message.splitlines()[0] if message else ""
    return " ".join("".join(character if character.isprintable() else " "
                            for character in first_line).split()) or "(no subject)"


def _commits(api, previous_sha, sha, first):
    total = first["total_commits"]
    commits, seen, page, result = [], set(), 1, first
    while True:
        if (result["status"], result["ahead_by"], result["behind_by"], result["total_commits"]) != (
                first["status"], first["ahead_by"], first["behind_by"], total):
            raise RuntimeError("Release comparison changed during pagination")
        if not _ancestor(result, previous_sha):
            raise RuntimeError("Previous release is not an ancestor of the selected source")
        for commit in result["commits"]:
            if not isinstance(commit, dict):
                raise RuntimeError("Invalid release comparison commit")
            commit_sha = _sha(commit.get("sha"))
            if commit_sha in seen or commit_sha == previous_sha:
                raise RuntimeError("Duplicate or previous-baseline commit in release comparison")
            seen.add(commit_sha)
            commits.append({"sha": commit_sha, "subject": _subject(commit)})
        if len(commits) > total:
            raise RuntimeError("Release comparison returned more commits than its total")
        if len(commits) == total:
            if sha not in seen:
                raise RuntimeError("Complete release comparison omits the selected source commit")
            return commits  # Keep GitHub's chronological ordering, including merges.
        if len(result["commits"]) != PAGE_SIZE:
            raise RuntimeError("Incomplete release comparison; no commits were silently omitted")
        page += 1
        if page > MAX_PAGES:
            raise RuntimeError("Release comparison exceeded the pagination limit")
        result = _comparison(api, previous_sha, sha, page)


def generate_changelog(api, repository, sha, tag):
    """Find the closest released ancestor and return every commit since it."""
    if repository != REPOSITORY:
        raise RuntimeError("Release changelogs are limited to " + REPOSITORY)
    _sha(sha)
    version = version_tuple(tag)
    releases = _published_releases(api)
    semantic = [(name, prior) for name, prior in releases if prior is not None]
    if semantic and version <= max(prior for _, prior in semantic):
        raise RuntimeError("The new version must exceed every published semantic release")
    highest = max(semantic, key=lambda item: item[1])[0] if semantic else None
    candidates, comparisons = [], {}
    for name, prior_version in releases:
        previous_sha = _tag_commit(api, name)
        if previous_sha not in comparisons:
            comparisons[previous_sha] = _comparison(api, previous_sha, sha, 1)
        result = comparisons[previous_sha]
        reachable = _ancestor(result, previous_sha)
        if name == highest and not reachable:
            raise RuntimeError("The highest semantic release is not an ancestor of the selected source")
        if reachable:
            # Prefer a semantic name when several releases label the same source.
            rank = (result["ahead_by"], prior_version is None,
                    tuple(-part for part in prior_version) if prior_version else (0, 0, 0), name)
            candidates.append((rank, name, previous_sha, result))
    if not candidates:
        raise RuntimeError("No published Halo OG release is an ancestor; a previous release baseline is required")
    _, previous_tag, previous_sha, first = min(candidates, key=lambda item: item[0])
    if not first["ahead_by"]:
        raise RuntimeError("The selected source has no commits since its previous release")
    return {"previous_tag": previous_tag, "previous_sha": previous_sha,
            "commits": _commits(api, previous_sha, sha, first)}


def _display_subject(subject, markdown):
    # An arbitrary commit subject must never become another build-source claim
    # or a hyperlink/HTML fragment in generated release notes.
    subject = re.sub(r"(?i)\b(https?)://", r"\1: //", subject)
    if markdown:
        return "".join("\\" + character if character in string.punctuation else character
                       for character in subject)
    return subject


def format_changelog(record, markdown=False):
    """Render the same key changes and complete commit list for notes and tags."""
    changelog = record["changelog"]
    commits = changelog["commits"]
    prefix = "### " if markdown else ""
    lines = [prefix + "Key changes", ""]
    changes, seen = [], set()
    for commit in reversed(commits):
        subject = commit["subject"]
        if not subject.startswith("Merge ") and subject not in seen:
            changes.append(subject)
            seen.add(subject)
            if len(changes) == 5:
                break
    lines.extend("- " + _display_subject(subject, markdown) for subject in reversed(changes))
    if not changes:
        lines.append("- See the complete commit list below.")
    lines += ["", prefix + "All commits since " + changelog["previous_tag"], ""]
    lines.extend(f"- {commit['sha'][:12]} {_display_subject(commit['subject'], markdown)}" for commit in commits)
    compare = (f"https://github.com/{record['repository']}/compare/"
               f"{changelog['previous_sha']}...{record['sha']}")
    lines += ["", f"[Full comparison]({compare})" if markdown else "Full comparison: " + compare, ""]
    return "\n".join(lines)
