# Community map packages and local reconstruction

`tools/community_packages.py` prepares a whole-asset content package and reconstructs a
complete Xbox v5 multiplayer cache from that package plus the player's original
Xbox NTSC `bloodgulch.map`, `a10.map` and `ui.map`. It uses only the reviewed
native `invader-extract` and `invader-build` helpers during reconstruction.
It never runs a package's executables or build scripts.

This is an **unchanged-asset stripping prototype**, not a claim that the remaining
payload has cleared provenance. Only a complete prepared tag whose size, SHA-256
and bytes equal a complete freshly extracted original stock tag is omitted.
Path equality alone is insufficient; an identical tag under a different path
can reference its original source path. A tag differing by even one byte remains
an entire literal asset. Modified-original and unknown assets stay intact,
including existing compatibility repairs. There is no chunk matching or binary
delta. Tags that are functionally similar but serialize differently also remain
literal. `.mapog` adds lossless compression to those same assets; it does not
strip further content. Current network consumers accept schema 2 package
catalogs and reconstruct complete maps locally. This source change does not add
package reconstruction to previously published testing binaries.

## Optional Mac prototype

Mac packaging now resolves pinned helper distributions by default. Use
`tools/macos_build.py --content-tools <reviewed-toolchain-directory>` for an
explicit reviewed local toolchain, or `--without-content-tools` for an isolated
build without reconstruction support. Missing or unverified distributions fail
instead of selecting arbitrary tools.
That build exposes **Settings → Import Community Package…**, accepting `.mapog`
and legacy local `.hogpkg` files. Package HTTPS delivery uses the same assembler;
it requires community-download consent and the fixed bundled helpers. Import runs
extraction and compilation in the background using the active session's
original data, then registers a verified map in
`~/Library/Application Support/Halo OG/Community Maps/maps/`. A local receipt
allows verified maps to be reused after restart without downloading, including
when HTTPS hosting is unconfigured or community downloads are off. Local
receipt identity takes precedence over an HTTP catalog entry with the same ID;
existing differing destination files are preserved for the user to resolve.
The local package choice is separate from consent to network downloads.
Cancellation stops a missing-map wait while keeping verified ready maps usable.
The prepared package catalog sets `prefetch: false`: Mac downloads and rebuilds
on demand after consent. The current Windows/Linux worker instead processes
the approved collection in the background at launch when
`community_maps.auto_download` is true (the default), with progress in terminal
log output. It preserves existing files and requires restart for map discovery.
Neither behavior is present in the older published Windows/Linux testing ZIPs.

The newly rebuilt reviewed helper binaries target **macOS 14.0**. This describes
the helpers' deployment target, not a claim of physical testing on macOS 14 or a
lower minimum for the rest of the app. Helper-enabled packaging
includes both binaries in the minimum-OS calculation, source and signed-binary
hash records, and their notices. The current published testing DMG does not
provide package import. Current desktop release packaging is being wired to
pinned native helper distributions; Windows/Linux distribution pins remain
unavailable until their reviewed helper builds pass.
The tested bundle includes a verified corresponding-source archive and notices,
but its `fresh_ci_ready` record remains false. Packaging refuses `--release`
with that record until the fresh-CI and public source-delivery gate is completed.
The optional helper audit checks the actual bundled binary hashes,
reviewed source pins, system-library dependencies and recorded notice hashes.

Both Python and the production native assembly/receipt APIs recreated all 40
approved maps exactly in isolated tests, as recorded below. An isolated helper-enabled app
also passed signing and bundle audits. Native menu interaction and gameplay in
that prototype app have not been exercised; the installed app and active game
were preserved.

## Windows and Linux reconstruction

Windows and Linux support is a requirement of the package design. The same
`.mapog` must rebuild the same Xbox NTSC v5 map on Mac, Windows, and Linux;
the host platform does not change the map format or the stock data required.
The current real collection reconstruction evidence is from an ARM Mac only.

