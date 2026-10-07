# Converting community maps and weapon sets

For directory batches, start with the
[offline map conversion pipeline](map-conversion-pipeline.md). It centralizes
versioned profiles, source and output checksums, authored menu metadata and
per-map builder diagnostics. The asset-specific findings below remain the
evidence for scoped conversions and acceptance checks.

The generic `og-multiplayer-v5` profile now supplies source-bound Vorbis/PCM,
BC7, existing-mip and exact pixel-packing stages. The historical recipes below
describe additional scoped decisions; they are not prerequisites for these
format-based stages. See the pipeline guide for current policies and helper builds.

Community conversion adapts imported content to Halo OG's Xbox-derived runtime.
It does not make that content part of the original Xbox game. Keep original
Xbox NTSC gameplay and presentation as the stock baseline; put custom weapons,
scripts, artwork and conversion choices in a map-local import profile. See the
[fidelity policy](xbox-fidelity.md) and [community map guide](community-maps.md).

The Chillout Digsite proof of concept established a working path from an MCC
CEA cache to an Xbox v5 map. It is an offline, one-player conversion with a
reviewed script subset and custom weapon smoke coverage. It does not establish
full MCC behavior, every weapon's fidelity, or multiplayer acceptance.

The separate multiplayer candidate uses `chillout_digsite` rather than updating
the POC's `chillout_dig` identity. Its script profile removes the first-player
SMG grant and typed SMG probe, preserves the three authored grenade profiles
and native random starting-equipment lists, and retains the native-compatible
pro-mode sword filter. Original Digsite spawns, CTF bases, Oddball locations,
hill polygons, teleporters and item placements remain authored content. Twelve
Race checkpoints are restored from the exact original Xbox Chillout scenario;
that is a recorded compatibility addition, not an authored Digsite Race course.
Their coordinates and IDs are copied without changing native Race rules.

This multiplayer conversion is available in the Cloudflare testing catalog as
**Chillout Digsite**. Static eligibility checks pass for all nine classic mode
presets. Two native peers verified CTF, Oddball, Team Oddball, King and Team King
scoring, natural match end and rematch against the published checksum. Slayer,
Team Slayer, Race and Team Race qualification remains pending; the user accepted
publication for player testing with that coverage. See the separate
[native multiplayer checks](community-multiplayer-testing.md) and
[distribution record](map-publishing.md).

## Choose the importer for the content

| Input | Entry point | Dependency policy |
|---|---|---|
| Reviewed JukkisP H1PB Beta 3 package, with source `tags/` and `maps/` | [`tools/community_maps.py`](../tools/community_maps.py) and [`port/maps/jukkis-beta3.json`](../port/maps/jukkis-beta3.json) | Stock Xbox tags first, with reviewed script cleanup and map-identity aliases |
| A newly reviewed cache or custom weapon set | [`tools/community_map_conversion.py`](../tools/community_map_conversion.py) | Authored tags first, explicit conversion overlays before them, stock tags only as a recorded fallback |

The H1PB policy intentionally supplies stock gameplay dependencies. Do not copy
its substitutions or script removal into an arbitrary Digsite/custom-weapon
import: a stock-first lookup can silently replace a mod's weapon, HUD or effects.
In either path, never replace authored scenario/BSP content through a stock name
collision. Use a unique scenario/cache identity; `chillout_dig` remains distinct
from retail `chillout`.

The reusable conversion tool separates preparation, model conversion, reviewed
HUD overlays, compilation and provenance reporting. Consult its current CLI
before running a recipe:

```sh
python3 tools/community_map_conversion.py --help
```

It does not silently remove scripts, rebalance weapons or add engine support.
Generated maps, extracted tags, previews, binaries and runtime reports belong
in fresh ignored directories under `build/`, not in Git.

The following uses example input/tool/profile paths; supply your reviewed local
inputs. The workspace and overlay destinations must not already exist:

