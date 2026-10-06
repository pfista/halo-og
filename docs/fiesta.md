# Fiesta starting equipment

In **Multiplayer → Edit Gametypes → select a game type → Item Options**, choose
**Fiesta** for **Starting Equipment**, then select **Uncut** or **All** for
**Weapon Set**. Finish **Save Changes** and select that game type for your match.
The existing default starting equipment and retail weapon sets stay unchanged.

Each spawn receives two different random weapons from the selected pool. A new
pair is chosen each time, with the loaded assets' authored ammo, charge, HUD and
weapon behavior. The host chooses and creates the pair; joining clients receive
the resulting inventory.

Selecting All reveals the menu spelling **Pfiesta**, including the saved game-type
card when its status line is available; the existing Hardcore Camo badge takes
precedence there. Changing to another weapon set restores **Fiesta**. This is a display-only
Easter egg; it uses the same Fiesta selection, saved value and gameplay rules.

| Weapon Set | Fiesta pool |
| --- | --- |
| Uncut | All nine documented recovered pre-release weapons: SMG, assault rifle with grenade launcher, Chaingun, Excavator, Gravity Wrench, Machete, Speargun, Space Luger and Missile Launcher, including weapons absent from the original map. |
| All | The full playable arsenal, including launch weapons, recovered weapons and later community additions, plus any additional playable weapons authored in the selected map. Weapons do not need a world pickup or starting-equipment placement to qualify. |
| Existing retail choices | The existing eight-weapon Fiesta pool: assault rifle, pistol, plasma pistol, plasma rifle, needler, shotgun, sniper rifle and rocket launcher. |