The developer CLI supports fixed native `invader-extract` and `invader-build`
helpers, with `.exe` names on Windows. A package records its producer's helper
hashes. A different native consumer toolchain must independently pin its own
helper hashes and explicitly allow that exact producer in the **locally trusted**
toolchain manifest's `compatible_package_producers` array:

```json
{
  "invader_commit": "7d25a855f5ef9e4ab8407abf490b21f8780abf27",
  "binaries": {
    "extract": {"sha256": "<reviewed native extractor SHA-256>"},
    "build": {"sha256": "<reviewed native builder SHA-256>"}
  },
  "compatible_package_producers": [
    {
      "invader_commit": "7d25a855f5ef9e4ab8407abf490b21f8780abf27",
      "tool_sha256": {
        "extract": "4dc6a8c5583f055b715cf48ae011929be63749a56a68540c31e73238d46e1e3f",
        "build": "4586b82e0db2a57e390e6d61ccf3a4cf2fde26288652cd0d3708be0e87111f65"
      }
    }
  ]
}
```

This example allows the reviewed Mac producer used for the Downrush prototype.
Replace the two placeholders only with hashes of reviewed native helper builds.
Keep that manifest outside downloaded packages; do not generate approval entries
automatically from untrusted package metadata. Sharing an Invader source revision
alone does not authorize a different toolchain. Existing manifests without a
compatibility array keep their exact producer/consumer binary-hash requirement.
An optional `consumer_platform` field (`macos`, `windows`, or `linux`) must match
the current host. Provenance records both the producer and native consumer
helper hashes and the consumer platform.

Run the existing CLI with user-extracted stock maps and a fresh output directory:

```sh
python tools/community_packages.py reconstruct --package downrush.mapog --stock-maps /path/to/your/maps --tool-bin /path/to/reviewed/native/tools --toolchain-manifest /path/to/trusted/source-manifest.json --destination build/community-maps/downrush-new
```

On Windows, use native Windows paths for those arguments and quote paths with
spaces. Package and extracted asset paths must also satisfy Windows filename
rules, including reserved device names and trailing dots/spaces. The CLI keeps
the exact original-stock, restored-tag, final-map size, and SHA-256 gates.
Only a successful exact rebuild publishes the final map and provenance.

The [desktop portability workflow](../.github/workflows/community-packages.yml)
runs synthetic package, filesystem, helper-selection, and publication checks on
Windows, Linux, and Mac. It uses no game assets. These checks do **not** prove
that real Invader builds produce identical Downrush bytes on those platforms.
Before enabling package inclusion in distributed builds, each desktop platform
still needs reviewed native helper binaries and dependency/source delivery, a
real same-package/same-stock exact-hash rebuild, and game load/play verification.
Pin the compression and conversion dependencies as well as Invader: the reviewed
Mac build found zlib 1.2.12 in the Apple SDK, and compression differences can
change the final cache SHA-256. Native Squish settings also need to match the
reviewed scalar configuration. Capture the RIAT Cargo lockfile and match the
Windows Rust/C runtime toolchains as part of reproducible helper builds.
A build that misses the approved output hash remains unusable.
Run those tests locally with independently supplied game data; do not upload
stock maps or disc images to public CI. Current desktop source supports package
HTTPS delivery using trusted native helpers, but real Windows/Linux assembly
and game play remain unverified. Android package reconstruction is unfinished.

## Format and consumer contract

A `.mapog` file has a 48-byte header (`<8sQ32s`, little endian): magic
`HOGMAP2\n`, exact expanded package size, and binary SHA-256 of the expanded
package. Exactly one RFC 1950 zlib stream follows. The decoder rejects trailing
streams/bytes, preset dictionaries, truncated or corrupt streams, expansions
over the declared size or 256 MiB, wrong inner hashes and wrong inner magic.
Expansion uses an owned private temporary file; native consumers remove that
temporary content when inspection or assembly finishes. Catalog hashes and
sizes identify the compressed `.mapog`, separately from the final compiled map.
Immutable object keys are `packages/sha256/<package_sha256>/<id>.mapog`.