```sh
python3 tools/community_map_conversion.py prepare \
  --source-map inputs/digsite/chillout_dig.map \
  --output build/chillout-review \
  --invader-bin build/reviewed-authoring-tools/build \
  --invader-manifest build/reviewed-authoring-tools/source-manifest.json \
  --stock-map assets/maps/bloodgulch.map \
  --origin digsite-authored-import

python3 tools/community_map_conversion.py models \
  --workspace build/chillout-review

python3 tools/community_map_conversion.py hud-overlay \
  --workspace build/chillout-review \
  --profile build/chillout-review/hud-profile.json \
  --converter build/reviewed-hud-tools/convert-hud \
  --converter-sha256 REVIEWED_CONVERTER_SHA256 \
  --output build/chillout-authored-hud

python3 tools/community_map_conversion.py compile \
  --workspace build/chillout-review \
  --scenario levels/dig/chillout/chillout_dig \
  --overlay build/chillout-authored-hud \
  --data build/chillout-review/data \
  --reviewed-build-manifest build/reviewed-fixed-compiler/manifest.json

python3 tools/community_map_conversion.py provenance \
  --workspace build/chillout-review \
  --overlay build/chillout-authored-hud
```

These stages are building blocks, not a turnkey fresh-clone Digsite conversion.
Retries create fresh build directories and preserve partial diagnostics. The
compile and provenance commands reject tool-generated HUD, PCM sound, duplicate
Chicago-layer, map-local weapon-alias and existing-mip overlays
that failed conversion or no longer match their recorded output hashes.
Managed marker-copy and Unicode-entry overlays use the same checks; their
scoped operations are described in the
[conversion helper guide](../tools/map_conversion/README.md).
Complete the reviewed codec, script and metadata steps between model conversion
and compilation. The separate reviewed
[PCM sound converter](../tools/map_conversion/convert_sounds.py) produces a
hashed overlay; other codec steps still require the reviewed helper/manual
recipe and its recorded hashes.
Create the HUD profile and HSC from a separately reviewed plan. Repeat `--overlay`
for additional derivative roots; order is significant, with the first root
winning. Omit `--reviewed-build-manifest` only when the unpatched compiler is
appropriate for the selected script source.

## Inputs and toolchain

Supply the original community source package or cache and record its SHA-256,
header identity, source release and scenario path. Cache versions identify
different layouts: the reviewed Digsite source is MCC CEA v13; Halo PC v7 and
Xbox v5 are also distinct. Renaming a cache or changing its version field is
not conversion.

Use original Xbox USA NTSC v5 build **`01.10.12.2276`** as the stock reference.
The existing H1PB importer extracts `bloodgulch.map` first, then `a10.map` and
`ui.map` to fill missing campaign/menu dependencies. A fully embedded custom
cache may not need stock tags to resolve its content, but the exact stock set
is still the reference for Xbox HUD logical dimensions and stock behavior.
Record stock input hashes; PAL or a different NTSC release is not an equivalent
conversion baseline. Engine build prerequisites are separate; see
[building](building.md).

The reviewed Invader revision is
`7d25a855f5ef9e4ab8407abf490b21f8780abf27`, with RIAT
`c1380cbfc708d89a3713af57b48d3f4368c34f8a`. Verify each helper binary against its
source manifest before execution. Run locally built, reviewed helpers; map
packages supply data, not trusted executable tools or build scripts.

The checked-in [content toolchain recipe](../tools/community-toolchain/README.md)
pins source/dependency inputs and produces a source manifest, but its packaged
consumer helpers are **only `invader-extract` and `invader-build`**. Authoring
also requires the reviewed `invader-convert`, `invader-refactor`, `invader-edit`,
`invader-dependency` and `invader-bludgeon` helpers. Both entry points use the
shared Invader wrapper, which verifies a manifest containing all seven helpers
even when a particular stage does not invoke them. A two-helper consumer
installation is not a complete authoring toolchain. Preserve the helper source changes, compiler/dependency versions,
binary hashes and licenses with the conversion record.

## Keep provenance useful

Track these distinctions per asset or rule, rather than classifying an entire
Digsite cache as historical or an entire community cache as stock:

