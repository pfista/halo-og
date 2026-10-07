# Offline map conversion pipeline

[`tools/convert_maps.py`](../tools/convert_maps.py) inventories a directory of Halo
maps, applies a selected conversion profile, and packages successful Xbox NTSC v5
community caches with separate menu metadata, preview assets and builder reports.
Conversion runs outside the game. The command does not install, publish or launch
maps, update the download catalog, or change game rules.

A recognized container is not necessarily convertible. A compiled and packaged
cache is not necessarily playable. Every output starts with
`gameplay_validation: "pending"`; collision, weapons, scripts, resource budgets,
game modes and multiplayer still need their own acceptance checks. See the
[conversion guide](community-map-conversion.md) for the established asset-specific
findings, including Chillout Digsite.

## Inspect a directory

Run from the repository root and select a new output directory outside the source
tree. Existing destinations are never replaced.

```sh
python3 tools/convert_maps.py /path/to/source/maps \
  --inspect \
  --output build/map-pipeline/inventory-new
```

Add `--recursive` to scan subdirectories. The scanner orders inputs
deterministically, includes malformed `.map` files in the inventory, and does not
follow map-file or directory symlinks. Other file extensions are ignored.

The inventory recognizes these layouts:

| Version or container | Meaning | Current conversion boundary |
| --- | --- | --- |
| Xbox v5 | Xbox cache layout | Compatible NTSC 2276 multiplayer community caches can be staged directly. Selected script, asset, presentation, original weapon or authored placement policies instead extract and rebuild them. |
| PC demo v6 | Demo-specific header offsets | Recognized and routed to the authored-content backend; successful extraction and Xbox compilation remain required. |
| Halo PC v7 | PC cache layout | Authored-content conversion or the exact reviewed PB3 recipe. |
| Custom Edition v609 | CE cache layout | Authored-content conversion; matching external resources may be required. |
| MCC CEA v13 | MCC cache layout | Authored-content conversion attempt; unsupported scripts, codecs and layouts remain blockers. |
| Bitmap, sound or localization resource maps | Resource table rather than a playable level | Inventoried as resources; not compiled as standalone levels. |

Header signatures, scenario type, bounded strings, declared sizes and tag ranges
are checked before conversion. Resource tables also receive bounds checks. Unknown
versions produce structured diagnostics instead of version-field patches.
The current output target is **multiplayer only**. Campaign and UI caches require
a separately supported target; recognizing their headers does not enable their
conversion.

## Prepare the authoring helpers

Non-v5 conversion requires reviewed, locally built native Invader helpers and
their source manifest. The existing toolchain builder now has an explicit
authoring selection:

```sh
python3 tools/community_toolchain.py \
  --toolset authoring \
  --output build/map-tools/authoring-new
```

This builds `invader-extract`, `invader-dependency`, `invader-convert`,
`invader-refactor`, `invader-edit`, `invader-bludgeon` and `invader-build`. It uses
the same pinned Invader revision `7d25a855f5ef9e4ab8407abf490b21f8780abf27`,
RIAT revision `c1380cbfc708d89a3713af57b48d3f4368c34f8a`, dependency archives
and Cargo lockfile as the established recipe. See
[the toolchain prerequisites](../tools/community-toolchain/README.md).

The authoring selection also applies the pinned
[`invader-starting-profile.patch`](../tools/map_conversion/invader-starting-profile.patch).
It fixes compilation of named starting-profile operands, a concrete cause of
Digsite equipment-script failures. The manifest records the patch SHA-256 and
the compiler source hashes before and after the repair; the delivered source
archive includes the patch. Generic conversions containing scripts, globals or embedded source files
require this recorded repair, including scripts introduced by scenario overlays.
An older seven-helper manifest can still handle genuinely unscripted inputs and
the exact reviewed PB3 cleanup route. A reviewed script omission also produces
an unscripted working scenario before this compiler gate. Compiler startup and map gameplay remain
separate checks.

