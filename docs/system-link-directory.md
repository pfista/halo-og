# Public games in System Link

Desktop builds containing this change use **https://games.oghalo.com** by default
on macOS, Windows, and Linux. Existing published builds do not gain it until
updated. It uses the original Xbox-style **Multiplayer → System Link** menu.

1. Use the same new build on both machines. Start with Blood Gulch, Slayer,
   and **Performance Options → Stock**, with Input Delay and Hardcore Off.
2. On the host, open **Multiplayer → System Link**, select a profile, create a
   game, and choose its map/mode. Leave Halo running.
3. On the other machine, open **Multiplayer → System Link**. The host should
   appear promptly after entering the list; listings then refresh about every
   ten seconds while the list is visible and Halo is in the foreground.
4. Select the game. **Connecting…** means the client is establishing the P2P
   connection. When the real host advertisement arrives, the normal lobby opens.
5. Start the match after everyone joins. For an Internet test, use separate
   networks, such as home Wi-Fi and a phone hotspot. A same-LAN test also checks
   that one host appears only once.

The server lists games; it does not relay gameplay. Some NATs/firewalls still
prevent the existing direct connection. A failed connection returns to the list
after 30 seconds. Private invites and LAN discovery remain available. Compare
invite and directory results when reporting a connection failure.

Public listings include the game name, map, mode, player counts, and an invite
usable by anyone who can see the listing. A host renews its listing every 30
seconds and when metadata changes. Stopped/crashed games disappear within 90
seconds; ordinary hosting disposal requests immediate removal.

Entering the list or returning to Halo requests a fresh listing immediately,
subject to network latency and any server retry delay. Leaving the list,
joining a game, hiding/minimizing Halo, or switching to another app pauses
listing requests. A public host still renews its listing during gameplay and
while Halo is in the background so late-join games remain discoverable.
New games created while the list is already open appear on the next ten-second
refresh. Failed requests use increasing retry delays with jitter and respect
the directory's numeric `Retry-After` header; reopening the list cannot bypass
that delay.

## Private hosting and other directories

Close Halo and edit the existing `[network]` section of `config.toml`:

```toml
[network]
online = true
public_games = false
directory_url = "https://games.oghalo.com"
```

Do not add a second `[network]` section. `public_games = false` keeps your hosted
game off the public directory while allowing public browsing. Share your private
invite only with the intended players. A previously public invite remains known
to people who saw it; restart hosting to create a fresh invite.

Set `directory_url = ""` to disable both directory browsing and advertising, or
replace it with another compatible HTTPS API v1 service. Restart after a URL
change. Multiple directories and upstream MQTT listing adapters are future work;
this service does not automatically collect upstream-only listings.
`online = false` disables Internet play, including this directory, while retaining LAN.

On Mac, use **Open Saves Folder** to find `config.toml` in Application Support.
On Windows/Linux it is beside the executable. There is no new OS settings browser.
Background map downloads keep their own trusted catalog and settings; directory
records cannot supply arbitrary download URLs.

## Implementation and validation

The shared native worker performs HTTPS requests off the game and P2P threads.
Mac uses NSURLSession, Windows uses WinHTTP, and Linux uses its existing Mbed TLS
transport. Responses are bounded, certificates/hostnames are verified, and
directory requests never follow redirects. Linux serializes TLS with map/update
transfers because its current PSA backend has no threading support; a slow map
download can temporarily delay directory refresh/heartbeats.
Discovery requires a rendered, visible list update within the preceding second.
Entry/focus generations ensure quick reopening triggers a fresh request and
prevent an older request from repopulating a new page visit. Healthy public
hosts renew every 30 seconds; changed metadata is coalesced to at most one
update per five seconds. Failed lease renewals retry with a shorter backoff
than failed browsing/registration, unless the server requests a longer delay.
The service filters expired listings in read queries and leaves physical
cleanup to its expiry alarm and registration transaction.

Only compatible protocol 11/optional PB-capable listings are displayed. Public
metadata is untrusted: selecting a row must establish the authenticated P2P peer
and receive its real advertisement before the existing join/compatibility checks
run. Cached records expire against the directory server's time, avoiding local
clock skew. LAN, tunnel, and directory records are deduplicated by the Xbox
address's host identity. The actual network advertisement takes priority so its
current game rules remain visible. Directory-only rows show a score limit when
the host supplies it; older hosts' missing score metadata is left blank rather
than displayed as zero. A failed listing withdrawal retains the lease for retry
or renewal, preventing a restart from creating a second live listing.

Tests cover production parsing, response caps, lease headers, authenticated-peer
and actual-advertisement gating, LAN deduplication, timeout and cancellation,
visible/foreground-only polling, immediate entry/resume, throttling, stale
responses, host renewal in the background, and expiry without read-side cleanup.
The local Mac build, live native HTTP smoke, and real Mac host registration and
renewal passed. A two-instance invite smoke did not establish a match; physical
two-Mac and cross-platform gameplay remain required playtests. Compilation and
directory registration alone do not prove that a given NAT pairing can join.

Run `python3 -m unittest tools.test_game_directory tools.test_game_directory_worker tools.test_game_directory_ui tools.test_macos_input tools.test_download_transport_limits tools.test_macos_directory_http tools.test_macos_service_imports`
for fixtures. On Mac, `python3 tools/macos_directory_smoke.py` tests the live
native HTTP adapter and removes its synthetic listing. Service details are in
[the directory service README](../services/game-directory/README.md).
