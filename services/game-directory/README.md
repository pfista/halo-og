# Halo OG game directory

Cloudflare Worker + SQLite-backed Durable Object at `https://games.oghalo.com`.
It advertises public games; gameplay uses the existing direct P2P transport.
The shared desktop client integration is in the source: Mac, Windows, and Linux
query it in the original System Link menu and advertise hosted games by default.
Existing builds need an update; service deployment alone cannot change them.
See [client settings and playtesting](../../docs/system-link-directory.md).

Deployed and verified on October 4, 2026. Six local Workers-runtime tests and
the live registration/update/removal smoke check passed. The scoped deployment
token is stored in the `oghalo.com` 1Password environment without expiration.
It is also available as the `CLOUDFLARE_WORKERS_API_TOKEN` GitHub Actions
repository secret. Only deployment jobs should receive it; game clients use
the public directory without Cloudflare credentials. A deployment workflow is
still pending.

## API v1

| Request | Result |
| --- | --- |
| `GET /health` | Checks Durable Object storage and reports active game count |
| `GET /v1/games?network_version=11` | Lists unexpired games for that protocol |
| `POST /v1/games` | Creates a public listing and returns `id` and `lease_token` |
| `PUT /v1/games/<id>` | Replaces metadata and renews its 90-second lease |
| `DELETE /v1/games/<id>` | Removes the listing immediately |

POST and PUT use `Content-Type: application/json`. PUT and DELETE require
`Authorization: Bearer <lease_token>`. The token is returned only when created,
stored hashed by the directory, and never included in public listings. Keep it
in the host process; never put it in logs, URLs, or a shareable invite.

Example listing:

```json
{
  "name": "Friday Halo",
  "map": "downrush",
  "gametype": "Slayer",
  "player_count": 1,
  "max_players": 16,
  "network_version": 11,
  "netcode": "distributed",
  "platform": "macos",
  "build": "test-build",
  "open": true,
  "in_progress": false,
  "has_teams": false,
  "invite": "halo://join/<64 hexadecimal characters>"
}
```

Optional `map_sha256` is a 64-character SHA-256 digest. The directory treats it
as host-provided metadata; the client must verify a downloaded map itself.
Other optional fields are `platform`, `build`, `netcode`, and the booleans.
Required names use printable ASCII to fit the Xbox-style menus.

Public hosting registers once, updates every 30 seconds or when game details
change, and deletes when hosting ends or becomes private. A 404 on update means
the lease expired: register again. Changing the invite also requires a new
registration. Use a new private invite after removing a public listing.
Browse every 5–10 seconds while System Link is open, off the game thread; merge
with LAN discovery and deduplicate by the invite's host identity. Selecting a
listing uses `p2p_join_invite()` and waits for the actual host's LAN announcement
before joining. Download maps only from the configured trusted map catalog,
not from URLs supplied by a listing. A protocol number alone does not prove
gameplay compatibility.

## Authentication and limits

The lease authenticates ownership of a directory record. It does **not** prove
that the advertiser owns the invite or validate game details. Clients must
treat listings as untrusted and retain the existing P2P host authentication.
This v1 HTTPS API does not implement upstream's signed MQTT listing format or
automatically see games advertised only on MQTT. Those require client adapters.
The existing MQTT invite signalling is separate from this directory.

Listings expire after 90 seconds, including after host crashes. Alarms clean up
stored rows; every API read also filters expired entries. Limits: 4 KiB request
body, 256 active listings globally, eight per network address, and 12 new
registrations per address per minute. Network addresses are hashed internally
for quotas and not returned publicly. Quota limits return HTTP 429; a full
directory returns HTTP 503. Public reads do not expose lease credentials.

## Test and deploy

```sh
npm ci --ignore-scripts
npm test
python3 deploy.py --env-file /path/to/approved/1password-mount.env --check
python3 deploy.py --env-file /path/to/approved/1password-mount.env
python3 smoke.py
```

Tests run the real Workers runtime using pinned Miniflare, including a complete
90-second lease expiry. Deployment reads `CLOUDFLARE_WORKERS_API_TOKEN` from an
existing approved 1Password environment mount without echoing or copying it.
The R2 credential is separate. Account, domain, and service settings are in
`wrangler.jsonc`; the running service has no deployment credential or app secret.

The deployment token needs Workers Scripts Edit for the Halo account and Zone
Read, DNS Edit, and Workers Routes Edit only for `oghalo.com`. The deployment
script refuses to replace another service's domain or an existing unrelated
DNS record. Worker uploads update only `halo-og-game-directory`; SQLite rows
survive redeployments. Local deploys reuse the existing namespace and do not
apply new migrations.
