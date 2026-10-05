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
  "score_limit": 50,
  "oddball_variant": false,
  "invite": "halo://join/<64 hexadecimal characters>"
}
```

Optional `map_sha256` is a 64-character SHA-256 digest. The directory treats it
as host-provided metadata; the client must verify a downloaded map itself.
Other optional fields are `platform`, `build`, `netcode`, and the booleans.
`score_limit` is an optional integer from 0 to 32767; absence means the host
did not supply its score limit, not a zero limit. `oddball_variant` marks
Juggernaut's frag-based scoring instead of the usual Oddball minutes.
Required names use printable ASCII to fit the Xbox-style menus.

Public hosting registers once and renews every 30 seconds. Changed game details
are coalesced into updates at least five seconds apart. Hosting ending or becoming
private requests immediate deletion. A 404 on update means the lease expired:
register again. Changing the invite also requires a new
registration. Use a new private invite after removing a public listing.
If withdrawal fails, retain its lease and retry before registering a different
invite; resuming the same invite renews its existing listing.
Fetch immediately when the rendered System Link game list opens or regains
focus, then refresh every ten seconds while that list is visible and focused,
off the game thread. Stop browsing when the list closes, a join begins, gameplay
starts, or the app loses focus. Failed browse requests retry with increasing
delays from five seconds to one minute, with jitter; a numeric `Retry-After`
may extend that delay up to five minutes. Merge with LAN discovery and
deduplicate by the invite's host identity. Selecting a
listing uses `p2p_join_invite()` and waits for the actual host's network advertisement
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

Listings expire after 90 seconds, including after host crashes. List and health
reads filter expired entries without cleanup writes, even when an alarm is
delayed. Alarms remove expired rows; registration also cleans up expired rows
and stale quota counters within its transaction before checking limits.
Limits: 4 KiB request body, 256 active listings globally, eight per network
address, and 12 new
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
90-second lease expiry and expired rows held until their scheduled alarm, proving
that reads hide them without deleting them and that expired leases cannot be
renewed. Deployment reads `CLOUDFLARE_WORKERS_API_TOKEN` from an
existing approved 1Password environment mount without echoing or copying it.
The R2 credential is separate. Account, domain, and service settings are in
`wrangler.jsonc`; the running service has no deployment credential or app secret.

The deployment token needs Workers Scripts Edit for the Halo account and Zone
Read, DNS Edit, and Workers Routes Edit only for `oghalo.com`. The deployment
script refuses to replace another service's domain or an existing unrelated
DNS record. Worker uploads update only `halo-og-game-directory`; SQLite rows
survive redeployments. Local deploys reuse the existing namespace and do not
apply new migrations.