The default `--toolset desktop` still builds only extraction and build helpers
for the separate archived consumer prototype. It is insufficient for authoring.
Neither selection automatically bundles helpers into the application or changes
release trust pins. A source-toolchain build may download pinned sources;
conversion itself reads local maps, resources and tools without downloading them.
Map packages supply data, not executable helpers or build scripts.

## Convert authored maps

```sh
python3 tools/convert_maps.py /path/to/source/maps \
  --profile authored-xbox-v5 \
  --invader-bin build/map-tools/authoring-new/build \
  --invader-manifest build/map-tools/authoring-new/source-manifest.json \
  --stock-maps /path/to/original-xbox-ntsc/maps \
  --resources /path/to/matching-source/resources \
  --metadata-dir /path/to/reviewed-menu-metadata \
  --output build/map-pipeline/authored-new
```

The stock, resource and metadata arguments are optional. Omitting `--resources`
uses each source cache's directory. Supplied `bitmaps.map`, `sounds.map` and
`loc.map` inputs are hashed and remain unchanged. Missing resources cannot be
reconstructed by renaming a file or substituting an unrelated resource set.

The default [`authored-xbox-v5` profile](../tools/map_conversion/profiles/authored-xbox-v5.json)
preserves authored content and recovered HSC. Its dependency order is reviewed
overlays first, authored or converted tags second, and stock fallback last. Stock
fallback, when supplied, extracts `bloodgulch.map`, `a10.map` and `ui.map` from the
exact Xbox NTSC `01.10.12.2276` baseline.

The backend extracts immutable originals into a private workspace, copies working
tags, resolves a scenario and distinct output identity, converts Gearbox models
and their references, adapts supported extended Chicago shaders, checks selected
overlay manifests, and compiles `xbox-ntsc`. Recovered script source is compiled
with `-S tags`; incompatible source APIs are reported. It then checks output
identity and capacities, rechecks immutable inputs, and records the reachable tag
dependencies and their winning lookup roots. Unreachable extracted tags are
reported as omissions; this does not authorize deleting reachable gameplay assets.

The default profile preserves sound codecs, bitmap codecs and dimensions.
Legacy Chillout's reviewed weapon-alias and other content decisions remain separate
asset-specific recipes. A required unsupported dependency stops that map. The generic `none` script
policy rejects maps containing scripts, globals or embedded source files rather than deleting them.

## Convert multiplayer maps using engine-native rules

The [`og-multiplayer-v5` profile](../tools/map_conversion/profiles/og-multiplayer-v5.json)
is a general conversion policy for any recognized multiplayer cache. It accepts
v5, demo v6, PC v7, Custom Edition v609 and MCC v13 inputs. It has no map-name,
source-hash or scenario-hash whitelist. Original Xbox multiplayer implements its
core rules in engine code; selecting this profile deliberately excludes features
implemented by authored scenario scripts. Keep the default `authored-xbox-v5`
profile when those scripted features are required.

```sh
python3 tools/convert_maps.py /path/to/source/maps \
  --profile og-multiplayer-v5 \
  --invader-bin /path/to/reviewed/authoring/helpers \
  --invader-manifest /path/to/reviewed/source-manifest.json \
  --asset-manifest build/map-asset-tools/new/asset-tools.json \
  --output build/map-pipeline/og-multiplayer-new
```

The `omit` policy clears the working scenario's scripts, globals,
embedded source files and compiled script-operand references. It records their original counts, the policy reason,
the actual source hash and scenario hashes before and after the change, including when a later asset
blocks compilation. Original caches and extracted source tags remain intact.
Hashes provide audit evidence rather than eligibility checks. Existing v5 inputs
are rebuilt when omission is selected, so a copy cannot silently skip the policy.
Invader regenerates the compiled script syntax, string and reference tables from
the now-empty source. Scenario-shadowing overlays and unresolved child scenarios
are currently rejected because they can introduce script source after omission;
compiled cache extraction normally provides an already-flattened scenario.