| Category | Meaning and evidence |
|---|---|
| Stock Xbox / baseline equivalent | Bytes match the same tag path in the exact retail reference; record the stock hash and actual lookup root, without inferring where an author's identical copy originated |
| Imported authored content | Content supplied by the map/weapon author, with source release, path and hash |
| Documented recovered content | Historical recovered asset identified by source documentation; record that documentation and any later edits |
| Documented modern addition | Later reconstruction, new art, script or gameplay addition identified by its author/source |
| Unclassified provenance | The supplied asset is known, but its historical origin or subsequent authorship is not established |
| Compatibility conversion | A recorded format, reference, codec or presentation adaptation needed for the Xbox runtime |
| Proof-of-concept override | A deliberate local validation choice, such as granting an SMG at spawn; keep it separate from the authored release profile |

A filename such as `reticles_assault_rifle` or `99_mac` is not evidence of origin,
date, or behavior. Likewise, an unused retail asset does not prove that a complete
playable prototype weapon survives in stock data. Record missing models,
animations, HUDs or scripts rather than filling those gaps under a historical
claim. Distinguish an authored use of shared art from a conversion's fallback
substitution.

Comments in conversion code should name the imported layout assumption, the
Xbox requirement and the scope of the repair. For example, a comment explaining
an MCC HUD texel-density adjustment belongs beside the profile/converter rule.
It must not describe that adjustment as original Xbox engine behavior. Keep
retail source comments unchanged unless a separate stock fidelity correction
has evidence and review. Reports should record source/output hashes, helper and
profile hashes, resolved dependency roots, before/after fields, substitutions,
omitted behavior and validation status.

The `provenance` command inventories **all candidate tags** in lookup order. It
does not calculate scenario reachability or determine historical authorship.
Its coarse stock/import/conversion labels complement the finer source evidence
above. The stock label also covers byte-identical known stock tags at the same
path when the authored root wins lookup: it means baseline equivalence, not a
claim about the author's source. A cache-wide `--origin` label identifies the supplying package; it cannot
establish that every asset in that package is historical recovered content.

## Map-local conversion recipe

1. **Prepare a fresh workspace.** Inspect the source header and inventory; extract
   into copied tags and preserve the source cache. Check every extraction result.
   Resolve external bitmap/sound resources from the matching authorized source
   set before proceeding. The small resource-dependent Chillout cache was
   insufficient; the later fully embedded cache extracted all 2,482 tags.
2. **Record and resolve dependencies.** Keep original extracted inputs, conversion
   overlays, HSC/data, optional stock fallback, output maps and logs separate.
   Resolve each active tag using the actual compile-root order and record which
   root won. An overlay must be a derivative copy, never an in-place modification
   of the download, shared stock source or another map's tags.
3. **Convert supported layouts.** Convert Gearbox `gbxmodel` tags to Xbox `model`
   and refactor their references, including first-person weapon dependencies.
   Preserve nodes, meshes, markers, collision and materials. Codec/serialization
   conversions and narrowly checked metadata repairs need before/after evidence;
   they do not authorize changing weapon damage, rate of fire or placement.
4. **Review scripts and semantics.** Inventory source scripts, globals, references,
   script APIs, encounters and game-mode assumptions. Either compile the reviewed
   authored source for Xbox or replace it with an explicitly limited profile.
   Clear incompatible compiled script tables in the copied scenario and compile
   fresh HSC; do not carry MCC opcodes or stale syntax tables into v5. Keep custom
   placement and required devices. Unsupported mechanics require a recorded
   omission or an independently reviewed engine proposal.
5. **Build a reviewed HUD overlay.** Use expected source hashes and explicit
   per-placement/per-resource rules. Preserve artwork where supported and adapt
   its logical size; do not substitute stock art merely because it compiles.
   Keep a stock fallback candidate and an authored-HUD candidate distinct so
   screenshots and hashes identify the version being assessed.
6. **Compile Xbox NTSC v5.** Put reviewed overlay roots before authored tags, with
   stock fallback last. Compile the unique scenario against the selected data/HSC
   directory using `-g xbox-ntsc` and fresh script source (`-S data`). Verify the
   output cache identity, all resolved dependencies and final SHA-256.
7. **Validate and stage a separate candidate.** Use separate saves/settings and
   record exact map and executable hashes. Stage only a completed map; local
   conversion/staging does not publish it or install it for other players.

