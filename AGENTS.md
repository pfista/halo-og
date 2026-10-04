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
- Keep original fonts, artwork, HUD, scoreboard, sounds and game rules. Rebranding,
  overhead labels, balance changes and other modifications require explicit scope.
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
- [Map publishing](docs/map-publishing.md): complete community maps on Cloudflare.

## GitHub releases

Keep release notes simple: a short description followed by direct download
links for every included platform. Link to the playtesting guide for setup;
keep platform requirements and any signing limitations brief. Publish matching
platform builds from one source commit and include checksums and provenance.