This profile preserves authored asset lookup order and does not remove scenery,
weapons or other reachable dependencies. Its format-based asset stages operate
on reachable scenario dependencies and the engine's implicit globals dependencies,
using the winning tag root. Unreferenced extracted assets and shadowed lower-priority
versions are excluded. Each conversion uses a fresh overlay, verifies original
and snapshot hashes, reparses the resulting tag, and records per-tag measurements.

The profile selects `presentation_policy: native-xbox`, including original shared
HUD digits for every supported source format. MCC v13 inputs also receive HUD
density conversion and native shell assets; the default profile's presentation
policy is `preserve`. The MCC stage supplies the canonical stock
Xbox pause widgets, actions, fonts and frame assets through the implicit
multiplayer UI collection. This makes the assets needed by Halo OG's regular
pause menu resident. It changes only multiplayer text entries 72, 73 and 100 to
the native button/score prompts, preserving all other authored strings.

The native Xbox presentation policy also selects the original shared HUDNumber
definition and its exact digit bitmap dependency tree from the verified stock
cache. Ammo and grenade numbers use this global provider independently of each
weapon's HUD. The converter copies it into a private stock HUD namespace and
changes only the active Globals HUD-digit reference, preserving all other fields
and authored shared artwork. Original glyph layout and pixel spacing stay paired;
these native tags bypass MCC density scaling and qualify for existing Up-res
artwork through the same dimension and pixel-checksum checks. The report records
the original provider, donor, reference change and copied asset hashes. The
`preserve` presentation policy retains the authored provider.

The OG profile also selects `weapon_policy: bungie-originals`. Recognized weapons
with complete original player assets use the original Xbox bundle, including
gameplay definitions, models, animations, sounds, projectiles, effects and HUD assets. Identity uses
model reference, weapon type and weapon label, with exact-path preference and
unique canonical matching for renamed variants. Modified stock gun parameters
are deliberately replaced by original parameters. Canonical dependencies use a
private namespace so their native textures cannot replace shared MCC level or
unit HUD textures. With Halo OG's Up-res setting enabled, the runtime recognizes
these private original HUD copies and the earlier stock-HUD namespace. It checks
the full original path, bitmap index, dimensions and original pixel checksum
before using the existing Up-res artwork; logical HUD sizes stay unchanged.
Custom or modified pixels retain their authored artwork. The original Xbox
weapon registry replaces only the authored
Globals weapon-list field; other Globals fields keep their source decisions.
Verified original campaign/NPC registry entries can follow the unchanged native
registry prefix, preserving its weapon enum indices. Unidentified unused registry
entries are omitted with their identity diagnostics.
This also removes unused MCC-only weapon registry dependencies.

Weapons present in the original Xbox references, including cut assets still in
those caches, have recorded canonical provenance. An unknown weapon reachable
from the scenario produces an actionable `needs_profile` report; a familiar
filename alone does not prove a Bungie asset. A cut weapon absent from those
references needs reviewed original-asset provenance before it can be enabled.
The default `authored-xbox-v5` profile retains `weapon_policy: preserve`.

The canonical library uses original `bloodgulch`, `a10` and `ui` caches, plus
`c40` when available for campaign weapons. Each input must be Xbox NTSC v5,
build `01.10.12.2276`, and its checksum is recorded. Multiplayer assets retain
extraction priority. In the original cache inventory, Flamethrower and Gravity
Rifle are the two cut weapon entries. Energy Sword, Fuel Rod, Hunter Fuel Rod
and Sentinel weapon definitions shipped as NPC weapons. Gravity Rifle lacks
first-person assets and a HUD. Completed implementations of original NPC or
unfinished weapons may be retained when their original identity is verified;
the report distinguishes these authored completions from canonical original
asset copies and records their dependencies. At least one originally missing
first-person model, animation or HUD reference must be supplied to classify an
authored implementation as a completion. Partial completions retain those assets
and report the remaining fields for the map builder. Every reachable weapon in
their dependency closure must have an original ancestor. Their MCC HUDs still
pass through the normal format conversion. Unknown weapon identities remain blockers.

