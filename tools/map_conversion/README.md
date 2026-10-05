# Authored HUD conversion helper

`convert_hud.cpp` applies reviewed numeric tag edits and physical HUD atlas
resizes inside a fresh output overlay. It preserves authored art rather than
substituting a stock weapon layout. It does not infer a map's intended HUD size.
Use a map-specific inventory and profile; a factor measured for one atlas is
not a default for other assets.

The helper was implemented against Invader commit
`7d25a855f5ef9e4ab8407abf490b21f8780abf27`, using its tag parser and bitmap codec
API. It embeds no Invader implementation, map, tag, ISO, game asset, or binary.
The helper source is GPL-3.0-only and the separately built helper links GPL
Invader/RIAT libraries. Preserve the matching source and dependency license
notices when distributing a compiled helper. The reviewed toolchain recipe and
dependency sources are described in [community-toolchain](../community-toolchain/README.md).

## Build

Use an independently reviewed local Invader toolchain containing its source
headers, generated parser headers, `libinvader.a`, RIAT static library, and
native dependency prefix. The macOS command below matches the validated local
ARM64 build layout; set the temporary shell variable to your own reviewed
toolchain directory. No installation or application settings change is needed.

```sh
hud_toolchain_root=/absolute/path/to/reviewed/toolchain
mkdir -p build/map-conversion
/usr/bin/clang++ -std=c++20 -O2 \
  -I"$hud_toolchain_root/invader/include" \
  -I"$hud_toolchain_root/build" \
  -I"$hud_toolchain_root/prefix/include" \
  tools/map_conversion/convert_hud.cpp \
  "$hud_toolchain_root/build/libinvader.a" \
  -L"$hud_toolchain_root/prefix/lib" \
  -lz -lFLAC -lvorbisenc -lvorbisfile -lvorbis -logg -lsamplerate -lsquish \
  "$hud_toolchain_root/riat-build/release/libriatc.a" \
  -framework Security -framework CoreFoundation -liconv \
  -o build/map-conversion/convert-hud
build/map-conversion/convert-hud --help
shasum -a 256 build/map-conversion/convert-hud
```

Linux and Windows need their platform's dependency paths and system libraries;
the command above does not certify those hosts. The engine source and shared
Invader toolchain remain unchanged. The compiled helper belongs under ignored
`build/`, not in source control.

## Reviewed profile and orchestration

Copy [hud-profile.example.json](hud-profile.example.json) into a private map
workspace and replace its placeholder hashes and tag fields with measured
values. The example contains no proprietary data and intentionally fails
source-hash verification until filled in. `preservation_checks` records review
requirements; it is descriptive metadata, not executable behavior.

Required profile contract:

- `schema_version`: `1`.
- `target_engine`: `"xbox"`.
- `write_policy`: `"fresh_overlay"`.
- `source_tree`: `"source-tags"` for extracted author input, or `"tags"` for a
  reviewed working derivative. These choices are explicit; a later derivative
  must not be mistaken for original author input.
- `tags`: normalized relative tag paths mapped to their expected SHA256 hashes.
  Every tag used by a rule must be listed.
- `field_rules`: `tag`, numeric `field`, expected `before`, explicit `after`, and
  a readable `reason`. Scalars and fixed numeric vectors are supported; nested
  reflexives use paths such as `crosshairs[0].crosshair_overlays[0].width_scale`.
- `bitmap_resamples`: `tag`, `divisor` (`2` or `4`), and a readable `reason`.

From the repository root, run the checked orchestration with the helper hash
from your build:

```sh
python3 tools/community_map_conversion.py hud-overlay \
  --workspace /absolute/path/to/private/map-workspace \
  --profile /absolute/path/to/reviewed-hud-profile.json \
  --converter "$PWD/build/map-conversion/convert-hud" \
  --converter-sha256 REVIEWED_HELPER_SHA256 \
  --output /absolute/path/to/new-hud-overlay
```

The output must be new. Orchestration verifies source/profile/helper hashes,
copies selected input tags into independent `source-snapshots/` and `tags/`
trees, writes `field-rules.tsv` and `bitmap-rules.tsv`, invokes the helper once,
and records output hashes. The native interface is `convert-hud OVERLAY_DIRECTORY`.
It rejects traversal, absolute tag paths, symlinks, hard-linked snapshot/output
pairs, changed source expectations, and repeat conversion. A failure leaves an
isolated output for inspection; do not compile or activate an incomplete result.

## Conversion limits and validation

