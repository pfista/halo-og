# Publishing the testing map catalog

[`map-publisher.json`](../tools/map-publisher.json) pins the nonsecret R2 account,
`halo` bucket, public origin, testing catalog destination and reviewed 45-map
allowlist. Expand the allowlist only after reviewing additional maps for public
distribution. Never upload XISOs, stock/campaign/UI caches, extracted originals,
helper binaries or private logs as map objects.

## Current complete-map publisher

The existing publisher handles complete converted community maps, including
their embedded Halo dependencies. Prepare a new catalog directory with explicit
`--map` arguments for the reviewed caches. Current Mac, Windows, and Linux
clients download all eligible catalog maps when automatic downloads are enabled.
Retain `--prefetch <map-id>` for older clients that use this hint.

The prepared catalog replaces the current catalog; it is not an append request.
When adding a map, retain every existing entry and immutable object from the live
catalog, add the reviewed map, and verify that the old entries are unchanged.
Guard the publisher's initial authenticated catalog read against the exact live
snapshot used for preparation. Its ETag condition then protects against changes
during publication. Supply `--expect-catalog-sha256 <snapshot-sha256>` with an
authorized publication to enforce that initial read before any object writes.

```sh
python3 tools/map_catalog.py \
  --output /path/to/new-catalog \
  --map /path/to/approved/community.map
python3 tools/publish_map_catalog.py --prepared /path/to/new-catalog
```

Without `--publish`, the publisher validates locally and reads no credentials.
Validation checks catalog identity, native cache format, sizes and SHA-256; the
prepared tree must contain only the catalog and declared map objects.

For an authorized publication, add `--publish` and `--credential-file` pointing
to an existing 1Password-mounted file from the `oghalo.com` environment. The
publisher reads credentials as data, never executes the file, and keeps values
out of logs and the client.

Immutable objects are created conditionally and verified through R2 and public
HTTPS before the mutable catalog advances with its captured ETag. The destination
is [testing/current.json](https://dl.oghalo.com/catalogs/testing/current.json).
A failed public read can leave a published catalog; inspect its state before
retrying. This publisher does not delete objects or automatically roll back.
Run `python3 tools/publish_map_catalog.py --help` for the current CLI contract.

## Distribution scope

The publisher allowlist covers 45 complete converted community maps.
Local reconstruction and package-only distribution are set aside. Keep using
the complete-map publisher; no content-tool download or local map rebuild is
required by the desktop release.

Four additional Digsite conversions are prepared as `chillout_dig`,
`damnation_dig`, `exhibit_dig`, and `prisoner_dig`. The prepared 45-map catalog
preserves all 41 previous entries, including the separate `chillout_digsite`
revision. These regular caches retain their reviewed Battle Rifle omissions.
Their hidden Fiesta companions use the separately approved existing 31-weapon
All pack; see [Fiesta delivery](weapon-pack-maps.md#delivering-hidden-arsenals).
Map publication and the next app release are separate operations. No gameplay
testing was performed for this four-map preparation.

On 2026-10-05, `chillout_digsite` replaced the earlier `chillout_dig` POC entry.
It appears as **Chillout Digsite** in the community map menu and is eligible for
automatic downloads on existing clients. Its embedded bitmaps and sounds need
no external resource files. The published Xbox v5 cache SHA-256 is
`93d966f3e191cb3f0506d8c31b2d0d3641e3530fac063387b6f4d2c435b6631d`
and its transfer size is 35,586,048 bytes. The
[complete map download](https://dl.oghalo.com/maps/sha256/93d966f3e191cb3f0506d8c31b2d0d3641e3530fac063387b6f4d2c435b6631d/chillout_digsite.map)
is immutable. The testing catalog remains at
[`current.json`](https://dl.oghalo.com/catalogs/testing/current.json).
On 2026-10-05, the catalog snapshot SHA-256 was
`bab01df54df64b2b04f1b998f6110dc79dbc0962b108020d3df6f6d9d2b1d9d1`.
All 41 complete objects were verified through R2 and public HTTPS before the
catalog update, and the other 40 catalog entries were preserved unchanged.
The old POC object remains downloadable; previously installed POC files are
not deleted or renamed.

Static checks cover all nine classic presets. Two native peers on one Mac
verified CTF, Oddball, Team Oddball, King and Team King scoring, natural match
end and rematch against this exact cache without targeted cache/sound warnings.
The user accepted publication for player testing with this coverage. Slayer,
Team Slayer, Race and Team Race runtime qualification, representative custom
weapon network damage/kill coverage, physical cross-platform play, split-screen
and audible sound quality remain unverified. This revision removes the POC's
first-player SMG grant, restores exact stock Xbox Race checkpoints, corrects
three multiplayer text entries and selects an existing missile-launcher mip
for the Xbox texture budget. See the
[conversion guide](community-map-conversion.md) and
[native multiplayer record](community-multiplayer-testing.md).

Local validation, upload completion, old-object retirement and gameplay acceptance
are separate results. See [playtesting](playtesting.md) for client acceptance.