Version 1.10.0 also selects `weapon_placement_policy: authored-default`. This is
an explicit community-map exception to the original Xbox rule that replaces an
authored Flamethrower pickup with a Rocket Launcher. It requires
`weapon_policy: bungie-originals`, `presentation_policy: native-xbox`,
authored-first dependencies and verified canonical stock inputs. The converter
audits authored netgame item collections, custom starting equipment and direct
scenario weapon placements,
then checks their final identities against the native Globals registry. Source
and compiled-cache audits record the placement, original identity and effective
native replacement. Source caches and extracted originals remain unchanged.

Only an audited Flamethrower replacement conflict enables the capability. The
converter creates `__native_policy/authored_weapon_placements_v1.string_list`
with exactly one ASCII, NUL-terminated string,
`halo-og:authored-weapon-placements:v1`, and adds it to the Xbox implicit
`ui/shell/multiplayer.ui_widget_collection`. Halo OG validates that marker before
retaining the authored Flamethrower in Normal, No Grenades, Uncut and All weapon
sets. Other weapon restrictions still use the original rules. The canonical
weapon registry and its enum indices remain intact. Maps without a valid marker,
including unchanged retail caches, retain original Xbox behavior.

The default `weapon_placement_policy: engine-native` retains the original remap;
omitting this field has the same meaning. The default authored profile and the
reviewed PB3 profile retain that policy. Selecting `authored-default` rebuilds
an existing v5 input so the placement audit and required marker cannot be skipped
by staging the source cache unchanged. The reports distinguish the explicit
community capability from canonical original weapon content; runtime and gameplay
validation remain separate from conversion success.