Ordinary HUD element placement scales preserve image resolution and meter
alpha/channel data. Fixed-size native pickup, number, or damage-indicator
paths can require physical normalization instead. Number sprite dimensions
and HUDNumber advance metrics must be measured independently. Offsets, scope
masks, zoom layers, and already-correct stock dependencies need separate rules.

Atlas resampling accepts 2D, single-depth images without mipmaps. It averages
alpha and uses alpha-weighted color to protect transparent edges, emits legacy
32-bit pixels, retains image order, sprite UVs and normalized registration
points, and clears the MCC resolution flags on the physically normalized
bitmap. A physical resize reduces pixel resolution; it is an explicit quality
decision. It does not remap sprites or replace artwork. Other mip, face, or
depth layouts fail closed.

Every changed field is checked before editing and every output tag is reparsed.
Numeric targets must fit their stored tag types and retain the requested value
after storage. Recorded HUD overlays with failed conversion or changed output
hashes are rejected by the compile and provenance commands. Other reviewed
overlay directories remain explicit inputs; they need their own acceptance
record.
Verify pixel equality for protected art, exact sequence metadata, resulting
logical dimensions, and counter advance. Then compile the Xbox cache and check
the actual engine size limits, followed by separate held-weapon, pickup,
counter, scope/zoom, and split-screen runtime coverage. Successful compilation
alone does not establish presentation fidelity or retail parity.

## PCM sound compatibility

`convert_sounds.cpp` and `convert_sounds.py` provide a separate, explicit sound
overlay. Some imported maps contain valid 16-bit PCM that Invader permits in
an Xbox cache because other engines support it through mods. The original Xbox
sound manager in this project accepts Xbox ADPCM: mono at 22,050 Hz, or stereo
at the supported rates. A cache that compiles can still contain refused sounds.
Audit the compiled map's reachable sound tags against that runtime gate.

Build the helper with the same reviewed toolchain command above, replacing
`tools/map_conversion/convert_hud.cpp` with
`tools/map_conversion/convert_sounds.cpp` and the output with
`build/map-conversion/convert-sounds`. This C++ helper is GPL-3.0-only and uses
the pinned Invader sound reader/encoder APIs. The Python wrapper contains no
audio assets and does not change the engine or application configuration.

Copy [sound-profile.example.json](sound-profile.example.json) into your private
workspace and list each reviewed source tag with its expected SHA256. The
placeholder intentionally fails verification. `origin` is descriptive
provenance, not evidence of historical authorship. Then run:

```sh
python3 tools/map_conversion/convert_sounds.py \
  --source-tags /absolute/path/to/reviewed/source-tags \
  --profile /absolute/path/to/reviewed-sound-profile.json \
  --converter "$PWD/build/map-conversion/convert-sounds" \
  --converter-sha256 REVIEWED_HELPER_SHA256 \
  --output /absolute/path/to/new-sound-overlay
```

The wrapper checks every expected source hash and helper hash before creating
the output. It copies independent `source-snapshots/` and `tags/` trees, invokes
the helper once, and records input/output hashes and whether sources stayed
unchanged. The native helper rejects traversal, symlinks, hard links, changed
snapshots and repeat conversion. Failed overlays remain isolated for inspection
and must not be compiled.

Only 16-bit PCM is supported here. HEK tag PCM is big endian; Invader's reader
converts it to little endian before encoding. Mono must already be 22,050 Hz;
stereo can be 22,050 or 44,100 Hz. The helper fails other rate/channel layouts
instead of resampling or changing pitch. No gain normalization occurs. It
preserves every playback field, including class, distance, random pitch,
permutation gain, promotion references and permutation chains, verified by a
full parser comparison after isolating the intended codec/sample/buffer edits.
Xbox ADPCM uses 36 bytes per channel for 64 frames; at most 63 zero frames are
added when an input is not aligned. The conversion log records original frames,
padding, encoded bytes, reference decoder signal-to-noise ratio and peak error.
ADPCM encoding is lossy; exact playback metadata does not imply waveform
equality. Duration is unchanged only when padding is zero; inputs already
aligned to 64 frames need no padding.

Put the resulting `tags/` root before the other source roots when compiling.
Re-audit all reachable sounds, then trigger representative actual ready, idle,
fire, melee, reload and overheat events in a separate diagnostic game. Record
unsupported-format warning counts and voice activity. Static compatibility does
not certify every event or audible quality. Existing engine sound-adapter
behavior is outside this asset conversion's scope.

## Proven duplicate Chicago shader layers