The inner `.hogpkg` contains a 16-byte header (`<8sQ`, little endian), UTF-8 JSON,
then contiguous raw literal bytes. The magic is `HOGPKG1\n`; the unsigned 64-bit
integer gives the JSON byte length. Literal offsets start at the beginning of
the payload, not the file. It contains no archive paths or chunk deltas. Raw
`.hogpkg` remains supported for local inspection and reconstruction; network
catalogs require the compressed `.mapog` representation.

Version 1 accepts exactly these manifest fields:

| Field | Meaning |
| --- | --- |
| `format`, `version` | `halo-og-community-package`, `1` |
| `id`, `scenario` | Safe lowercase community ID and relative compiled scenario ending in that ID |
| `profile`, `cache_build` | `stock-xbox-ntsc`, `01.10.12.2276` |
| `invader_commit` | Reviewed `7d25a855f5ef9e4ab8407abf490b21f8780abf27` revision |
| `tool_sha256` | Exact `extract` and `build` binary hashes; this prototype records Mac binaries |
| `stock_inputs` | Ordered `bloodgulch`, `a10`, `ui` entries: `name`, complete `size`, `sha256`, `type` (1, 0, 2) |
| `output` | Approved complete cache `size`, `sha256`, `declared_bytes`, `tag_bytes` |
| `payload_bytes`, `files` | Exact payload size and asset records |

Stock cache hashes are **per-package exact-base requirements**, not a global
allowlist of all acceptable original game data. The producer records its chosen
NTSC caches, and the consumer requires those exact complete inputs. This
Downrush package is pinned to the three original caches used by its approved
conversion; it does not accept every disc with the same build header.

Every file record has `tree`, `path`, `kind`, `classification`, `size` and
`sha256`. Trees are `tags`, `data` or `stock-overrides`. Literal records add
`offset`. `stock-reference` records add `stock_path`, are allowed only in `tags`,
and have classification `unchanged-stock`. They restore the whole original tag
under the prepared tag's requested path.

Other tag classifications are `modified-or-different-stock` and
`unknown-or-community`; neither proves authorship. Prepared `.hsc` files use
`generated-data`. Stock overrides are complete literals classified
`compatibility-modified-stock`, with an additional `original_sha256` guard for
the unmodified original tag. Overrides replace only the consumer's temporary
extracted copy. The original caches and selected game-data folder remain intact.

Limits are 4 MiB JSON, 20,000 records, 256 MiB for the complete package, 128 MiB
per asset, and 1 GiB of listed expanded assets. The consumer rejects unknown
fields/versions, duplicate JSON keys, unsafe or aliased paths, links, duplicate
or case-colliding names, file/directory conflicts, noncontiguous offsets,
truncation, trailing bytes and bad whole-file hashes. Original stock cache
inputs can exceed the 128 MiB multiplayer cache limit; their complete hashes
and NTSC headers are still required. The final multiplayer cache must satisfy
the 128 MiB declared-cache and 22 MiB tag-arena limits, including its tag range.

The consumer first verifies the package, trusted helper hashes, exact stock
cache inputs, all referenced stock tags and all override bases. It extracts
stock in `bloodgulch → a10 → ui` order, restores prepared tags/data, applies
guarded whole-file stock overrides and builds with stock-first tag priority:

```text
invader-build -g xbox-ntsc -t stock -t tags -m maps -d data -S data -E <scenario>
```

Only a cache matching the approved header, complete size and SHA-256 is usable.
Python reconstruction uses a fresh destination, publishes verified maps last,
and removes its generated destination on failure. It refuses existing
destinations, including dangling symlinks. The native Mac integration uses the
same data contract; consumer Python is not a requirement for that design.

## Producer and local verification