The native importer currently enforces a 512 MiB declared multiplayer cache bound and a
22 MiB tag arena. Check the generated map's declared/uncompressed size and tag
data size, not just its compressed disk size. Map resources stream from disk;
the file bound does not reserve 512 MiB for each loaded map. A larger memory budget or new
script/rendering API is an engine change, separate from this content recipe.

HUD profiles fail closed: every selected source tag has an expected SHA-256,
every field rule specifies the expected prior value and a reason, and every
bitmap resample names its reviewed factor and source. A changed source hash or
field value requires inspecting the new content and reviewing a new profile.
Do not turn a mismatch into an unconditional wildcard rule. Preserve the full
profile, converter source/binary hashes and source snapshots beside the overlay.
Start from the data-free [example profile](../tools/map_conversion/hud-profile.example.json)
and the [helper build/validation instructions](../tools/map_conversion/README.md).
The placeholder profile deliberately fails until reviewed inputs are supplied;
its example factors are not defaults for imported content.

## Chillout findings that need an explicit profile

### Script subset and compiler repair

The source scenario had 42 scripts, 68 globals and 46 script references. The
offline proof of concept replaces those with three scripts and three globals,
including a typed SMG object-definition reference. It retains a small native
subset for core placement/pro-mode sword filtering and adds a one-player SMG
startup profile for validation: 50 loaded rounds, 200 reserve rounds. That grant
is a proof-of-concept override, not the stock Xbox or original Digsite loadout.

The profile omits MCC flycam/host teleport, optional timers/navpoints, flashlight
taunts, blue-team armor selection and parameterized starting-grenade scripts.
Authored weapon tags remain custom content; loading/firing one weapon does not
certify all authored weapon logic, mode settings or network behavior.

The all-weapon diagnostics use separate scenario profiles, a muted owned
process and the native `cheat_deathless_player` switch to keep close-range HUD
checks alive. Record this fixture setting explicitly: its screenshots and ammo
changes establish presentation/action compatibility, not damage, survival or
weapon balance. Production scripts and the manual launcher must omit the cheat
and diagnostic input interposer. Explosive reload checks should also use clear
space and immediate alive/readied probes so a blast animation or respawn cannot
be mistaken for a completed reload.

The POC converted 76 Gearbox models and refactored 85 references in 55 tags. Its
asset conversion changed nine BC7 images to DXT5 and 77 Vorbis permutations to
Xbox ADPCM. A later playback audit found another 18 sound tags/permutations in
16-bit PCM. All were mono at 22,050 Hz, so these were encoded to Xbox ADPCM
without resampling. All 388 effective sound tags then met the native sound
manager's format/rate/channel gate. These are format/codec adaptations, with authored geometry and sound
content retained; the lossy codec conversions still need visual/audible review.
They are not replacement Xbox artwork or weapon balance changes. Imported
animation graphs were retained, and compiler warnings remain for animation
counts above retail block limits in grenade-launcher/speargun first-person and
cyborg graphs. Treat animation correctness as an outstanding gameplay audit,
not an established result of model conversion.

At the pinned Invader revision, `ScenarioScriptValueType::STARTING_PROFILE`
lacks a literal-name resolution case. Compilation can succeed with operand
`0xffff` instead of the named profile's index. The isolated repair uses the
existing `find_thing(scenario.player_starting_profile, n.string_data)` lookup
and writes `new_node.data.short_int`; the source change is preserved in
[`invader-starting-profile.patch`](../tools/map_conversion/invader-starting-profile.patch).
Rebuild into a separate compiler directory;
do not modify the trusted shared source or binary. A reviewed build manifest
must identify the patch, original revision, dependencies and resulting binary
hash. Then inspect the compiled operand: the Chillout test profile is index 3,
so its starting-profile node must resolve to 3. A successful compiler exit alone
does not verify this repair.

To construct the repaired compiler, first prepare a **separate** reviewed
Invader checkout and configured build tree with the same pinned revision,
RIAT and host-specific dependencies as the authoring toolchain. The existing
toolchain recipe describes those inputs; configure its dependency/build paths
for the new source tree. Copy writable source/build files independently, never
hard-link them to the trusted originals. Read-only dependency reuse is allowed.
There is no automatic generic compiler-rebuild wrapper in this conversion tool.
From the repository root, with that separate tree already configured:

```sh
conversion_compiler_source=build/reviewed-fixed-compiler/invader
git -C "$conversion_compiler_source" rev-parse HEAD
git -C "$conversion_compiler_source" apply --check \
  "$PWD/tools/map_conversion/invader-starting-profile.patch"
git -C "$conversion_compiler_source" apply \
  "$PWD/tools/map_conversion/invader-starting-profile.patch"
cmake --build build/reviewed-fixed-compiler/build --target invader-build
shasum -a 256 tools/map_conversion/invader-starting-profile.patch \
  build/reviewed-fixed-compiler/build/invader-build
```

Confirm the printed source revision matches the pin before applying the patch.
Save `manifest.json` with the tool's required fields `original_invader_commit`,
`binary` (the selected compiled binary path) and `binary_sha256`. Also record
the patch SHA-256, source/RIAT revisions and source changes, compiler/SDK versions,
dependency hashes and exact configure/build commands. Verify the original shared
source and binary hashes remain unchanged. Pass this manifest through
`--reviewed-build-manifest`; it authenticates the selected derivative compiler,
but does not construct or independently certify its source build.

Native console tag literals resolve through the scenario's script-reference
table. A custom weapon referenced only by a starting profile may therefore give
a misleading console query. Use a typed HSC `object_definition` global or inspect
the actual tag/inventory identity before deciding the spawn grant failed.

Pickup fixtures need verified inventory too. The native equipment reset can
retain the currently held weapon (`unit_delete_all_weapons` skips it), so a
reset profile alone does not prove the intended loadout. Switch to a known
control weapon, grant the control profiles, and verify both carried weapons
and the ground target before assessing a swap prompt. Keep these test fixtures
in a diagnostic scenario rather than changing authored production placements.

### Authored HUD conversion rules

The native Xbox HUD derives sprite size from bitmap dimensions and normalized
sprite bounds. MCC bitmap `half_hud_scale` metadata is not applied by this native
path. This does **not** imply a universal halve/quarter rule: source dimensions,
sprite layout, placement scale and intended stock logical size must be measured.
The reusable [HUD converter](../tools/map_conversion/convert_hud.cpp) takes a
reviewed map profile; a profile is not a new engine default.

| Reviewed element | Data-only approach |
|---|---|
| Ordinary aim reticle, static ammo art or ammo meter | Adjust placement width/height scales while retaining the high-resolution pixels and authored sequence selection |
| Pickup message icon | No per-icon draw scale; resample/repack its authored atlas and preserve sequence/frame identity, UVs and message advance/offset semantics |
| Counter digits | Native number rendering ignores placement width/height scales; resize the glyph atlas and separately set logical digit advance metrics |
| Damage arrow | No per-arrow scale; resample its dedicated authored atlas |
| Screen-effect scope mask | Review physical dimensions and native centered pixel sampling separately from ordinary sprites; keep full viewport coverage |
| Zoom label, scope sprite layers and sniper angle ticks | Review each image's dimensions, placement scale and coordinate offsets separately |

Anchor offsets need their own rules as well. The native point calculation uses
the common HUD scale of 1; it does not automatically halve MCC offsets. Reviewed
shared declarations often use twice their stock offsets (for example, master
rounds `58,6` versus `29,3`). Halve those only after comparing the corresponding
layout. Nonuniform changes, such as motion-sensor placement, need a specific
layout decision rather than the bitmap's resample factor.

Chillout's plasma charge panel needed its own offset review after the shared
grenade layout was normalized. The master plasma background and outline
`24,2` become `12,1`, its charge number `52,6` becomes `26,3`, and its separate
charge-icon overlay `102,4` becomes `51,2`. The sword's age background and
outline also change `24,2` to `12,1`. These six vectors match the corresponding
stock logical placements and separate the authored panel ink from both selected
grenade icons. The native number renderer does not append that charge icon; it
has its own bitmap placement. The imported sword uses the scorpion-cannon
weapon alias and has no numeric charge element, so do not add a counter while
repairing its background. Preserve charge/heat semantics, bitmap pixels,
number metrics, and the independently reviewed reticle scales.