`convert_chicago_layers.cpp` handles one specific imported shader compatibility
case. The current January renderer's Chicago extra-layer loop repeatedly draws
layer zero because its loop index never advances
(`source/rasterizer/xbox/rasterizer_xbox_transparent_geometry.c`). This can stall
rendering when an imported shader has a nonempty extra-layer block. The generic
shader loop advances normally; do not remove its layers or strip all layered
shaders.

Build this GPL-3.0-only helper with the reviewed Invader recipe above, replacing
`convert_hud.cpp` with `convert_chicago_layers.cpp` and naming the output
`build/map-conversion/convert-chicago-layers`. It uses Invader's parser API and
contains no game assets or renderer changes. Record its SHA256 and the pinned
source/library provenance before use.

Copy [chicago-layer-profile.example.json](chicago-layer-profile.example.json)
into the private map workspace. List the parent shader, its single terminal
duplicate shader, and every bitmap they reference with reviewed source hashes.
The example placeholders intentionally fail verification. Each explicit
action names `parent` and `duplicate_layer`; it permits no general field edits.

```sh
python3 tools/map_conversion/convert_chicago_layers.py \
  --source-tags /absolute/path/to/reviewed/source-tags \
  --profile /absolute/path/to/reviewed-shader-profile.json \
  --converter "$PWD/build/map-conversion/convert-chicago-layers" \
  --converter-sha256 REVIEWED_HELPER_SHA256 \
  --output /absolute/path/to/new-shader-overlay
```

The wrapper verifies the profile, all input hashes and the helper hash before
creating a new overlay. It saves independent snapshots of all dependencies and
copies only selected parent shaders into the output `tags/` tree. The native
helper requires exactly one extra layer whose shader has no further layers. It
proves that corresponding bitmap files are entirely byte-identical, then
normalizes only those dependency identities for a strict full parser comparison
of both shaders. Any differing shader parameter or art causes rejection.
Removing the single duplicate layer is the only accepted mutation; a reparse
and comparison after restoring that layer verifies every primary parameter,
numeric counter limit, bitmap reference, transform and color stays unchanged.
Nonredundant layers need a separately reviewed conversion; this tool rejects
them. Traversal, symlinks, hard links and repeat conversion are rejected.

The manifest records input and output hashes, source/snapshot integrity and the
renderer evidence. Only outputs with `status: converted` may be compiled, with
their `tags/` root before other roots. Re-audit reachable Chicago shaders and
test the affected weapon's equip, numeric screen, zoom, firing and reload.
Removing a repeated blend pass can change grayscale brightness even when its
parameters and art match, so visual acceptance remains separate from static
proof. This compatibility conversion does not establish intended historical
appearance or change stock rendering behavior.

## Map-local aliases for reserved weapons

`convert_weapon_alias.cpp` handles an explicit community adaptation when an
imported author grant points at a weapon identity that the stock multiplayer
engine remaps. The original Flamethrower globals slot, for example, is remapped
to the rocket launcher in `source/game/game_engine.c`. A map-local alias outside
the reserved globals list allows a reviewed authored grant to use the original
weapon data. The stock globals list and engine remap remain unchanged. This is
a deliberate community departure, recorded in the manifest; it does not claim
the resulting weapon selection is stock Xbox behavior.

Build the GPL-3.0-only helper using the pinned Invader recipe above, replacing
`convert_hud.cpp` with `convert_weapon_alias.cpp` and naming the output
`build/map-conversion/convert-weapon-alias`. The helper contains no game assets.
First inventory references across every reachable compiled tag, resolving the
effective source roots in compile order. For each source root, write a list of
its effective tag paths, one per line, and run:

```sh
build/map-conversion/convert-weapon-alias --inventory \
  /absolute/path/to/source-tags /absolute/path/to/paths.txt \
  weapons/flamethrower/flamethrower.weapon
```

The read-only inventory prints owner tags and field selectors for exact weapon
dependencies. Separately inspect the map's custom spawn scripts; script source
is not a typed tag dependency. Retarget only the reviewed author references.
Do not change the reserved globals slot or broadly refactor every reference.
If no production author reference exists, report that result before proposing
an adaptation.

Copy [weapon-alias-profile.example.json](weapon-alias-profile.example.json)
into a private map workspace. Record the original weapon, a fresh `community/`
alias path, the original globals slot, and each reviewed scenario or item
collection owner with its exact replacement count. Pin all three categories of
input hashes. Example placeholders intentionally fail verification.

