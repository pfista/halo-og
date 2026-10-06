# Community maps

Halo OG imports community content into its Xbox-derived engine. The reviewed
JukkisP H1 Performance Build 2.0 Public Beta 3 collection contains 40 maps;
conversion targets Xbox NTSC v5 build `01.10.12.2276`. Follow the
[fidelity policy](xbox-fidelity.md) and [player setup](playtesting.md#community-maps).
The current download path supplies complete playable `.map` files; the local
package-reconstruction experiment has been set aside.

## Runtime support for compatible v5 maps

Place a compatible v5 multiplayer cache in the active data root's `maps/`
directory and restart. Discovery keeps the original 13 maps in order, then
appends custom maps sorted by name, up to 128 entries total. Headers must have
a recognized regional build, multiplayer type and a name matching the filename,
ignoring case. Names are 1–31 ASCII letters, numbers, spaces, underscores or
hyphens; stock-name duplicates are skipped. Native disk caches are bounded at
128 MiB and the original tag arena remains 22 MiB.

A v7 cache cannot be converted by renaming it or changing its version field.
Passing header checks does not establish support for every tag or game mode.

## Managed storage and downloads

Mac first launch accepts an original Xbox disc image or extracted maps folder.
Folder selection offers **Copy and Manage**, **Use This Folder**, or **Cancel**.
Copies/imports preserve their sources, earlier imports and existing destination
files; a failure preserves the previous selection. Data-root changes apply on
the next launch. Importing original data does not upload it.

```text
~/Library/Application Support/Halo OG/
  macos-settings.json
  config.toml
  Game Data/<import-id>/maps/
  Community Maps/maps/
```

Settings, profiles, saves, logs and verified community maps live outside the
app bundle and survive updates. Legacy `Halo CE Universal` data is copied
without deleting originals or replacing existing Halo OG files.
Windows saves use `%APPDATA%/Halo OG`; Linux uses `$XDG_DATA_HOME/halo-og`
or `~/.local/share/halo-og`. See [player setup](playtesting.md) for each build's
configuration, data location and download controls.

The `test-v0.3.0-net11-maps1` testing release and current main builds enable
background downloads on Mac, Windows and Linux with fresh settings. Once
compatible original NTSC game data is available, they queue all 40 approved
community maps, about 863 MiB. Saved opt-outs remain off. Mac Settings controls
downloads; Windows/Linux use `community_maps.auto_download` in `config.toml`
beside the executable. The older `test-v0.3.0-net11-dmg2` Mac build requires
opt-in, and its Windows/Linux builds require manual community maps. Android
still installs matching maps manually.

Mac stores downloads in `Community Maps/maps/` above; Windows/Linux store them
in the active game data root's `maps/` directory. Transfers run off the
simulation thread. Exact size, SHA-256 and Xbox v5 identity are verified before
exclusive publication; different same-name files are preserved. Verified maps
remain usable offline. Restart Windows/Linux after completion to refresh map
discovery; see [player setup](playtesting.md#community-maps) for progress,
controls and manual downloads.

Hosted community caches retain their required embedded Halo dependencies.
They exclude standalone disc images and separate stock, campaign and UI map
files; players supply original game data themselves. Downloads install directly
without tag extraction, Invader or a reconstruction toolchain.

The nonsecret Mac endpoint configuration is
[`map-downloads.json`](../port/macos/map-downloads.json). The publisher is
`https://dl.oghalo.com/`; the catalog is `catalogs/testing/current.json`.
Upload credentials stay outside the client in the approved 1Password environment.
See [publishing](map-publishing.md) for the operator workflow.

Uncut Fiesta and All Fiesta request a separate hidden weapon cache for the
selected logical map. These variants contain the whole map plus the shared
weapon dependencies because the engine reads one compiled map cache at a time.
The full generation-one library has 54 variants, about 1.995 GB; Prisoner alone
is 34 MiB. Its public catalog and cache objects are pending R2 upload, so
automatic expanded-Fiesta downloads are currently unavailable. Until publication,
install matching prepared cache/manifest pairs manually using the
[weapon-cache guide](weapon-pack-maps.md). Once published, Mac, Windows and Linux
download only requested variants through
`catalogs/testing/arsenals-v1.json`, under the same download preference as
community maps. Ordinary modes keep using the original map files.

The downloader verifies the original-map SHA, catalog identity, cache and flat
manifest before reporting readiness. Mac installs pairs in
`Community Maps/maps/arsenal/v1/`; Windows/Linux use the active data root's
`maps/arsenal/v1/`. Different existing files are preserved. Selection waits for
the download and asks you to select the option again; a compatible joining
client waits automatically for the host's exact arsenal revision. Android
continues to install matching pairs manually. See the
[weapon-cache guide](weapon-pack-maps.md) for preparation and publication.

## Reproduce the imports

For new cache formats or custom weapon sets, use the separate
[conversion guide](community-map-conversion.md). Its authored-first workspace
and reviewed overlays differ from the stock-first H1PB policy below.

Run from the repository root and choose fresh output directories under `build/`.
Supply the source package's `maps/` and `tags/` and your own original NTSC caches
(`assets/maps` by default, or `--stock-maps`). Never run executables supplied by
the map package.

```sh
python3 tools/community_maps.py inventory \
  --package /path/to/H1PB-Beta-3 \
  --output build/community-maps/inventory-new

python3 tools/community_maps.py build \
  --package /path/to/H1PB-Beta-3 \
  --invader-bin /path/to/reviewed-toolchain/build \
  --invader-manifest /path/to/reviewed-toolchain/source-manifest.json \
  --all --output build/community-maps/imports-new
```

The importer authenticates helper hashes and Invader revision
`7d25a855f5ef9e4ab8407abf490b21f8780abf27`.
[`jukkis-beta3.json`](../port/maps/jukkis-beta3.json) pins scenario hashes,
allowed scripts and cleanup prefixes. Changed scenarios/scripts require review.
Repeated `--map` selects a cohort; omitting `--all` and `--map` selects Downrush.
Batch builds continue after a per-map failure; inspect `build.json` before staging.

After [building the Mac app](apple-build.md), stage a separate local candidate:

```sh
python3 tools/community_map_candidate.py \
  --imports build/community-maps/imports-new \
  --high-refresh --practice-launchers \
  --output build/community-maps/candidate-new
```

The candidate verifies map/stock input hashes, uses separate saves and retains
original HUD art and 30 Hz simulation. `--high-refresh` enables interpolation;
otherwise it uses the 30 FPS reference profile. Practice launchers run offline
one-player Slayer. Keep source folders available: the candidate uses local links.
This is local staging, not installation or publication.

## Import policy

Stock dependencies take precedence: extract Blood Gulch first, then fill missing
assets from `a10` and `ui`. Preserve authored geometry, collision, lighting,
textures, devices, spawn/item positions and required custom assets. Convert
Gearbox models to Xbox models and rewrite references in copied tags.

Remove the reviewed NHE host setup, countdowns, timer/waypoint aids and optional
garbage-collection scripts. Where required, a startup script removes only the
reviewed `spawn_marker` and `randoms` training objects. Octagon B needs no such
cleanup. Do not remove authored doors, lights, fans or other devices. Combat-AI
encounters are rejected for this profile.

Four stock-name variants use `h1pb_chillout`, `h1pb_hangemhigh`, `h1pb_prisoner`
and `h1pb_wizard` throughout scenario identity, cache name and network lookup.
Stock lookup cannot replace authored level content. Weld's extended Chicago sky
shader is converted to Xbox-supported Chicago form while preserving its authored
layers; compare its appearance during testing.

Stock recompilation repairs are limited to unused vehicle-gun AI firing
references, the Scorpion headlight flare bitmap index and its secondary-fire
bullet effect-location index. Manifests record before/after hashes, substitutions,
removed scripts, conversions, scenario identity and output SHA-256. Source files
remain intact; extracted original tags are local conversion inputs. Reviewed
complete community caches can be hosted separately from the client.

## Validation

**Octagon B has no blue CTF spawns**; do not advertise it as accepted for CTF.
Compiler warnings and missing Race/spawn data require per-mode checks. Test
collision, spawn/item behavior, authored devices, sky/lighting, weapon/audio
behavior, controllers, transitions and longer sessions. Builds and short Slayer
load/render checks do not certify every mode or original-Xbox fidelity.

Run gameplay/network probes sequentially with fresh saves and output folders:

```sh
python3 tools/macos_multiplayer_smoke.py \
  --mode invite --seconds 70 --map downrush \
  --map-source build/community-maps/imports-new/downrush/maps/downrush.map \
  --reference-profile --output build/community-maps/network-new
```

Same-machine probes do not establish physical cross-platform or Internet/NAT
play. Keep generated maps, logs, saves and private invites out of Git.

For a custom weapon set or objective-mode acceptance, use the separate
[community multiplayer harness](community-multiplayer-testing.md). The older
smoke above uses synthetic damage/kill diagnostics by default; it establishes
connection and lifecycle evidence, not actual projectile damage or objective
scoring. Bind the reviewed map and frozen runtime by hash, exercise ordinary
inputs, and assert the relevant state on both peers.