The later ammo-row audit compares matching bitmap, sequence, state, view and
anchor declarations against the retail Xbox tags. Master plasma's primary
heat row `8,42` becomes `4,21`; the SMG primary ammo row `-2,40` becomes
`-1,20`; Excavator's primary row Y=42 becomes Y=21. Matching retail AR alpha
uses Y=20 rather than blindly rounding 42/2, and shotgun uses 21 rather than
44/2. These are placement changes, independent of the artwork scale. Bespoke
odd-Y custom rows and nonuniform split heat positions remain separate review
items.

Chillout's reported zoom errors require two different calculations. The
screen-effect masks are twice the retail dimensions: the pistol full mask is
512×512 versus 256×256, with corresponding half-sized split masks. The native
mask UV calculation samples centered pixels at 1:1, so physically resampling
these masks by two halves the aperture while the drawn quad still covers the
viewport. The Beam Rifle's custom trapezoid uses this same path. Its measured
aperture changes from 435×413 to 217×206 pixels, with raster rounding. Preserve
the authored shape, outside coverage and image ordering.

The SMG's `2x` is an ordinary sprite from `hud_reticles_scope`, whose atlas is
256 pixels wide versus the retail 64. Its authored sprite is 107×72 logical
pixels at placement scale 1; width and height scale 0.25 produce 26.75×18.
Its anchor offset uses a separate coordinate rule, 210→105. The supplied
lettering/UV packing differs from retail, so this is not a claim of identical
retail glyph dimensions. Camera magnification and weapon zoom levels remain
authored. Full and split scope layers require their own runtime acceptance.

Sniper and Bolt Action also need a separate anchor correction. The Xbox static
weapon HUD path uses the root anchor and ignores the MCC element's individual
center anchor. Their supplied blue angle-tick layers use an 8×256 backing image
whose pixels already match stock; resizing that image would be incorrect.
Restore the measured stock placement scale 1 and top-left offsets `92,85` and
`445,85`. Preserve the separate black scope layers and multitexture functions.
This correction removes the full-height blue strip outside the scope; it does
not change camera magnification or the native zoom caption calculation.

The full audit uncovered a Battle Rifle renderer stall as well. Its ammo-display
Chicago shader has an extra layer identical to its parent after resolving two
byte-identical bitmap tags. The preserved Xbox renderer's extra-layer loop does
not advance its index, so this input hangs when rendered. The separate reviewed
[Chicago-layer converter](../tools/map_conversion/convert_chicago_layers.py)
removes only a proven duplicate layer into a fresh hashed overlay. It rejects
changed shader parameters, different bitmap contents and nested child layers;
the engine and the weapon's 24-round counter remain unchanged. Removing a
duplicate multiplicative pass may affect brightness, so inspect the actual
counter and firing behavior rather than claiming identical MCC rendering.

Chillout's Flamethrower also collides with a stock Xbox multiplayer rule:
the engine remaps the reserved Flamethrower entry in globals to the Rocket
Launcher. Preserve that stock rule and globals tag. An explicit community
[weapon-alias conversion](../tools/map_conversion/convert_weapon_alias.py)
copies the supplied weapon bytes to a distinct map-local definition and
retargets the single authored Fiesta item-collection reference. The original
reserved definition remains present. Record both identities and test the alias
as the authored Flamethrower; the extra cached definition is not a new weapon
design. Audit scenario, item-collection and custom-script grants before deciding
which references to redirect on another map.

The Missile Launcher's supplied primary charge trigger has magazine `NONE`,
charges for 1.2 seconds and consumes zero rounds. The Xbox fully charged state
unconditionally accesses that magazine while the trigger remains held, which
asserts with this input. A separate reviewed numeric overlay binds only that
primary trigger to its existing magazine 0. The secondary trigger still emits
the projectile and consumes one round on release; charge time and all other
fields remain authored. This is a community compatibility departure, including
the native reload/ammunition gating introduced by a valid magazine binding.
Accept it only after actual sustained-charge, release, reload and empty-magazine
checks. Keep its profile and acceptance separate from presentation-only edits.

