# Publishing the testing map catalog

[`map-publisher.json`](../tools/map-publisher.json) pins the nonsecret R2 account,
`halo` bucket, public origin, testing catalog destination and reviewed 40-map
allowlist. Expand the allowlist only after reviewing additional maps for public
distribution. Never upload XISOs, stock/campaign/UI caches, extracted originals,
helper binaries or private logs as map objects.

## Current complete-map publisher

The existing publisher handles complete converted community maps, including
their embedded Halo dependencies. Prepare a new catalog directory with explicit
`--map` arguments for the reviewed caches. Current Mac, Windows, and Linux
clients download all eligible catalog maps when automatic downloads are enabled.
Retain `--prefetch <map-id>` for older clients that use this hint.

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

The live testing catalog contains the 40 complete playable community maps.
Local reconstruction and package-only distribution are set aside. Keep using
the complete-map publisher; no content-tool download or local map rebuild is
required by the desktop release.

Local validation, upload completion, old-object retirement and gameplay acceptance
are separate results. See [playtesting](playtesting.md) for client acceptance.
