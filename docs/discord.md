# Discord activity

Halo OG publishes a Playing activity through the Discord desktop client's local
RPC connection on Mac, Windows and Linux. Presence stays active while the game
is open, including menus, campaign and local multiplayer. It also works with
`network.online = false`. Discord must be running with activity sharing enabled
for other people to see it.

When hosting an internet game, the activity includes the existing private party
and invite. Leaving that game removes its party and join secret while keeping
the Playing activity. Closing Halo OG closes its connection to Discord. An empty
`discord.application_id` disables the integration.

## Developer application

Discord gets the game title from the application's registered name. Setting
activity details or an image tooltip to Halo OG does not change that title.

1. Create an application named **Halo OG** in the
   [Discord Developer Portal](https://discord.com/developers/applications), or
   rename an existing application you own.
2. Copy the public **Application ID** from General Information. No bot token,
   client secret or OAuth login is needed for this local presence integration.
3. Set the existing `discord.application_id` in your local `config.toml` to that
   ID, then restart the game. To ship this application to every player, update
   the shared default in `port/linux/src/port_config.c` and the matching Discord
   URL scheme in `tools/macos_build.py`.
4. Optionally upload an image named `logo` under the application's Rich Presence
   art assets. The game uses that asset with the tooltip Halo OG.

The default application is **Halo OG**, `1556496882329460736`. Existing saved
configs holding the previous bundled Halo CE ID, `1553978809840050229`, use the
new application at runtime without rewriting that saved value. Empty and custom
IDs are preserved, and `HALO_DISCORD_APPLICATION` still overrides the file.

## Validation

Run the production presence fixtures without Discord or game data:

```sh
python3 -m unittest tools.test_discord_presence
```

After a Mac build, run the real game against a private mock Discord socket:

```sh
python3 tools/macos_discord_smoke.py
python3 tools/macos_discord_smoke.py --offline
```

These checks use isolated saves and settings. They verify the activity payload
and invite handling without changing the player's Discord activity. The title
and visibility still require checking the real Discord client with the configured
developer application and the player's activity-sharing settings.