Compilation limits do not establish runtime texture-cache fit. The preserved
Xbox cache has 1,408 pages of 16 KiB (22 MiB); textures used in the current frame
are locked. Chillout's Missile first-person `s_msllauncher` texture requested
342 pages while as many as 1,265 other pages were locked. The native failure dump
names that texture; neither the explosion texture nor total system RAM is the
allocation being measured. Audit both `YOU GOT STABBED` and `SOUND CACHE BLOWN`
log phrases as resource failures, even if the process exits successfully. Their
embedded batch-file instructions are diagnostic text, not actions to execute.

The separate reviewed existing-mip converter selects the supplied 1024-pixel
level of this 2048-pixel DXT5 image, retaining that level and every lower
compressed mip byte exactly. It neither resamples nor recompresses the image.
This is an explicit loss of its highest-detail level, reducing the request from
342 to 86 pages and preserving the native cache limit. Require exact metadata
preservation outside the scoped mip fields, immutable original inputs, and a
fresh sustained-fire run with no cache-warning phrases. Do not apply this rule
to other textures without their own allocation evidence and reviewed profile.

Two-peer multiplayer testing exposed the separate `msllauncher` first-person
bitmap at a postgame transition. It requested 342 pages while 1,137 pages were
locked, leaving only 271 pages available. Its complete authored mip chain has
the same reviewed layout, so a separate profile selects its existing 1024-pixel
mip as well: 5,592,448 compiled bytes become 1,398,144, saving 4 MiB. All
59 first-person bitmap images were inventoried; no other image requires this
treatment from that failure dump. The resulting cache passed natural match end
and rematch in the five objective presets listed above without targeted cache
or sound warnings. Those checks do not establish every weapon's network damage
or audible sound quality.

### Native multiplayer text

The imported 191-entry multiplayer text list supplies entries beyond the stock
Xbox list, bypassing the native fallback strings. Its score prompt contains a
formatter placeholder that the Xbox call site copies without formatting, and
its postgame prompts name PC keyboard controls. A reviewed
[Unicode-entry overlay](../tools/map_conversion/convert_unicode_strings.py)
restores only entries 72, 73 and 100 to the verified native Xbox wording.
The other 188 entries and separate 89-entry custom pickup table stay unchanged.
Record exact before/after text and the traced native call sites in the private
profile; another map needs its own entry/count/hash review.

The full Chillout weapon audit also finds five additional primary ammo families
still using scale 1, plus Battle Rifle at its authored relative scale 0.5.
Digsite's 512×136 clip sprites become 128×34 at scale 0.25, matching the accepted
SMG and stock AR row dimensions. Battle Rifle uses the same DW2 ammo atlas as
Excavator; its scale becomes 0.125, preserving the authored half-relative size.
Magnum's six-round sprite is
305×130 before placement scaling and becomes 76.25×32.5 at 0.25, with its
separate alpha/meter offsets normalized to `5,21` and `4,20`. Keep the original
sprites, ammo channel, selected sequence and meter state semantics.

Reticle presentation requires a separate decision from the ammo-row correction.
The supplied Magnum circle is 45 pixels at authored scale 1.25, producing a
56.25-pixel draw size. Its bitmap and overlays have no half/high-resolution
flags proving an automatic density correction. At the user's request, a
separate presentation overlay halves all three centered reticle layers to
0.625: the circle becomes 28.125 pixels and the center art becomes 11.25 pixels.
The stock Xbox pistol reference has a 28-pixel sprite quad with 25 pixels of
visible art, so this is a stock-style adjustment rather than exact art parity
or a claim about the author's original intent. Preserve bitmap bytes, offsets,
colors, animation states and weapon aim parameters; verify the actual native
reticle bounds and firing/reload HUD before accepting the new overlay. Do not
apply the ammo row's quarter factor to this unrelated reticle artwork.

Chaingun's custom heat meter begins at scale 1.5, so its reviewed scale is
0.375; its heat title uses 0.25. Their offsets are reviewed separately. The
grenade launcher's secondary header deliberately retains X=164: halving it
to 82 would overlap the grenade panel near X=84. These custom layouts need
per-element decisions. Custom H3 reticles also have different visible ink
within their full quads; a large atlas or quad alone does not establish a
reticle sizing error or justify resizing the entire atlas.

