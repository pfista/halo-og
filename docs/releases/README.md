# Release-notes authoring prompt

Use these instructions whenever the user asks to create a Halo OG release.
Keep the product description, direct platform download links, setup links,
complete commit list, compare link, checksums and provenance in their established
structure. Author the **Overview** for that release using the prompt below.

## Prompt

Review every change between the previous reachable published Halo OG release
and the selected release source. Read the full commit range, relevant diffs and
feature documentation; commit subjects are an index, not the overview. Confirm
that each highlight is implemented in this source and new since that baseline.
Include work from the current conversation only when it made it into the build.

Write a short paragraph of two to four sentences explaining what this release
adds or improves for players. Give it a clear theme without generic marketing
claims. Follow it with usually three to six concise highlight bullets, or fewer
when the release is small. Choose and order them by significance to players,
with major features first. Group related implementation commits into one useful
highlight; retain every commit separately in the generated full changelog.

Consider gameplay dynamics and optional rules, modes, maps added or updated,
controls, audio and rendering, bug fixes, stability, and network behavior or
compatibility. Include the categories that matter for this release without
forcing one bullet per category. Use the actual feature or map name and explain
the change and its practical effect. Mention defaults, where to enable a setting,
or compatibility requirements when players need that information.

For example, an optional Hardcore camo mode, an Overshield drain-sound fix and
control changes should be named directly when they are in the release range.
Do not bury them under recent test or build commits. CI, tests, documentation and
refactoring belong in the full commit list unless they directly change the
player experience. Avoid vague bullets such as "various improvements" or
"netcode updates." Describe the actual behavior and qualify testing limits;
build success alone does not prove cross-platform play or Xbox parity.

Recheck the paragraph and highlights against the final source and baseline.
Remove reverted, incomplete, previously released or unrelated changes. Never
reuse an old overview or automatically select the last few commits.

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
  "summary": "This update adds optional Hardcore camo and improves powerup audio and controller behavior. Hosts can choose harder-to-see camo, while fixes address unwanted Overshield hit sounds and controller input.",
  "highlights": [
    "Hardcore camo: hosts can remove the camouflage color tint in Edit Gametypes → Performance → Camo, making camouflaged players harder to spot. Normal remains the default.",
    "Overshield audio: passive drain on network clients no longer triggers the shield-hit sound when recognized as normal decay; actual damage retains its feedback.",
    "Controls: corrected controller bumper assignments and added a choice of Xbox look acceleration or no acceleration."
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
