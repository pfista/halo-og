# Global Fiesta arsenal caches

The Xbox engine loads one map's tag arena. A weapon in another cache cannot be
spawned using that cache's datum. `tools/build_fiesta_arsenal.py` builds a hidden
derivative for each normally selectable map. Fiesta Uncut and All use the
derivative while the selected map name and world remain the same. Ordinary games
use the original cache. Originals are never overwritten. Renaming an MCC cache
or changing its header is not a conversion.

## Version 1 weapon profile

All contains 31 reviewed playable definitions from installed stock and community
maps: the eight launch weapons, canonical Flamethrower, and 22 namespaced imports.
The imports include restored Digsite designs, later/community weapons,
multiplayer Needler, Longshot Rocket Launcher, Empty Rocket Launcher, and melee Skull.
Objective/vehicle definitions without player first-person assets do not qualify.
Vehicle-named handheld adaptations qualify only through their reviewed definitions.

Uncut contains nine restored designs: SMG, assault rifle/grenade launcher,
Chaingun, Excavator, Gravity Wrench, Machete, Speargun, Space Luger, and Missile
Launcher. Its strict list is independent of All's broader inventory. Official
Digsite describes recovered SMG/ARGL and reconstructed first-person assets in
[Digsite Deliveries](https://www.halowaypoint.com/news/digsite-deliveries), other
recovered designs in [Cutting Room Corps](https://www.halowaypoint.com/news/cutting-room-corps),
and assets in the [official H1 repository](https://github.com/digsite/h1).

The authored Empty Rocket Launcher starts with **zero ammunition** and cannot
fire at spawn; its melee remains available. Its ammo-object grant is also zero,
so ordinary ammo pickup is not promised. The pack preserves that behavior. Longshot starts with two
rounds and retains authored ammo limits, integrated night vision and autoaim
differences. Multiplayer Needler retains authored projectile/camouflage/melee
differences. Skull uses ordinary inventory flags and the ball first-person/melee
assets; it is distinct from the configured Oddball objective. A full installed
inventory audit checked 37 identities and 47 distinct source definitions across
54 selectable caches. Ghost/Warthog guns and Gravity Rifle lack first-person
assets; configured Ball/Flag retain objective flags and are excluded. The one
Flamethrower compatibility alias is deduplicated.

The canonical list is lowercase ASCII paths without extension, using backslashes,
sorted, one path per line including a final newline. Its SHA-256 is
`2856504cbd257e1b18c273caa64237fbfe77dc77d22cce1a7fa0a0abfc53f71f`.
The tool/runtime pin the exact list; a missing or unexpected eligible weapon fails
construction. A private-player marker lets the runtime prefer imported global
definitions over authored same-path copies. The canonical Flamethrower retains
precedence over its compatibility alias.

## Preserved content and scoped animations

`tools/weapon_pack_maps.py` copies each scenario's closure and the pinned builder's
four implicit multiplayer roots: globals, white bitmap, multiplayer game text,
and multiplayer UI collection. Imported closures are copied using
`invader-refactor -M copy` beneath `community/weapon_pack/`. Case-insensitive base
and import collisions are refused. Community variant dependencies first receive
separate source namespaces so Digsite overlays cannot replace their authored
projectile, damage, model or sound assets.

Palette references embed the arsenal without adding world objects. The global
profile also retains the eight launch definitions and canonical Flame explicitly
in each derivative's palette, including maps whose original cache omitted one.
Erasing all appended references must reproduce the original scenario bytes.
All source definitions and original caches are hashed before/after authoring.
Base geometry and placement dependencies remain byte-identical source tags.

First-person model/animation references alone do not prove pickup compatibility.
Selected definitions need ordinary inventory flags and their unchanged weapon
label in both stand and crouch player stances. The stock graph lacks labels for
Sword, Machete, Fuel Rod, Speargun and Missile Launcher.
`--fiesta-player-graph` selects the reviewed Digsite cyborg graph only in the
hidden Fiesta cache. A copied player at `community/weapon_pack/player/cyborg.biped`
is copied from the actual multiplayer unit (stock `cyborg_mp`), then changes only
its animation-graph reference. Copied globals change only
`multiplayer_information[0].unit`; the separate singleplayer reference remains
unchanged. Reversing either change must reproduce exact original bytes. A further
compiled-cache proof freshly extracts the original multiplayer biped and the
private derivative, restores the original animation reference, and requires the
entire extracted HEK file to match. This checks physics, shields, health and every
other player field after compilation, rather than assuming SP/MP definitions are
interchangeable. Actual compiled multiplayer globals must select the private
player. Labels are never substituted.

The graph has the same 19 node names/order/topology and clip node-list checksum as
the original stock model/graph, 324 clips rather than 195, and all stock clip names.
This proves skeleton compatibility, not identical motion. All 195 shared clip
payloads differ; recompression/equivalence is not presumed. Four shared header
next-index changes point to the same next clip names. One visible departure is
intentional: `W-passenger rifle idle` changes from 40 frames of frame size 40 to one
frame of frame size zero. Shared keyframes, second keyframes, sound/foot events
and flags are unchanged. Ordinary caches retain the original graph.
`tools/weapon_pack_animation_audit.py` bounds-checks and records the exact audit.

Combat-AI scenarios are refused. Compiled scripts without embedded source require
original reviewed HSC data with `--data`; the compiler reads private hashed
copies. Embedded source is retained and compiled from tags. Stock message/HUD
tables and balance fields are not rewritten to fix custom pickup presentation.

## Preparation and compilation

Use reviewed Xbox-compatible HEK inputs and the pinned toolchain from
[community-map-conversion.md](community-map-conversion.md). These ignored local
artifacts are prerequisites, not files supplied by a fresh checkout. Source
extraction and helper hashes are recorded. A reviewed patched builder is accepted
only when its binary digest and original Invader revision match.

The high-level commands are:

1. `prepare`: extract/audit all 13 original Xbox multiplayer caches into a fresh
   stock source tree, recording reviewed NTSC compatibility repairs.
2. `prepare-installed`: consume a frozen normal-resolver inventory of logical
   names, exact cache paths and base hashes; extract each custom map into its own
   source tree. Selected original data takes precedence over an overlay.
   Unapproved files absent from normal selection are excluded.
3. `prepare-extra-weapons`: pair each selected extra weapon with its exact source
   root, keeping its identity while isolating its dependency closure.
4. `build`: verify source hashes, then compile all selected maps with ordered
   reviewed weapon roots, compatible Fiesta graph, and the version 1 list.
   `--map` selects a diagnostic subset; default builds the entire frozen
   inventory. `--jobs` allows one to four independent workers.

For example, after reviewed preparation:

```sh
python3 tools/build_fiesta_arsenal.py build \
  --prepared build/reviewed-installed-sources \
  --weapon-tags build/reviewed-extra-weapons/tags \
  --weapon-tags build/reviewed-digsite/xbox-overlay \
  --weapon-tags build/reviewed-digsite/tags \
  --digsite-data build/reviewed-digsite/data \
  --reviewed-build-manifest build/reviewed-compiler/manifest.json \
  --output build/private-global-arsenal \
  --jobs 3 \
  --invader-bin /absolute/path/to/reviewed/invader/build \
  --invader-manifest /absolute/path/to/source-manifest.json
```

Use a fresh ignored `build/` directory every run, including after failure.
Traversal/symlink output escapes are refused. Variant manifests record closures,
source/generated hashes, provenance, compiler arguments, script snapshots,
compatibility and reverse proofs, headers, and native-validation status.
The compiler's `-E` profile exceeds retail Xbox's 47 MiB limit; this native port's
128 MiB declared cache and 22 MiB tag-arena limits remain mandatory.
This does not certify retail Xbox hardware compatibility.

## Hidden catalog and validation

Storage is `maps/arsenal/v1/<physical>.map` with adjacent `<physical>.json`.
Logical names up to 23 characters use `_fiesta_<logical>`. Longer safe names use
`_fiestah_` plus the first 16 hex digits of SHA-256 of lowercase ASCII logical name.
`physical_name()` is shared with installation tooling. Runtime/network selection
retains the original logical name.

Bounded flat JSON declares `schema_version`, `generation`, `logical_map`,
`physical_map`, `cache_sha256`, `base_sha256`, `weapon_list_sha256`,
`cache_file_bytes`, and `cache_declared_bytes`. The base hash must match the
actual normal-resolver original. Network identity uses the full cache digest;
Invader's header checksum is unsuitable. High-level `catalog.json` additionally
records actual eligible paths and authoring manifests. Compilation does not
install content or prove native/network behavior.

The first full 31-weapon Prisoner derivative with the corrected multiplayer player is at
`build/global-fiesta-prisoner-20261006-r04/maps/arsenal/v1/_fiesta_prisoner.map`.
Its SHA-256 is
`6333c68f852542e3deb2fb11ad77d16522321dfc1699c0b7ce0ef21827a33ca3`.
It passes source/scenario/player reference preservation, compiled multiplayer
player equivalence, and 31 eligibility
checks. Full-inventory compilation and native checks are separate evidence in
[Fiesta validation](fiesta.md#local-validation). The earlier 14-import Blood Gulch
sample does not certify this full global profile.

The completed global library is
`build/global-fiesta-installed-arsenal-20261006-r02/maps/arsenal/v1`, covering all
13 stock and 41 approved custom multiplayer maps in the frozen normal-resolver
inventory. Adjacent `catalog.json` records every map's paths, hashes and proofs;
`completion-verification.json` checks all 54 cache/manifest/base hashes, headers,
31/9 pools, source-world preservation and compiled player equivalence. Original
caches remain unchanged. Total compressed cache size is 1,994,752,000 bytes.
The largest declared cache is 122,735,616 bytes and largest tag arena 15,924,736
bytes, both Digsite, within native limits. Exact authoring source snapshots are
stored alongside the completion report. Native validation and installation are
separate from these construction proofs.

The native texture cache retains the original 22 MiB allocation and page budget
for ordinary maps, UI and campaign. Loading an accepted hidden global Fiesta
cache for the exact selected logical map replaces that empty arena with 32 MiB;
the next ordinary map restores 22 MiB. Allocation failure preserves the prior
arena and fails the map load. The budget remains fixed while that map is open,
including borrowed movie/precache memory. Diagnostic logs record budget changes.
The original 1,408 texture/LRU datum slots and all world placements remain intact.
Global Fiesta also skips the added whole-pool eager weapon prewarm; selected
weapons retain ordinary prediction and rendering requests.

This scoped capacity addresses observed Digsite global-Fiesta pressure: the
initial load filled all 1,408 pages in one allocator frame, and a later 171-page
cyborg texture request encountered a largest available contiguous run of only
95 pages. Dump markers include age-one blocks as locked for reporting, whereas
allocation directly pins age-zero/incomplete/busy blocks, so the later failure
is evidence of fragmentation rather than proof that all reported locked pages
were simultaneously unevictable. Sanitized fixtures exercise production page
allocation, map transitions, failed growth/shrink, borrowing, and diagnostics;
native renderer checks remain separate evidence.

Run authoring safety fixtures:

```sh
python3 -m unittest discover -s tools -p test_weapon_pack_maps.py
python3 -m unittest tools.test_texture_cache_budget
```

## Delivering hidden arsenals

The hidden Fiesta profile is separate from the visible 41-map community catalog.
Its public endpoint is
`https://dl.oghalo.com/catalogs/testing/arsenals-v1.json`. Root fields are exactly
`schema_version`, `profile` (`fiesta-arsenal-v1`), `generation` (1),
`weapon_list_sha256`, and `arsenals`. Each entry contains exactly
`logical_map`, `physical_map`, `base_sha256`, `cache_sha256`, `cache_file_bytes`,
`cache_declared_bytes`, `manifest_sha256`, `manifest_bytes`, `cache_object_key`,
and `manifest_object_key`. Identity is the logical map plus the original-cache
SHA; different original revisions may coexist, but duplicate identities are
rejected. The existing flat nine-field runtime manifests remain unchanged.

Cache objects use `arsenals/v1/sha256/<cacheSHA>/<physical>.map`; manifest objects
use `arsenals/v1/sha256/<manifestSHA>/<physical>.json`. The index contains no
authoring paths, extracted tags, helper binaries or native logs. These derivative
caches contain their normal embedded Halo dependencies; players still supply
the exact original map, which is checked against `base_sha256`. Original stock,
campaign and UI maps are not uploaded as base-map objects or included in the app.
The visible community catalog and its publisher allowlist remain unchanged.

After committing and pushing the requested source changes, prepare and validate
a fresh delivery tree from the verified outputs:

```sh
python3 tools/arsenal_catalog.py \
  --authoring-catalog build/global-fiesta-installed-arsenal-20261006-r02/catalog.json \
  --arsenal build/global-fiesta-installed-arsenal-20261006-r02/maps/arsenal/v1 \
  --output build/fiesta-arsenal-delivery-v1

python3 tools/publish_arsenal_catalog.py \
  --prepared build/fiesta-arsenal-delivery-v1

python3 -m unittest tools.test_arsenal_catalog tools.test_publish_map_catalog
```

`--map prisoner` optionally prepares a diagnostic subset. Public preparation
checks the full 31/9 weapon list, recorded player preservation proof, exact cache
header/hash/size, and flat-manifest correspondence before copying only delivery
objects. The clean index permits at most 115 entries and 1 MiB; each cache is
bounded to 128 MiB, each flat manifest to 4096 bytes, and the complete transfer
batch to 2 GiB. Files and directory names cannot escape the new ignored output.
Public logical names start with a lowercase ASCII letter or digit, use only
lowercase letters, digits, spaces, underscores and hyphens, and cannot end in a
space or exceed 31 characters. UI, campaign and Windows device basenames are
excluded. Physical names follow the same generation-one rule as the runtime.

[`arsenal-publisher.json`](../tools/arsenal-publisher.json) explicitly allows the
54 reviewed logical maps. The publisher defaults to offline validation, reads no
credentials and makes no network calls until `--publish` is supplied. For the
authorized upload, use an existing 1Password-mounted credential file with
`--credential-file`; never copy its values into source, logs or a new env file.
It shares the existing SigV4 uploader: create immutable objects conditionally,
verify each through authenticated R2 and public HTTPS, then advance only the
hidden catalog using the captured ETag. Publication failures do not imply a
rollback; unchanged verified objects can be reused safely on retry.

The current 54-cache delivery contains 1,994,752,000 cache bytes and 23,986 flat
manifest bytes. The clean JSON index is 40,011 bytes, making the initial object
plus catalog upload **1,994,815,997 bytes**. The catalog SHA-256 is
`f3bb16570d151ca929d0e8211af1c4ddf28b8e80548e8787925ca861deed3b0d`.
These figures describe the frozen generation-one outputs, not an upload receipt.
Build the exact committed app, publish/verify the matching assets, and exercise
a clean client downloading and joining Prisoner before publishing its app update.
