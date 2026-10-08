# Release-notes authoring prompt

Use these instructions whenever the user asks to create a Halo OG release.
Keep the product description, direct platform download links, setup links,
complete commit list, compare link, checksums and provenance in their established
structure. Author the **Overview** for that release using the prompt below.

## GitHub release prompt

Review every change between the previous reachable published Halo OG release
and the selected release source. Read the full commit range, relevant diffs and
feature documentation; commit subjects are an index, not the overview. Confirm
that each highlight is implemented in this source and new since that baseline.
Include work from the current conversation only when it made it into the build.

Write a short paragraph of two to four sentences explaining what this release
adds or improves for players. Give it a clear theme without generic marketing
claims. Follow it with usually three to six concise highlight bullets, or fewer
when the release is small. Choose and order them by significance to players,
with major features first. Start each highlight with a short, recognizable
category or feature name, followed by the concrete change and what it means
for players. Group related implementation commits into one useful highlight;
retain every commit separately in the generated full changelog.

Consider gameplay dynamics and optional rules, modes, maps added or updated,
controls, audio and rendering, bug fixes, stability, and network behavior or
compatibility. Include the categories that matter for this release without
forcing one bullet per category. Use the actual feature or map name and explain
the change and its practical effect. Mention defaults, where to enable a setting,
or compatibility requirements when players need that information.

For example, name a new mode, an Overshield sound fix or a split-screen fix
directly when it is in the release range. Explain what players can choose,
hear or see before describing how it works. Do not bury those changes under
recent test or build commits. CI, tests, documentation and
refactoring belong in the full commit list unless they directly change the
player experience. Avoid vague bullets such as "various improvements" or
"netcode updates." Describe the actual behavior and qualify testing limits;
build success alone does not prove cross-platform play or Xbox parity.

Recheck the paragraph and highlights against the final source and baseline.
Remove reverted, incomplete, previously released or unrelated changes. Never
reuse an old overview or automatically select the last few commits.

## Community announcement prompt (Discord and Whop)

Use this prompt for Guilty's Discord announcements and for release copy prepared
for Whop. The bot currently delivers to Discord; this guide also defines the
style for Whop copy without requiring a separate publishing integration.

Read the live published GitHub release notes and write a short, player-facing
announcement. Choose usually three to six significant highlights, or fewer
for a small release, with major features first. Use bullets in this format:
`- **Category or feature:** What changed and what players can now do, hear or
see.` Group related fixes, as in **Input and camera**, **Split-screen**,
**Menus**, **Timer audio** or **Community maps**, without forcing categories
that do not fit this release. A short opening sentence in Guilty's helpful
voice is optional; keep the highlights easy to scan.

Lead with visible behavior rather than implementation terms. For example,
describe a cache fix as updated maps loading correctly after their files
change, rather than explaining content hashes. Describe the practical effect
of a memory limit or conversion change only when the notes establish it; do
not turn technical work into an unsupported promise. Keep hashes, commit
subjects, internal APIs, conversion machinery, CI and testing detail in the
GitHub changelog unless players need a specific compatibility requirement.

Use exact feature and setting names. Include meaningful defaults, opt-in
behavior and where to find an option when the published notes provide them.
Distinguish settings such as **Just Me** (the acting player hears the sound)
and **Silent** (nobody hears it); do not call both silent. Use only changes
and effects supported by the published release notes. Do not copy the example
below as a fixed list of features or infer that code on main is available.
Preserve testing-release status and any material limits from the notes.

Keep the announcement within its destination's message budget. Guilty's
Discord application adds the version, testing-release status and release link;
its generated summary should omit a duplicate title, URLs and mentions. Whop
copy should use the same player-facing highlights and link to the published
release using that destination's established format. Authoring copy does not
authorize sending, publishing or changing a destination.

## Source file

Before committing and building the release source, write
`docs/releases/<tag>.json`, where `<tag>` is the exact new `vMAJOR.MINOR.PATCH`
tag. It has exactly two fields:

- `summary`: one non-empty paragraph of plain text, without line breaks.
- `highlights`: one to six distinct non-empty strings of plain text, one per
  bullet, without line breaks.

Use normal prose and punctuation; the generator handles Markdown escaping and
bullet formatting. Keep links in the existing download, setup and compare
sections. Do not add Markdown formatting or headings to these strings.

This example illustrates the requested style using current development topics.
It is not a release manifest: verify the actual range and behavior before using
any of its wording in a versioned file.

```json
{
  "summary": "This update adds a competitive mode and more control over player sounds, with fixes for aiming, split-screen and powerup announcements. Hosts can choose the Pro preset while players keep useful feedback from their own actions.",
  "highlights": [
    "Team Slayer Pro: a new locked gametype with the Pro preset for timers, precision weapon spread and stronger camo. Original built-in gametypes are hidden by default, with a setting to show them.",
    "Player sounds: movement and weapon sounds offer Normal, Just Me and Silent. The Pro preset uses Just Me so players hear their own actions without other players hearing them.",
    "Input and camera: menus block gameplay controls, camera shake stays visible between frames, and aiming stays within firing limits.",
    "Split-screen: teammate panes stay stable through deaths and respawns, and menus and scoreboards overlay correctly.",
    "Timer audio: upcoming rocket, camo and Overshield announcements play before the countdown.",
    "Community maps: updated maps load correctly after their source files change."
  ]
}
```

Preparation loads the versioned file from the selected source SHA, stores it in
the candidate's provenance and renders it in both the annotated tag and GitHub
notes. Missing or invalid content stops preparation. Verification compares it
with the same source file before publication. The full commit history is still
generated independently and must fit, together with the overview and other
notes, within the existing 16 KiB client limit.

Authoring this file does not publish a release. Follow the explicit release
authorization and version rules in [AGENTS.md](../../AGENTS.md) and the
[publication guide](../macos-menu-and-releases.md).