The producer accepts already reviewed converted tags and generated script data.
Its `original_stock_tags` input must be a fresh extraction with the pinned
extractor and the same stock order. `patched_stock_tags` must have the identical
inventory, with only the existing reviewed contents changed. A real
reconstruction from the original caches is the acceptance gate for that
producer-input assumption. See [community-maps.md](community-maps.md) for
central conversion and the pinned toolchain/source-manifest procedure.

```sh
# Fresh, unmodified stock extraction: verify the reviewed Mac helper before running it.
python3 - "$INVADER_BIN" "$INVADER_MANIFEST" \
  build/community-maps/local-package-prototype-20261003/original-stock-tags <<'PY'
import json
from pathlib import Path
import subprocess
import sys
from tools.community_packages import digest

binary = Path(sys.argv[1]).resolve() / "invader-extract"
manifest = json.loads(Path(sys.argv[2]).read_text())
pins = json.loads(Path("port/macos/content-tools.json").read_text())
if (manifest["invader_commit"] != pins["invader_commit"] or
    manifest["binaries"]["extract"]["sha256"] != pins["binaries"]["extract"] or
    digest(binary) != pins["binaries"]["extract"]):
    raise RuntimeError("Extractor differs from the reviewed Mac source and binary pins")
stock = Path(sys.argv[3]).resolve()
stock.mkdir(parents=True, exist_ok=False)
for name in ("bloodgulch", "a10", "ui"):
    subprocess.run([str(binary), "-t", str(stock),
                    str((Path("assets/maps") / (name + ".map")).resolve())], check=True)
PY

python3 tools/community_packages.py prepare \
  --prepared-tags build/community-maps/full-collection-import-20261002/downrush/tags \
  --prepared-data build/community-maps/full-collection-import-20261002/downrush/data \
  --original-stock-tags build/community-maps/local-package-prototype-20261003/original-stock-tags \
  --patched-stock-tags build/community-maps/full-collection-import-20261002/stock-tags \
  --stock-maps assets/maps \
  --expected-map build/community-maps/full-collection-import-20261002/downrush/maps/downrush.map \
  --scenario levels/test/pat_downrush/downrush \
  --toolchain-manifest "$INVADER_MANIFEST" \
  --destination build/community-maps/local-package-prototype-20261003/downrush.hogpkg

python3 - <<'PY'
from pathlib import Path
from tools.mapog import compress_package
root = Path("build/community-maps/local-package-prototype-20261003")
print(compress_package(root / "downrush.hogpkg", root / "downrush.mapog"))
PY

python3 tools/community_packages.py reconstruct \
  --package build/community-maps/local-package-prototype-20261003/downrush.mapog \
  --stock-maps assets/maps --tool-bin "$INVADER_BIN" \
  --toolchain-manifest "$INVADER_MANIFEST" \
  --destination build/community-maps/local-package-prototype-20261003/reconstructed

python3 tools/community_packages.py inspect \
  build/community-maps/local-package-prototype-20261003/downrush.hogpkg
python3 -m unittest tools.test_community_packages

# Actual native API acceptance, using a separately staged optional-helper app.
python3 tools/macos_map_package_smoke.py \
  --package build/community-maps/local-package-prototype-20261003/downrush.mapog \
  --data-root assets \
  --tools-app "build/community-tools/macos14-staging-check-20261003/Halo OG.app" \
  --output build/community-maps/local-package-prototype-20261003/native-smoke-new-run
```

`INVADER_BIN` and `INVADER_MANIFEST` above are temporary shell shortcuts to the
reviewed local tools, not application settings. Choose fresh output paths for
every run. `prepare_package`, `read_package`, `materialize_package` (asset-only
fixture seam) and `reconstruct_package` are also callable Python APIs.