Uncut deliberately uses reviewed weapon identities. A map's modern additions,
undocumented prototypes, or vehicle guns do not become historical content merely
because the map includes Digsite assets. Historical identities can use reconstructed
first-person models/animations and later map-author changes; Uncut does not claim
these were complete playable weapons hidden on the retail Xbox disc. The recovered
list is supported by [Digsite Deliveries](https://www.halowaypoint.com/news/digsite-deliveries),
[Cutting Room Corps](https://www.halowaypoint.com/news/cutting-room-corps),
[Digsite Discoveries](https://www.halowaypoint.com/news/digsite-discoveries), and the
[pinned recovered weapon source](https://github.com/digsite/h1/tree/4b326caf864b48c0b9c4db62338082691f2b645b/tags/digsite/weapons)
with its [original-build provenance](https://github.com/digsite/h1/blob/4b326caf864b48c0b9c4db62338082691f2b645b/data/digsite/readme.txt).

All excludes objective items, vehicle/extra-inventory weapons and weapons without
a player first-person model and animation interface. The known Digsite conversion
alias for the flamethrower counts once when its canonical weapon is also present.
The pool has no fixed eight- or ten-weapon array limit.

## Weapons absent from the original map

Halo loads one map's tag and resource dependencies at a time. Expanded Fiesta
automatically selects a private full-arsenal derivative of the chosen map, stored
under `maps/arsenal/v1`. The app first uses a complete verified pair in the active
game-data folder; on Mac it can also use the managed maps folder. The menus and network game
retain the original map name. Original caches remain untouched. Custom/Generic
equipment and the original eight-weapon Fiesta pool load the original cache.

[The weapon-pack authoring tools](weapon-pack-maps.md) import the global arsenal
into a separate namespace and add palette references without adding world
placements or replacing retail weapon/HUD definitions. A Fiesta-only player
animation graph supports additional labels, including Speargun and Missile
Launcher. The original player biped/model and animations remain unchanged in the
original cache. Shared animation timing/event fields are preserved, except the
imported graph uses a one-frame Warthog passenger rifle idle pose instead of the
original 40-frame idle clip.

Before map loading, the app checks the derivative's generation, global weapon
list, full cache digest, original-map digest, player reference and actual eligible
weapon definitions. Missing, stale or partial arsenals produce a recoverable
message and preserve the previous lobby selection. They cannot silently start
Uncut with the normal assault rifle and pistol. An individual spawn's
allocation/attachment failure still preserves the existing inventory.

Selecting an expanded Fiesta map or game type automatically requests its matching
arsenal when local content is missing and downloads are enabled. The request uses
the SHA-256 of your actual original map, so it cannot substitute another geometry.
The downloading message leaves your current selection unchanged; select the map
or game type again after the download completes. On Mac, Settings shows progress,
and **Check Maps** retries failed or previously unavailable requests. A complete
verified local arsenal remains usable with downloads disabled or offline.

A joining client requests the host's exact full cache digest, keeps incoming game
settings pending and continues automatically after verification. It sends a
reliable download heartbeat every 15 seconds, which keeps a slow late join alive
without declaring map readiness. Waiting expires after 15 minutes; leaving the
lobby cancels joining, and a changed host offer discards the previous pending
settings and start signal. Background content already downloading may still
finish. No map load or BEGIN takes effect with unverified assets.

Expanded Fiesta streams held and visible weapon textures through the ordinary
prediction paths, instead of prewarming the entire arsenal in one frame. It uses
a bounded 32 MiB native texture cache to accommodate the imported assets.
Ordinary maps, menus and campaign retain the original 22 MiB cache; transitions
restore that budget, and failed allocations preserve the previous arena.

The generation-one arsenal contains 31 playable definitions, including all nine
Uncut weapons. Original and imported versions of the same recovered identity
count once, using the global version; the known flamethrower compatibility alias
also counts once. Additional map-authored weapons remain eligible in All.
All includes the distinct multiplayer Needler, melee Skull, Longshot rocket
launcher and Temple's empty rocket launcher variant. Their authored ammo and
weapon settings are retained; the empty launcher starts without ammunition.

## Other rules and compatibility

Existing Weapon Set choices still control world pickups independently of their
original Fiesta pool. Uncut and All select the new Fiesta pools and leave world
pickups as authored. The existing grenade rules, including Infinite Grenades,
remain in effect. Choosing Uncut or All with Custom/Generic starting equipment
retains those starting-equipment rules.

Fiesta works with the existing multiplayer modes and is selected before the
match. Starting Equipment and Weapon Set cannot change during the match.
Performance presets and other settings preserve them. Copy, rename, save-as and
reload use the existing signed 104-byte game-type format. Existing saved IDs
remain unchanged; Uncut and All append IDs 11 and 12, preserving the hidden
No Grenades ID 10.

Every player needs a build supporting Fiesta to enter a Fiesta match. Expanded
Fiesta additionally requires the global-arsenal capability and matching full
cache digest before settings are applied or maps are precached, including normal
and late joins. Name-only map readiness is insufficient for these matches. This
capability is separate from saved Performance options. Older supporting builds
continue using their original capability frames for ordinary games.
The download-wait capability is acknowledged separately. A previous global-cache
host can still admit clients with its exact assets already installed; waiting
for missing content requires an updated host. The v11 game record, saved aid
flags, and version-one through version-four capability frames retain their layouts.

Production-function fixtures cover menu callbacks/help, signed saves, every
ordered pair in expanded pools, resource prediction, host/client gating,
placement remapping, equipment replacement and failure recovery. They do not
establish live cross-platform play, every imported weapon's usability, or
subjective gameplay feel. Weapon-pack build verification is distinct from native
map/HUD/audio/multiplayer validation.
Download/retry fixtures additionally cover complete-pair root selection, original
hash memoization, exact revision requests, pending settings and start cancellation,
and heartbeats that cannot mark a downloading peer ready. These new fixtures and
the automatic delivery path still require platform execution after the initial
source push; the native evidence below predates automatic downloads.

The existing native `debug.network_test` harness accepts `fiesta uncut` and
`fiesta all` as diagnostic variant names. They compose Slayer with Fiesta and
the corresponding set before normal host setup, allowing isolated multiplayer
smokes using the same automatic arsenal selection as the menus. They are not
additional menu game types.

## Local validation

Production fixtures exercise every ordered Uncut pair with all nine imported
definitions on a stock map, imported/original deduplication in either cache order,
original-pool prediction, UI failure recovery and capability/digest checks. Asset
build reports verify all 54 prepared stock/community maps, eligible weapon
identities, animation support, source preservation and cache budgets.

Two isolated native peers on one Mac verified automatic logical-map selection on
Prisoner for Uncut and All. A separate Uncut run recorded 24 matching fresh
respawns covering all nine recovered identities. All also passed with Native
Metal, including imported weapons using BC2/BC3 cube textures. These checks do
not establish physical cross-platform multiplayer or every weapon's gameplay
behavior.

The final texture-cache build also passed Uncut with ANGLE and All with Native
Metal on Chill Out Digsite, the largest prepared cache. Both peers rendered
frames, agreed on each player's two-weapon inventory and exited cleanly without
texture-cache warnings. Production lifecycle fixtures separately verify the
32 MiB expanded budget, restoration to 22 MiB and allocation-failure recovery.
