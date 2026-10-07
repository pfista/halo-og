# Halo OG invite links

On `pfista/open-ce`, shared invite text is
`halo://join/<64 hexadecimal digits>`, which stock OpenCE understands. The whole
URI is 76 ASCII bytes. The OS handler uses the isolated `halo-og-opence://`
scheme. Delivery buffers hold 87 bytes including the terminator, enough for
the longest accepted private URI.

The shared parser accepts `halo://`, legacy `halo-og://`, and private
`halo-og-opence://` text for copied invites and explicit launch arguments. Mac,
Android and iOS register only the private scheme; paste shared invitations into
the game or use an explicit launch argument. Desktop process forwarding uses
port 47317 and a private local authentication context, so another Halo OG or
OpenCE instance cannot consume its delivery. Peer authentication, signaling,
passwords and transport framing retain the pinned upstream protocol.

| Platform | OS delivery |
| --- | --- |
| Windows | Per-user Unicode registry command with quoted executable and URI arguments. |
| Linux | Halo OG desktop entry and `xdg-mime` registration; escaped executable path and a separate URI argument. |
| macOS | Bundle URL types, SDL opened-URL event, then the instance's private invite file. |
| Android | `ACTION_VIEW` launcher delivery at creation and when reused; atomic invite file, then the existing `singleInstance` game activity. |
| iOS | Bundle URL types and SDL UIKit scene delivery at startup and while running, then the app's private invite file. |

Desktop Discord uses the separate `discord-1556496882329460736` launch scheme.
Its join secret remains the bare 64-digit payload. Mobile ports do not use the
desktop Discord RPC integration.

## Regression checks

These checks compile the production parser, link generator, desktop command
registration and forwarding functions with controlled OS calls. They also
compile the shared directory record for all native/guest ABIs, including the
unchanged player/score field offsets.

```sh
python3 -m unittest tools.test_p2p_invites tools.test_p2p_handoff \
  tools.test_url_scheme_registration tools.test_invite_layout \
  tools.test_discord_presence tools.test_mobile_invites \
  tools.test_guest_build_dependencies
```

The Android lifecycle check requires a JDK and executes the production Java
writer and launcher methods. Linux additionally launches a temporary harmless
probe through `gio` to verify desktop `Exec` parsing. Windows registers a
disposable test scheme and opens its probe through `ShellExecute`, then removes
the test registration. The Build and Apple CI jobs run the applicable checks
on their native runners.

For actual iOS URI delivery, build the simulator host and run:

```sh
python3 tools/ios_invite_smoke.py
```

This installs a small probe into a disposable simulator, uses the real SDL
UIKit delegate and native invite bridge, and checks complete links at startup
and in the same running process. Tap Open when iOS asks to open the invite in
Halo OG, using the named isolated simulator in Simulator or Device Hub. It
needs no Xbox data and does not join a game.
It does not establish physical-device gameplay or cross-platform matchmaking.

## Upgrade boundaries

Deploy the updated [game directory worker](../services/game-directory/README.md)
before distributing new clients. It accepts both stored invite formats and
returns the requested scheme to new clients while preserving older clients'
responses.

macOS uses `local.halo.og`; iOS defaults to `local.halo.og.ios`. Existing iOS
installations can keep their provisioned `--bundle-id` to retain their container.
Android keeps its existing `com.halo.decomp` package and data container; an
upstream APK using that package cannot be installed alongside it.