The isolated 2026-10-03 Downrush run produced a 69,252,341-byte package, SHA-256
`8652543d972f227d5dd7718bfaae06151290a93b2ffa0daa1fd20ce2dadcd287`.
Its 1,376 entries retain 453 same-path differing tags, 217 unknown/community
tags, five whole modified-stock compatibility tags and one generated script.
Its 700 unchanged-stock references omit 10,498,176 bytes. The raw package is
larger than the compressed compiled map; size reduction is not the acceptance
criterion for this pass.

Using only the pinned extractor and builder, fresh stock extraction plus this
package reproduced the approved Downrush cache exactly: 26,480,640 bytes,
SHA-256 `3282e580e782f939ae00c63f01971238eb0f85db19a2467efe42b5cb5600d126`.
The inspectable manifest, helper logs and reconstruction provenance are under
the ignored `build/community-maps/local-package-prototype-20261003/` directory.

The final native smoke (`native-smoke-final-v2-20261003/status.json`) reconstructed
those exact bytes in an observed **9.26 seconds** and passed 15 native parser,
reuse and helper-mismatch cases. It verified local registration, fresh startup
with hosting unconfigured and HTTP consent off (`PENDING → READY`), exact map
replay without helper execution, uppercase stock paths, tamper rejection and
preservation of conflicting files. Removed local maps produced an explicit
re-import/cancel status with mocked HTTP enabled; cancellation returned
`UNAVAILABLE` to stop waiting without fetching a map. The run made zero real network requests
and one mock catalog request; original caches, package and helpers were
unchanged. The filesystem could not exercise two differently cased stock
filenames because it is case-insensitive; the parser's case-collision fixture
did pass.

The separately staged `host-build-final/Halo OG.app` passed the app signature
and bundle audits for 11 Mach-O objects, with minimum OS 27.0. The game and UI
were not launched by this acceptance check. These results prove the local ARM
Mac data reconstruction and receipt path. Other toolchain/platform variants,
native menu interaction and gameplay need
their own checks; physical cross-platform play is still unverified. The
installed app, active game, original data and user preferences were untouched.
The separate batch below verifies all 40 conversions through the Mac producer
and CLI reconstructor; it does not extend that native UI or gameplay coverage.

## Batch producer and whole-asset audit

`tools/community_package_batch.py` prepares the approved collection without
changing the v1 package format. Supply the reviewed prepared-map collections,
an approved full-map catalog, exact original stock caches, and pinned native
tools. The initial inventory must cover exactly the catalog's IDs and complete
map hashes. The original collection has 39 successful maps; the separately
repaired Weld collection supplies the fortieth.

```sh
python3 tools/community_package_batch.py verify \
  --prepared-collection build/community-maps/full-collection-import-20261002 \
  --prepared-collection build/community-maps/full-collection-weld-repair-20261002 \
  --approved-catalog build/community-maps/r2-full-collection-candidate-2026-10-03/catalog.json \
  --stock-maps assets/maps --tool-bin "$INVADER_BIN" \
  --toolchain-manifest "$INVADER_MANIFEST" \
  --destination build/community-maps/all40-package-audit-new

python3 -m unittest tools.test_community_package_batch tools.test_community_packages
```

Choose a destination that does not exist. The batch freshly extracts original
stock tags, prepares each package, then runs a separate fresh extraction and
exact reconstruction for every map. `inventory` with the same inputs and no
`--destination` performs only the read-only identity checks.

`inventory.json` records every selected source and approved map identity.
`audit.json` records each package's size/hash, reconstruction result, whole-tag
classification totals, and final input-preservation checks. Each
`maps/<id>/asset-audit.json` contains the complete whole-file decisions; no
retained literal may match any original complete tag's size and SHA-256.
Different serialization still remains literal. Custom content and complete
modified-original assets are preserved; these classifications do not prove
authorship or clear the remaining payload's provenance.

Packages are at `maps/<id>/<id>.hogpkg`; verified maps are at
`maps/<id>/reconstructed/maps/<id>.map`. The batch also retains private original
stock extraction, helper logs and reconstructed tag trees for review. **Never
publish the batch directory as a whole.** A publisher must select only explicit
verified package files; original stock, rebuilt complete maps, logs and helper
inputs are excluded from a stripped-package upload. Failed maps remain marked
failed, and any failure or changed input prevents an overall verified result.