```sh
python3 tools/map_conversion/convert_weapon_alias.py \
  --source-tags /absolute/path/to/reviewed/source-tags \
  --profile /absolute/path/to/reviewed-alias-profile.json \
  --converter "$PWD/build/map-conversion/convert-weapon-alias" \
  --converter-sha256 REVIEWED_HELPER_SHA256 \
  --output /absolute/path/to/new-weapon-alias-overlay
```

The wrapper verifies hashes before creating a fresh overlay and independent
source snapshots. The alias is a byte-identical copy of the original weapon.
Only selected scenario or item collection owners are serialized after changing
their dependency identities. The native helper verifies exact reference counts,
reparses each output, and reverses the refactor for an exact full parser
comparison proving every other parameter stayed unchanged. It verifies that
the original globals slot still points to the original weapon and the alias
occupies no reserved slot. Globals are never emitted into the overlay. Existing
aliases, repeat conversion, traversal, symlinks and hard links are rejected.

Compile only `status: converted` outputs with their `tags/` root first. Re-audit
the compiled references and test the affected weapon's actual grant, equip,
HUD, firing and depletion in a separate diagnostic map. Static byte and metadata
preservation does not certify playability or intended historical appearance.

## Select an existing authored lower mip

`select_existing_mip.cpp` handles a measured texture-cache allocation failure
for a reviewed ordinary texture. Before using it, inspect the engine's native
`stabbed.txt` cache dump and identify the failed bitmap, requested page count,
and locked page usage. A `YOU GOT STABBED` engine message indicates texture
allocation failure; it is not an authored weapon sound or taunt. The sound
cache has a separate `SOUND CACHE BLOWN` allocation-failure message. Do not
guess that an explosion effect caused the warning when the native dump names
a first-person skin that already failed before firing.

First check whether identical art and bitmap parameters can share an existing
bitmap identity without changing pixels or sampling behavior. If the art
differs, selecting an existing lower mip is a deliberate resolution tradeoff.
This helper accepts only one 2D 2048-by-2048 DXT5 image with its complete authored
mip chain and removes its highest mip. The original 1024 and lower compressed
mip bytes remain exact; no resampling or recompression occurs. The engine's
cache limit and weapon gameplay stay unchanged.

Build the GPL-3.0-only helper with the pinned Invader recipe above, replacing
`convert_hud.cpp` with `select_existing_mip.cpp` and naming the output
`build/map-conversion/convert-existing-mip`. Copy
[existing-mip-profile.example.json](existing-mip-profile.example.json) into
the private workspace and pin the reviewed source bitmap hash. Each action
explicitly selects bitmap index zero and drops one top mip; no general scaling
or arbitrary bitmap edits are supported.

```sh
python3 tools/map_conversion/select_existing_mip.py \
  --source-tags /absolute/path/to/reviewed/source-tags \
  --profile /absolute/path/to/reviewed-mip-profile.json \
  --converter "$PWD/build/map-conversion/convert-existing-mip" \
  --converter-sha256 REVIEWED_HELPER_SHA256 \
  --output /absolute/path/to/new-texture-overlay
```

The wrapper verifies input and helper hashes before making independent source
snapshots and a fresh output tree. The native helper proves the retained mip
payload matches the original bytes and checks exact parser equality after
restoring the scoped size, mip and payload edits. All other bitmap parameters
stay unchanged. Traversal, symlinks, hard links and repeat conversion are
rejected. Failed overlays remain isolated and must not be compiled.

Compile accepted `tags/` before other source roots, then validate the affected
weapon's equip, zoom, firing and reload in the actual game. Check both cache
warning messages and fallback-texture appearance. Removing the highest mip
can reduce close-up sharpness even when all retained art is exact; runtime
appearance acceptance remains separate from the static preservation proof.

## Prepare a multiplayer profile and restore reviewed markers

Single-player diagnostic grants are not multiplayer starting rules. Review the
scenario and HSC separately before promoting an imported map. For the Chillout
Digsite POC, the exact reviewed changes were:

1. Copy the scenario into a fresh private overlay with the unique tag/cache name
   `chillout_digsite`. Keep the original `chillout_dig` test cache separate.
2. Pin the copied input scenario hash and verify there are exactly four starting
   profiles, with `digsite_poc_smg` at index 3. Remove only that profile. An
   `invader-edit -n -E 'player_starting_profile[3]'` operation is appropriate only
   after those expectations pass; indices are not portable across maps.