MCC uses a 960p HUD canvas, twice the Xbox canvas. Its bitmap `half_hud_scale`
flag applies an additional half scale; see the [pinned restoration author
documentation](https://github.com/Aerocatia/halopc-restored/blob/2ed57083cdab6d625789c551faf218a9ef50e9c8/README.md#L38-L41).
The HUD stage converts this presentation to native coordinates and scales while
preserving authored artwork and relative element sizes. Stock sequence/frame
geometry provides additional checks, rather than requiring custom art to match
stock sprite shapes. Number glyphs and HUDGlobals images drawn at fixed physical
size receive a checked bitmap resize; numeric advances are converted separately.
Before a physical image resize, every reachable direct consumer must be one of
the traced fixed-size HUDNumber/HUDGlobals fields. MCC weapon elements with
independent native anchors are separated into HUD parent nodes, preserving
element draw order. Original parent chains are preserved; generated chains must
stay below the native 16-definition bound. Unsupported extended anchors, shared images or image layouts produce precise
`needs_profile` diagnostics. Half-pixel integer coordinates use a nearby canonical
coordinate where available, otherwise nearest-integer rounding with a recorded
quantization warning. The source tags remain unchanged.

The HUD report records per-field before/after values, density evidence, bitmap
consumer proofs, output hashes and pending visual validation. This stage runs
after the format codec stages and applies once based on the original cache
version; converting its v5 output again does not rescale the HUD.

The profile's asset decisions are:

| Setting | Conversion | Boundary |
| --- | --- | --- |
| `extensions: omit-mcc` | Omits proved unsupported MCC-only target fields | Currently only `HUDGlobals.anniversary_hud_remaps`, which occupies unused native HUDGlobals bytes. Other HUD metadata remains exact. Dependency selection is recomputed; textures referenced elsewhere remain included. |
| `audio: xbox-adpcm` | Ogg Vorbis and big-endian 16-bit PCM to Xbox ADPCM | Keeps authored rate, channels, pitch, gain and playback fields. Mono must be 22,050 Hz; stereo may be 22,050 or 44,100 Hz. Unsupported codecs or payload/metadata mismatches are reported. Existing ADPCM is preserved. |
| `bitmaps: bc7-to-dxt5` | BC7 surfaces to DXT5 | Keeps dimensions, faces, mips, sequences and other metadata. Records decoded pixel error; compression is lossy. Other images in the tag remain byte-identical. |
| `dimensions: existing-mip` | Selects an existing authored lower mip that fits native limits | Does not resample, generate mips or recompress. Retained bytes are exact. Limits are 2048 for 2D textures, 512 for cubemaps and 256 for volume textures. HUD/sprite/interface tags or flags, invalid layouts and insufficient mips require separate decisions. Nonzero registration points require a proved shader-only usage graph. |
| `packing: lossless` | Chooses a smaller native uncompressed pixel representation | Every channel must remain exact through Invader, native GPU and software bitmap decoders across all mips, faces and depth slices. Dimensions and metadata remain unchanged. Compressed images and bump palettes are preserved. |

Audio records converted permutations, original frames, ADPCM block padding
(at most 63 frames), encoded size and waveform error. Bitmap records include
source formats and per-image layout; mip records include removed levels and
before/after dimensions. These are static measurements; visual and audible
acceptance remain pending.

The mip stage parses every reachable tag in its winning lookup root to classify
direct bitmap consumers. Only `shader_model` and `shader_environment` consumers
currently prove that an image registration point is unused; any HUD/UI or other
consumer blocks that exemption. A missing or unparseable required tag invalidates
the entire proof. The registration point itself remains unchanged.

The extension stage runs first. Pinned Invader currently emits Anniversary HUD
remaps and their source/target bitmap dependencies into Xbox caches even though
its definition marks the array MCC-only with legacy maximum zero. Halo OG's
native HUDGlobals structure treats this region as unused. The helper clears only
that array in copied effective HUDGlobals tags, restores it after reparsing to
prove all other metadata unchanged, and records the field counts and source
evidence. This policy does not discard arbitrary fields based on compiler warnings.

Lossless packing separately compares the channel values produced by all three
decoders because A8 RGB, stored X8 alpha and some 16-bit expansion values differ
between them. An exact Invader roundtrip alone is insufficient. This stage does
not add lossy compression or alter HUD meter channels to meet a memory budget.

Build these additional source-bound helpers against a reviewed local toolchain:

```sh
python3 tools/build_map_asset_tools.py \
  --toolchain /path/to/reviewed/toolchain \
  --invader-manifest /path/to/reviewed/toolchain/source-manifest.json \
  --tools all \
  --output build/map-asset-tools/new
```

The builder records source, library and generated-header hashes, exact commands,
and helper hashes in `asset-tools.json`. It reuses the local pinned libraries;
it does not claim to rebuild Invader or download dependencies. `--tools audio`,
`bitmaps`, `mips`, `packing`, `extensions` or `hud` selects a single helper. The converter checks the helper's
manifest and current source hash before execution; rebuild after editing a helper.

Recognizing every supported container does not mean every authored feature has
an Xbox equivalent: resource budgets, HUD placement and tag layouts can still
require further conversion decisions.
Campaign and UI targets retain their separate unsupported-target diagnostics.

## Use the reviewed PB3 collection recipe

```sh
python3 tools/convert_maps.py /path/to/H1PB-Beta-3/maps \
  --profile jukkis-pb3 \
  --source-tags /path/to/H1PB-Beta-3/tags \
  --stock-maps /path/to/original-xbox-ntsc/maps \
  --invader-bin build/map-tools/authoring-new/build \
  --invader-manifest build/map-tools/authoring-new/source-manifest.json \
  --output build/map-pipeline/pb3-new
```

The [`jukkis-pb3` profile](../tools/map_conversion/profiles/jukkis-pb3.json)
selects v7 input and loads the checked-in scenarios, hashes, aliases and optional
script decisions from [`port/maps/jukkis-beta3.json`](../port/maps/jukkis-beta3.json).
It requires the exact source tags and stock baseline. `--source-tags` is explicit;
when omitted, the batch also checks `tags/` in the input directory and its parent.

This path reuses the existing stock-first PB3 importer. It removes only its
reviewed optional training/timer scripts, retains its scoped training-object
cleanup, and records compatibility repairs. It is not the policy for a newly
authored custom weapon set. Changes to the scenario hashes, cleanup lists or
script-removal decisions require a new reviewed recipe. Extra overlays are not
accepted by this existing PB3 recipe.

For a new profile, pass `--profile /path/to/reviewed-profile.json`. A profile has
an explicit ID/version, supported cache formats, dependency/script, weapon,
weapon-placement and presentation policies,
target capacities, optional exact source/scenario selections and ordered overlay
directories. Its canonical JSON fingerprint is recorded independently of local
operating paths. Overlay paths resolve relative to the profile file; expected
input hashes and conversion manifests must match. Selecting `reviewed` scripts
or `stock-first` dependencies does not create a new removal recipe automatically.

## Supply names, authorship and menu previews

Place one `<output-id>.json` file in `--metadata-dir`. Paths inside its `preview`
entry resolve from that directory, not from the map or output directory.
An editorial file overrides profile metadata. The following is a **fictional
schema example**, not information about an existing map. Replace its illustrative
preview hash with the supplied image's actual lowercase SHA-256.

```json
{
  "schema_version": 1,
  "display_name": "Example Ridge",
  "creator_username": "example_mapmaker",
  "contributors": ["example_lighting_artist"],
  "map_version": "1.0",
  "description": "A narrow ridge separates two fortified bases. 2-8 players.",
  "recommended_players": {"min": 2, "max": 8},
  "modes": ["slayer", "team_slayer", "ctf"],
  "source_url": "https://example.com/maps/example-ridge",
  "preview": {
    "file": "photos/example-ridge.png",
    "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "origin": "author"
  },
  "field_provenance": {
    "creator_username": {"origin": "author", "reference": "readme.txt"},
    "map_version": {"origin": "author", "reference": "readme.txt"},
    "recommended_players": {"origin": "author", "reference": "readme.txt"},
    "description": {"origin": "reviewed_editorial"},
    "preview": {"origin": "author"}
  }
}
```

Unknown creator usernames, authored map versions, descriptions, recommended player
ranges, URLs and pictures remain `null`. Contributors and modes default to empty
lists. With no editorial record, the safe output ID is a neutral display label
with filename-derived provenance. A cache format version or engine build is not
an authored map version. Spawn counts do not establish the recommended player
range; recommendations are bounded at 1-16 and remain distinct from mode-specific
start locations and the session limit.

The metadata schema rejects unknown fields and control characters. Display names
are limited to 128 characters, creator names to 128, map versions to 64 and
descriptions to 2,048. Use concise Xbox-style description prose; those schema
bounds do not establish that long text fits the existing menu widget. Mode IDs
are `slayer`, `team_slayer`, `ctf`, `oddball`, `team_oddball`, `king`, `team_king`,
`race` and `team_race`. Listing a mode is editorial information, not acceptance
of its gameplay.

Preview files must use safe relative paths, stay inside the metadata directory
without symlink components, be no larger than 10 MiB, and have a matching hash.
Accepted filename extensions are PNG, JPG/JPEG, BMP and WebP. Image bytes are
copied unchanged into the package; this stage checks identity and file signatures,
not visual quality or decoding. Origins are `author`, `generated_capture` or
`generated_artwork`. The converter packages supplied images; it does not capture
screenshots, generate artwork, crop images or add Xbox menu effects.

## Read outputs and builder reports

```text
output/
  batch.json
  maps/<id>.map
  metadata/<id>.json
  previews/<id>.<extension>
  reports/<id>-<input-index>.json
  reports/<id>-<input-index>.md
```

`maps/`, `metadata/` and `previews/` contain successful per-map outputs only.
Each discovered input gets a report, including resource maps and rejected caches.
One map's conversion failure does not prevent independent maps from being
packaged. Duplicate output identities reject both conflicting candidates. The
final directory is published atomically without replacing an existing destination.
Private conversion workspaces and full local tool logs remain under ignored
`build/map-pipeline-*` directories for investigation.
An existing compatible v5 input is staged without changing its tags under the
default preservation profile. Stock-first resolution, overlays or only an
extracted-scenario hash are rejected for that copy path. The general `omit`
policy or any selected asset stage routes v5 inputs through extraction and authoring instead.
Unchanged copies report `preserve_existing_v5`; rebuilt maps report their actual
conversion and omission steps.

| Status | Meaning |
| --- | --- |
| `inventoried` | Inspection succeeded; no conversion or gameplay check occurred. |
| `resource` | A supporting resource container, not a playable level. |
| `converted` | Output was compiled or staged, checked and packaged; gameplay remains pending. |
| `needs_profile` | Required tools, target support or an explicit compatible content recipe are missing. |
| `unsupported` | Identification rejected an unknown or malformed cache layout. |
| `failed` | A conversion, immutable-input, collision, metadata or verification requirement failed. |

The CLI returns 0 when the batch has no failed, unsupported or needs-profile
entries, 1 when such entries exist, and 2 when the batch cannot start. A nonzero
per-map batch result can still contain independent successful outputs; inspect
`batch.json` before staging anything.

Builder reports separate blockers, warnings, repairs and omissions. Diagnostics
include their stage, the reported tag/type and field/value when known, and a
suggested next step. Invader's `...in path.tag` context and RIAT missing-tag or
function errors are retained without inventing dependency chains or causes.
The machine-readable record preserves conversion and toolchain provenance.
Shareable reports remove absolute local paths and raw asset payload fields;
original source assets are not included in the report package.

Capacity failures include the actual size, maximum and excess bytes. When bitmap
usage was inventoried, they also list the largest winning bitmap payloads after
conversion and their consumer classes. These input payload sizes exclude compiler
deduplication; they identify likely reduction candidates, not a final cache size
breakdown. Increasing a compiler limit does not bypass the pipeline's native bounds.

For example, a missing dependency calls for the matching reviewed resource set;
an unsupported HSC function calls for a source-script review; a sound-format error
calls for a compatible codec overlay; and a changed preview hash calls for
reviewing the supplied image. Re-run into a fresh output directory after resolving
the recorded cause. Do not replace a precise diagnostic with broad script removal
or stock substitution.

## Identity and remaining integration

Generated metadata binds the original source SHA-256/cache version, the final
v5 cache build/SHA-256 and the converter profile ID/version/hash. Preview and
metadata hashes remain separate from the gameplay cache checksum. Correcting
authorship or changing a picture does not change `cache.sha256`.

The final cache SHA-256 is the intended multiplayer content identity. This tool
does not wire that identity into ordinary multiplayer handshakes or implement a
new network capability. Every peer still needs matching converted bytes and
compatible engine behavior. The metadata/preview sidecars are also not yet read
by the existing map-selection, lobby or server-details widgets; no UI cache is
patched or replaced by this command.

The default target allows 512 MiB decoded native multiplayer cache files and
retains the 22 MiB tag arena. This is a streamed disk-cache capacity, not a
512 MiB whole-map allocation: resource decompression buffers, the native memory
window and texture budgets remain separate. Multiplayer disk-cache slots use
the same capacity; download and import validators enforce it as well. The
runtime source changes require a rebuilt application before larger maps can
load in an installed build. Retail Xbox multiplayer disk-cache slots are 47 MiB; ordinary
texture-budget acceptance and actual console compatibility are additional checks.
Producing Xbox v5 serialization does not certify retail-console compatibility,
original authored behavior, or original Xbox gameplay fidelity.