The isolated batch `build/community-maps/all40-package-audit-20261004T041133/`
verified **all 40** approved maps, including the repaired Weld, with zero failures
in an observed **404.894 seconds**. Every reconstructed map matched its approved
complete SHA-256, size and Xbox v5 header. Original caches, prepared tags/data,
stock extraction, helper binaries and the approval catalog remained unchanged.
No retained literal matched any complete freshly extracted original tag's size
and SHA-256.

Across the 40 packages, 28,220 whole-stock reference instances omit 403,459,188
bytes. The payload preserves 18,295 modified or differently serialized stock
tags (939,306,383 bytes), 200 guarded compatibility repairs (624,400 bytes),
7,451 unknown/community tags and 39 generated scripts. Counts include repeated
assets across maps. The packages total **2,589,811,840 bytes (about 2.41 GiB)**;
their raw tag representation is larger than the approved compiled-map collection.
This proves exact local reconstruction and the narrow whole-tag omission rule,
not authorship, public distribution clearance, or multiplayer compatibility on
physical Windows/Linux machines.

## Compressed collection and native acceptance

The prepared 40-map `.mapog` collection totals **721,262,748 bytes (about
688 MiB)**, compared with 904,589,312 bytes (about 863 MiB) for the approved
complete compiled maps. Its lossless inner packages contain the same complete
literal assets and stock references audited above. The raw packages total
2,589,811,840 bytes; their JSON and headers account for 14,540,759 bytes. Raw
tag files retain editor/source fields and a different representation from the
compiled cache, which is itself Xbox-compressed. The compiled caches declare
1,889,942,528 expanded bytes in total. These totals do not measure the savings
of individual compilation transforms, and compression does not authorize
omitting any modified or custom asset.

The 2026-10-04 native acceptance at
`build/community-maps/native-mapog-macos14-all40-20261004T044053/status.json`
recreated **40 of 40** compressed packages with the newly reviewed macOS 14
helpers. Every complete output matched its approved SHA-256, size and Xbox v5
header. The observed collection run took **477.924 seconds**, including receipt
and filesystem checks; actual assembly totaled 413.954 seconds. Each map passed
local registration, guest `READY`, fresh startup with hosting unconfigured and
downloads disabled, replay without helper execution, conflicting-file
preservation, tamper rejection, missing-map cancellation and uppercase stock
paths. No real network requests occurred; each probe made one mock catalog
request. Original caches, all compressed packages, catalog, helpers and the
bundled helper record remained unchanged.

This is native data-assembly and offline-library evidence, not an app UI or
gameplay test and not proof of physical Windows/Linux reconstruction. The probe
used an existing approved stock folder; XISO extraction itself was not tested
in this batch. The installed app, active game and user preferences were
untouched. The tested helper bundle's corresponding-source resource was
25,069,173 bytes, SHA-256
`263b7bba209e7c041270aea04591c2bdb7e2cc3c0f59d237e14d562bb7648f51`;
newer source-delivery candidates require their own verification.

The all-map probe records its exact compiled source hashes. A subsequent
nonblocking regular-file read hardening passed the asset-free native HTTPS
fixtures, including FIFO package/map/catalog/receipt/helper-record rejection,
compressed-stream tampering and immediate cancellation during assembly. The
separate `post-hardening.json` identifies those source hashes; it does not
retroactively change the source provenance of the 40-map run. A fresh hardened
Downrush smoke at
`build/community-maps/native-mapog-macos14-post-hardening-downrush-20261004/status.json`
also rebuilt the exact approved bytes in 11.105 observed seconds, passed all 15
parser/helper/reuse cases, and preserved its inputs and offline receipt checks.
Public catalog
advancement and any new release remain separate deployment gates.