3. Verify the copied scenario's `scripts`, `globals`, `references` and
   `source_files` tables are already empty in this reviewed working input.
   Create an explicitly reviewed private HSC file rather than reusing MCC
   bytecode. Remove the one-player SMG grant and its typed probe global. Retain
   the existing pro-mode sword exclusion and two native-compatible scripts.
4. Preserve authored geometry, spawns, equipment placements, objective flags,
   three original grenade profiles and the weighted short/long starting weapon
   collections. Native spawning consumes these collections; a diagnostic grant
   must not replace their behavior.
5. Record omitted optional MCC behavior: host flycam/teleport, timer/navpoint
   aids, flashlight taunts, blue-team armor overrides and parameterized grenade
   workaround scripts. The native Xbox script target has no formal script
   parameters or MCC-only `game_is_authoritative`, `local_players`,
   `players_on_multiplayer_team` and `game_time_authoritative` calls. Do not
   silently drop authored gameplay or invent replacement engine APIs.
6. Pin the private HSC hash, helper/compiler hashes and ordered asset overlays.
   Compile fresh source with `-g xbox-ntsc -S data` and the reviewed compiler.
   Verify the unique cache identity, actual script/reference operands, absence
   of diagnostic grants, native cache bounds and embedded resources. Keep
   multiplayer, damage, objective scoring and audible acceptance separate.

These steps are an explicit map-specific script policy. This helper directory
does not automatically strip scripts or choose a map's spawn rules.

`append_netgame_flags.cpp` and `append_netgame_flags.py` extract the repeatable
marker-copy operation. A reviewed profile pins both source and target scenario
hashes, the existing target flag count, both counts for the selected type, and
an ordered list of usage IDs. The native helper copies actual parsed source
structs, preserving position/facing float fields without rebuilding them from
decimal text. It rejects missing/duplicate selected markers, target ID
collisions, stale counts and repeat conversion. Reparse and reverse-append
comparisons prove every original target field remains unchanged.

Version 1 supports individually identified CTF flags, ball spawn markers, Race
checkpoints and teleporter entry/exit markers. Each selected type/ID must name
exactly one source marker. Hill polygons and vehicle markers require separate
review and are deliberately unsupported. The wrapper enforces the stock limit
of 200 total flags, Race IDs below 32 and CTF IDs 0/1. A legal marker import
does not certify a complete route, paired teleporter or objective setup.

Chillout Digsite had no authored Race checkpoint markers. The reviewed
compatibility candidate appends the twelve original Xbox Chillout checkpoints,
preserving their source fields and IDs 0–11. This is a deliberate stock-Xbox
checkpoint restoration for the imported map. Record the exact stock cache/tag
hashes and geometry audit in the private profile's provenance. Preserve all
original Digsite flags/spawns/BSP fields; no Race vehicles or engine rules are
added. Static geometric agreement still requires native route traversal and
lap/scoring checks on multiplayer peers before acceptance.

Build the GPL-3.0-only helper with the pinned Invader recipe above, substituting
`append_netgame_flags.cpp` and the output name
`build/map-conversion/append-netgame-flags`. Record the build command, source
hash and resulting helper hash. Copy
[netgame-flags-profile.example.json](netgame-flags-profile.example.json) into
a private workspace and fill every placeholder after reviewing that map. The
example contains no source coordinates or game assets and fails until reviewed
hashes are supplied. It does not express a default route.

```sh
python3 tools/map_conversion/append_netgame_flags.py \
  --source-tags /absolute/path/to/reviewed/stock-tags \
  --target-tags /absolute/path/to/reviewed/multiplayer-tags \
  --profile /absolute/path/to/private/marker-profile.json \
  --converter "$PWD/build/map-conversion/append-netgame-flags" \
  --converter-sha256 REVIEWED_HELPER_SHA256 \
  --output /absolute/path/to/new-marker-overlay
```

The wrapper verifies source, target, converter source and binary hashes before
creating an output. The overlay retains independent source/target snapshots,
reviewed profile, converter source, explicit action file and `conversion.json`
provenance. Compiler orchestration accepts only successful managed overlays
whose profile, action file, source snapshots and exact output hash still match.
Failed overlays remain isolated. Symlinks, hard links and existing output
directories are rejected. Use the accepted `tags/` root first with the reviewed
HSC data and compiler; re-audit compiled marker bytes and native bounds.

Run the data-free boundary checks with:

```sh
PYTHONPATH=tools python3 -m unittest \
  tools/test_community_map_conversion.py \
  tools/map_conversion/test_append_netgame_flags.py
```

