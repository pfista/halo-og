# Mac Fiesta arsenal downloads

Mac requests a hidden arsenal when selecting or joining Fiesta with Weapon Set
Uncut or All. The selected map and original game data are still required. This
does not queue the complete arsenal collection at launch: only a requested
logical map, original-map SHA-256 and, for a joining client, the host's exact
arsenal SHA-256 may be downloaded.

The existing community-download setting controls HTTP access. Verified complete
pairs remain available with downloads disabled or offline, including pairs
installed manually before this downloader has seen a catalog. A missing pair
keeps the previous menu selection while preparation is pending. Settings shows
download progress through the existing map status display. **Cancel Downloads**
stops active transfers; **Check Maps**, or enabling downloads again, retries
previous requests. A failure remains stable until this explicit retry.
Check Maps revalidates previously ready pairs as well, allowing a removed pair
to be downloaded again. Different or corrupted existing files remain preserved;
move the conflicting pair aside before retrying a replacement.

Downloads use the nonsecret configuration in
[map-downloads.json](../port/macos/map-downloads.json), with catalog
`https://dl.oghalo.com/catalogs/testing/arsenals-v1.json` and the existing
approved HTTPS object origin. The catalog is pinned to profile
`fiesta-arsenal-v1`, generation 1 and the compiled weapon-list SHA-256.
Metadata rejects duplicate or unknown fields, escaped/non-ASCII strings,
noninteger sizes, unsafe names, mismatched immutable object keys and conflicting
logical-map/original-SHA identities. Bounds are 1 MiB for the catalog, 115 entries,
4096 bytes per manifest, 128 MiB per cache transfer/declared size, 22 MiB for cache
tags and 2 GiB for the advertised collection including metadata.

The managed layout is separate from the app bundle and original maps:

```text
~/Library/Application Support/Halo OG/Community Maps/
  maps/arsenal/v1/_fiesta_prisoner.map
  maps/arsenal/v1/_fiesta_prisoner.json
  Downloads/.fiesta-<private staging id>/
```

Names longer than 23 characters use `_fiestah_<16 hex characters>`, derived
from the lowercase logical name's SHA-256. Logical names in menus and on the
network stay unchanged.

The worker authenticates the manifest first, then streams only its matching
cache. Both full SHA-256 digests, exact transfer sizes, flat runtime manifest,
physical cache-header name, declared size and supported Xbox NTSC v5 build must
match before the pair becomes ready. Exclusive links preserve different existing
files and symlinks. An interrupted matching half may be completed; a partial pair
is never ready. Runtime preparation separately authenticates the selected
original map and verifies the compiled arsenal/player compatibility before use.

Synthetic native coverage lives in
[map_downloads.m](../port/macos/tests/map_downloads.m). Run
`python3 tools/test_macos_map_downloads.py` to exercise in-process HTTPS fixtures
without game assets, credentials or external network.
