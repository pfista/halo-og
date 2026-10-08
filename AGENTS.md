# Halo OG contributor and agent rules

Halo OG (`pfista/halo-og`) preserves original Xbox Halo: Combat Evolved NTSC
rules, presentation and LAN feel across native platforms. Community maps are
content imports; competitive features are optional and default off.

## Fidelity and upstream changes

- Preserve the 30 Hz simulation. Assess high-refresh rendering, interpolation
  and camera/input latency separately; a 30 FPS reference preset does not impose
  a normal-play cap.
- Review useful cybersecurity upstream changes individually. Inspect actual
  diffs, defaults and dependencies; split mixed commits and never merge wholesale.
- Prioritize matching accuracy, correctness, stability, performance and platform
  fixes that preserve Xbox behavior. Review netcode timing, authority, fairness,
  compatibility and service dependencies before adoption.
- Use original Xbox behavior, including its quirks, as the acceptance criterion.
  A baseline fidelity correction needs evidence that the port differs from the
  original; passing regression tests alone does not establish that evidence.
- Intentional departures from original behavior should generally be explicit
  configuration options that default to the original behavior. Keep uncertain
  netcode changes selectable while comparing their timing and feel with OG.
- Maintain interoperability with cybersecurity games as a goal. Keep Halo OG's
  original presentation and local feel while respecting shared host-authoritative
  rules. A shared protocol number alone does not establish gameplay compatibility.
- Reference upstream discovery, invite and connection protocols independently of
  its PC-style menus. Check in with the user before implementing game-discovery
  UI, then map it to original Xbox-style Multiplayer/System Link menus rather
  than importing upstream UI. OS-native settings windows are not the intended
  game-discovery UI.
- Keep original fonts, artwork, HUD, scoreboard, sounds and game rules. Rebranding,
  overhead labels, balance changes and other modifications require explicit scope.
- Identify community additions and compatibility changes in code comments and
  asset provenance. Distinguish stock Xbox content, imported authored content and
  conversion changes so later weapon sets can select them deliberately.
- Move repeatable map conversion steps into development tools with documented,
  reviewed profiles. Preserve source assets and record changes and validation;
  do not apply one map's HUD sizing or script policy blindly to another map.
- Keep the reviewed-through revision separate from the integrated baseline.
  Record commit hashes, decisions, reasons, validation and integration status in
  [the fidelity policy](docs/xbox-fidelity.md). Run checks appropriate to the change.
- A successful build or smoke test does not prove retail parity. Native ARM/x86
  binaries are not byte-identical Xbox executables.

## Local Mac installation

After a successful local Mac app build, the default is to install with
`--install` into `/Applications/Halo OG.app`, unless the user's current
instructions say otherwise. Preserve the previous app, game data, saves and
settings; verify the installed signature and `Contents/Resources/BuildInfo.txt`.

## Documentation entry points

- [Playtesting](docs/playtesting.md): installation, joining and reporting problems.
- [Building](docs/building.md): platform toolchains and validation.
- [Fidelity policy](docs/xbox-fidelity.md): baseline, defaults and upstream decisions.
- [Community maps](docs/community-maps.md): conversion and managed storage.
- [Community conversion](docs/community-map-conversion.md): authoring tools,
  stock/community provenance and repeatable map-specific conversion profiles.
- [Map publishing](docs/map-publishing.md): complete community maps on Cloudflare.

## Commits and changelog

- Commit each independently reviewable bug fix or feature separately. Include
  its supporting tests and documentation; keep unrelated pending work out of
  the commit. Shared setup may accompany the first feature that needs it.
- Use Conventional Commit subjects: `fix:` for bug fixes, `feat:` for new
  features, and `docs:`, `test:`, `refactor:`, `build:`, `ci:` or `chore:` for
  those changes. An optional scope is welcome, such as `fix(input): ...`.
- Describe the concrete behavior in the subject. Release changelogs use commit
  subjects directly, so each must make sense to readers without the chat or
  diff. Avoid vague subjects or bundling several fixes into one entry.
- Preserve published history unless the user explicitly authorizes rewriting
  it. Commit requests do not authorize pushes, tags or releases.

## GitHub releases

Keep the established release structure: a short product description, direct
download links for every included platform, an **Overview** with a short prose
paragraph and player-facing highlight bullets, then the complete commit list.
Link to the playtesting guide for setup; keep platform requirements and signing
limitations brief. Publish matching platform builds from one source commit and
include checksums and provenance.

- Follow [the release-notes authoring prompt](docs/releases/README.md) whenever
  the user asks for a release. Review the entire range since the previous
  reachable release, including relevant diffs and feature documentation. Choose
  highlights by player impact, not commit recency or the number of commits.
- Explain the release's main changes in two to four short sentences, followed
  by usually three to six concise bullets (fewer for a small release). Cover the
  significant gameplay rules, modes, maps, controls, bug fixes, rendering/audio
  and network changes actually included. State optional settings and defaults
  when they affect how players use a feature. Do not pad the overview with CI,
  test, documentation or refactoring work unless it has a direct player benefit.
- Follow the community announcement prompt in the same guide for Discord and
  Whop copy. Use concise player-facing bullets with bold category or feature
  labels, usually three to six highlights (fewer for a small release), ordered
  by player impact. Explain what players can do, hear or see; leave implementation
  details in GitHub. Ground announcements in the live published release notes
  and preserve testing-release status. Preparing copy does not authorize posting.
- Author `docs/releases/<tag>.json` with `summary` and `highlights` before
  committing and building the release source. The generator reads that file
  from the exact build SHA and uses the same overview in the annotated tag and
  GitHub notes. Do not substitute the latest few commit subjects, copy a stale
  overview, or describe unfinished work as shipped. Recheck it against the final
  source and release range before publication.

- Commit and push requests do not authorize tags or releases. Require the user's
  explicit instruction for the specified source commit before creating or
  pushing a tag, dispatching a release workflow, or publishing any GitHub release
  (including a prerelease). Branch pushes may build, test and upload CI artifacts.
- New release tags must be `vMAJOR.MINOR.PATCH`, with no suffix, and the title
  must be `Halo OG vMAJOR.MINOR.PATCH` (for example, `v0.3.1` and `Halo OG v0.3.1`).
  Testing releases still use GitHub's prerelease flag. Publication workflows are
  manual-only and may be dispatched only after that user authorization.
- The tag's version must match `HALO_OG_VERSION` in
  `port/linux/include/halo_og_version.h`. Bump and commit that header before
  building the matching platform artifacts. Never rewrite existing tags or
  replace their published assets.
- Both the annotated tag message and GitHub release notes must include concise
  commit subjects with short SHAs since the previous reachable Halo OG release
  tag, plus a compare link. Keep the overview and full commit list in the release
  notes after the description and platform download links.
- Preserve the established platform asset filenames and direct download links.
  Older `test-...` tags remain historical releases; do not rename them.