Chillout's radar is one measured exception: its full-screen background and
foreground offsets `20,20` become `0,0`, while the independent sweeper/blip
center `104,103` becomes `41,41`. The split-screen center `63,61` becomes
`31,31`; its background/foreground are already `0,0`. Scaled authored artwork
matches the stock logical extents (128 by 128 full, 64 by 64 split), so this
repair changes only those four offset vectors. Sensor range, sensor scale,
pixels and placement scales remain authored. Split-screen rendering still
requires its own runtime acceptance check.

Concrete Chillout reference rules are atlas-specific: original counter glyphs
72×48 become stock logical 18×12 through an atlas quarter-resample, while counter
advance metrics are halved. Original damage arrows are exactly twice the stock
logical dimensions, so their 512×256 atlas becomes 256×128. Normalized sprite
bounds alone must not be shrunk to simulate scaling: that crops the image.

The original SMG HUD already uses the shared Digsite
`reticles_assault_rifle` atlas, also referenced by other authored weapons. Its
child HUD selects sequence 5 from shared Digsite ammo alpha/meter atlases; the
Digsite assault-rifle selector uses those same atlases at sequence 0. Our early
fallback deliberately substituted the stock Xbox AR HUD layout and shared stock
bitmaps. Restoring the authored graph reverses that substitution and preserves
the author's shared-resource choices; it does not imply unique SMG reticle art.
Do not apply this fallback to future weapon sets automatically.

## Reproduction and acceptance checklist

- Pin the repository revision, profile/converter hashes, source release/cache
  hash, exact stock hashes and all helper hashes. Preserve compiler patches and
  complete commands in the manifest; the original sources remain unchanged.
- Check extraction failures, missing resources, reference conversions, active
  dependency precedence and stock substitutions. Reject unexpected input hashes
  or compiler repairs rather than broadening a rule silently.
- Parse the compiled cache: Xbox v5/NTSC identity, unique name, multiplayer type,
  declared size/tag arena bounds, script/global/reference counts, critical script
  operands and weapon/HUD dependency identities. Record warnings by tag.
- Inspect authored HUD at stock logical size, including counters, damage arrows,
  pickup messages, ammo depletion/reload, zoom and split-screen where supported.
  A correct viewmodel does not prove correct HUD or world pickup geometry.
- Test spawns, collision, devices, lighting, sounds, custom weapon inventory,
  firing/reload/melee/grenades, death/respawn, transitions and longer sessions.
  Verify custom weapon identity through a valid reference, not appearance alone.
- Review every advertised game mode and multiplayer behavior separately. Short
  offline smoke tests, successful compilation and same-machine network probes
  do not establish original Xbox parity or cross-platform/NAT acceptance.

For a full weapon HUD pass, enumerate `.weapon` definitions from the compiled
cache, then resolve their HUD parent chains and bitmap/sequence selections in
the same lookup order used by compilation. Include objective items and inspect
vehicle-named aliases: Chillout's Scorpion cannon is the handheld Sword,
Warthog gun is the Concussion Rifle, and Banshee gun is the Pro Plasma Pistol.
Use canonical authored clip/reserve limits in diagnostic starting profiles.
Capture each held weapon with grenades, ammo consumption/reload or its charge
state, and every available zoom level. Use short numbered typed globals for
console checks; native expressions are limited to 127 ASCII bytes. Keep a
per-definition result with screenshots, input acknowledgements and warnings.
Record nonapplicable actions for melee/objective items and distinguish tested
HUD/playback behavior from balance, multiplayer, split-screen and audible
quality. A shared atlas rule does not replace testing its weapon-specific
placement, sequence and state choices.

For 15–20 future maps, share the toolchain and proven model/codec transformations,
then prepare one immutable input/workspace and one review profile per map or
weapon cohort. Reuse a HUD or script rule only when its expected hashes/layouts
and intended semantics match. Build a small representative cohort first, keep
per-map failures independent, and track validation by map, weapon and mode. A
new weapon set is a new authored-content review even when it shares a working
format conversion. Ship only completed reviewed maps; keep incomplete behavior
visible in their manifests instead of labeling the whole set accepted.
