# Digsite weapon lineage review

The converter identifies weapons by reviewed asset variants, independently of map names or cache formats. This review covers the 17 identities blocking the supplied Chillout, Damnation, Exhibit and Prisoner Digsite caches. Catalog 1.1.0 with profile 1.12.0 admits sixteen exact variants and authorizes one explicit omission: the reviewed Battle Rifle references. The preceding catalog/profile 1.0.0/1.11.0 admitted ten and left seven unverified; results from that earlier profile remain historical evidence.

A weapon name, a folder named Digsite, or a Bungie asset from a later game is not sufficient. The map authors describe [CE Digsite Multiplayer](https://steamcommunity.com/workshop/filedetails/?id=3477809506) as a fanmod mixing restored and new weapons. Modified shipped Halo 1 guns use the OG donor. Completions of established Halo 1 cut/NPC assets can retain the reviewed finish. The user additionally approves the exact Revolver/Magnum variant as a separate Custom Edition community exception; it is not labeled original Halo 1 content.

## Decisions

| Extracted weapon | Decision | Established ancestor or review basis |
| --- | --- | --- |
| `vehicles/banshee/mp_banshee gun.weapon` | canonical-stock | World model has the same 438 unique vertex positions as the verified Xbox plasma pistol, using its plasma-pistol material and meter topology; the pro/player customization is replaced with OG gameplay and assets. |
| `vehicles/rwarthog/rwarthog_gun.weapon` | original-completion | Despite its vehicle path, this player weapon has the same 408 vertex positions and 83 unique positions as the recovered 1999 Macworld Concussion Gun world model; modern first-person presentation completes that Halo 1 ancestor. |
| `weapons/battle rifle/battle rifle.weapon` | omit | The user explicitly excludes this reviewed Battle Rifle variant and authorizes omission of its references. No Halo 1 ancestor has been established for this 4012-vertex variant. Conversion must audit every omitted reference and must not substitute another gun. |
| `weapons/beam rifle/beam rifle.weapon` | original-completion | The official source contains the Halo 1 1999 Particle Beam ancestor. The user confirms this reviewed fanmod variant belongs to the previously discussed Halo 1 restoration set. Its finished mesh does not geometrically match the reviewed ancestor models; admission records the user-confirmed lineage and exact completion hashes, not an independently established mesh match. |
| `weapons/bolt action rifle/bolt action rifle.weapon` | original-completion | World model has the same 970 vertex positions and 211 unique positions as the recovered E3 2000 Halo 1 sniper rifle, including its material topology; this is the prerelease bolt-action ancestor, not a later Halo rifle. |
| `weapons/chaingun/chaingun.weapon` | original-completion | World model has the same 1228 vertex positions and 237 unique positions as the recovered 1999 Macworld chaingun; Digsite developers document rebuilding textures and first-person detail around that original model. |
| `weapons/excavator/excavator.weapon` | original-completion | The official source contains the Halo 1 1999 Excavator ancestor. The user confirms this reviewed DW2 finished variant is an allowed original restoration. Its different 3024-vertex world model is accepted as the user-confirmed finish, not an independently established geometry match. |
| `weapons/gravity_wrench/gravity_wrench.weapon` | original-completion | The completed world model contains all 379 handle vertices from the official Digsite Gravity Wrench first-person source after a rigid transform, with maximum positional error 0.00000117 Halo units; its two jaws have 445 unique vertices each, matching the source total of 890. The official developer account documents this refinement of the recovered 1999 Halo 1 weapon. |
| `weapons/grenade launcher/assault rifle.weapon` | original-completion | World model has the same 1872 vertex positions and 500 unique positions as the official Digsite restoration of the 1999 Halo 1 assault rifle grenade launcher; the official developer account identifies the recovered ancestor and its completed first-person implementation. |
| `weapons/machete/machete.weapon` | original-completion | The official source contains the Halo 1 1999 machete ancestor. The user confirms this reviewed 522-vertex player completion is an allowed original restoration. The finished mesh differs from the reviewed archival meshes; admission records the user-confirmed lineage without claiming a geometric match. |
| `weapons/magnum/magnum.weapon` | approved-community | This fanmod Revolver/Magnum variant is explicitly included by the user as a Custom Edition community exception. It is not classified as an original Bungie/Halo 1 asset and is not silently replaced by the OG pistol. The claimed first-Custom-Edition-mod history is the user statement, not independently verified provenance. Only this exact reviewed weapon and dependency closure are admitted. |
| `weapons/missile launcher/missile launcher.weapon` | original-completion | The official source contains the Halo 1 1999 missile-launcher ancestor. The user confirms this reviewed Pwndr SAM-launcher variant is an allowed original restoration. Some positions overlap the archival model, but the finished geometry and materials differ; admission records the user-confirmed completion rather than claiming full geometric correspondence. |
| `weapons/plasma_cannon/plasma_cannon.weapon` | original-completion | This player finish uses the original Fuel Rod firing effect, tail contrail and exhaust light. All 175 parsed contrail lines match the verified Xbox Fuel Rod asset except point generation rate 60 to 45. The author identifies its new ammo system, model and animations as changes to the original Fuel Rod; the original NPC ancestor lacks player presentation. The reviewed finish includes these authored changes, rather than claiming retail parity. |
| `weapons/sentinel beam/sentinel beam.weapon` | original-completion | Its projectile retains the original characters/sentinel/beam.contrail attack asset: all 161 parsed lines match the verified Xbox NPC beam contrail except point generation rate 1500 to 1200. The author identifies the Aggressor Sentinel weapon. New first-person art, animation and HUD complete that original NPC ancestor; this exact reviewed finish changes base damage from 1 to 4 and does not claim retail parity. |
| `weapons/smg/smg.weapon` | original-completion | World model shares all 750 unique vertex positions and material layout with the official Digsite completed first-person MP-99 model; duplicated vertices differ. The official developer account distinguishes this Halo 1 side-fed prototype from the later Halo 2 M7. |
| `weapons/space luger/space luger.weapon` | original-completion | World model has the same 1964 vertex positions and 225 unique positions as the recovered E3 2000 suppressed Halo 1 pistol; official developer accounts document the original model and later completion, predating ODST. |
| `weapons/speargun/speargun.weapon` | original-completion | The official source contains the Halo 1 1999 spear-gun ancestor, and the user specifically confirms this variant is the Halo 1 speargun. Its 1402-vertex player finish differs from the archival model. The explicit user-confirmed lineage admits only the exact reviewed completion hashes; it does not establish an independent geometry match. |

## Explicit user decisions

On October 8, 2026, the user approved the Revolver/Magnum as a community exception, specifically confirmed the Halo 1 speargun, confirmed the other previously discussed restorations, and excluded the Battle Rifle. The catalog records the exact statement with a `user-decision` receipt referencing this chat. The five newly admitted prototype finishes use recovered Halo 1 ancestor references plus this confirmation; their mesh correspondence was not independently established. The Revolver/Magnum has `ancestor: null` and `approved-community`, preserving that distinction in converter reports.

> So the revolver or Magnum. Magnum was the first Custom Edition mod made, so not exactly OG, but we’re still going to include it. Yes, the speargun is the Halo 1 speargun, and the others you’ve said, map. Basically, the only thing not is the battle rifle.

The user then chose explicit omission of the excluded Battle Rifle references. Its catalog entry has `outcome: omit`, `ancestor: null` and a separate approval receipt with the statement `Omit Battle Rifle references and report every omission`. The omission policy records each changed reference and preserves the other weapons and placements; it does not replace the Battle Rifle with a permitted gun. The decision is bound to the exact reviewed raw weapon and closure hashes, so changed variants still require review.

## Variant binding

The machine-readable [catalog](../tools/map_conversion/profiles/catalogs/halo1-weapon-lineage.json) binds each decision to the exact immutable extracted weapon SHA-256, model/type/label identity and complete recursive dependency SHA-256 inventory. All 17 raw closures were byte-identical across the four supplied maps. There are no map filename or map checksum allow rules. The same reviewed asset can therefore occur in any supported map. A modified model, projectile, HUD, sound or other dependency invalidates the review and returns a specific diagnostic.

The profile pins the catalog file SHA-256. Review additions require new entries or variants, updated evidence and a new profile pin. Inputs are verified before converter model/presentation transforms. The generated cache report records which ancestor and variant were used.

## Evidence and reproduction

The official source models were read as provenance only from [Digsite h1 at `4b326caf864b48c0b9c4db62338082691f2b645b`](https://github.com/digsite/h1/tree/4b326caf864b48c0b9c4db62338082691f2b645b). They are not copied into this repository or packaged with converter output. The repository [source naming guide](https://github.com/digsite/h1/blob/4b326caf864b48c0b9c4db62338082691f2b645b/data/digsite/readme.txt) identifies `99_mac`, `00_e3` and `_dig` as specific prerelease builds and later Digsite completion data.

Read-only Invader `edit --list-values` model dumps were compared by vertex-position multiset and unique vertex positions, rounded to five decimal places after cache decompilation; admitted geometric matches also share material layout. The full source tag hashes, rather than this floating-point comparison, enforce converter acceptance. The plasma pistol matches the verified Xbox donor geometry. Six recovered-weapon variants match the pinned official Halo 1 source geometry; the SMG duplicates some vertices but has the same complete unique position set.

The Gravity Wrench refinement was also compared to the pinned official Blender source as binary mesh data, without executing embedded content. All 379 handle vertices match after a rigid transform within 0.00000117 Halo units. Its 890 jaw vertices are articulated separately in the imported implementation. That source comparison and the official developer account support the reviewed refinement.

The Fuel Rod and Sentinel variants retain their original Xbox NPC attack assets. Full parser dumps of the original contrails differ in only point-generation rate (Fuel Rod: 60 to 45; Sentinel: 1500 to 1200). Their newly authored player presentation completes existing Halo 1 NPC weapons. The exact reviewed finishes include gameplay changes, including the author-documented Fuel Rod ammo system and Sentinel base damage 1 to 4; this is deliberate completion support, not a claim of retail gameplay parity.

[Digsite Deliveries](https://www.halowaypoint.com/news/digsite-deliveries) explains the recovered Halo 1 AR grenade launcher and MP-99 SMG, including newly authored first-person art and MCC-specific grenade reload support. [Cutting Room Corps](https://www.halowaypoint.com/news/cutting-room-corps) documents restoration work on the chaingun, gravity wrench and Space Luger. [Digsite Discoveries](https://www.halowaypoint.com/news/digsite-discoveries) documents recovering and finishing the suppressed pistol. Those accounts establish historical ancestors; a different fanmod variant still needs its own bound review.

No gameplay/app testing or distribution of official source payloads is part of this review. A successful lineage check does not establish V5 engine compatibility: converted models, animations, HUD layout and unsupported MCC features still pass the ordinary converter stages and can produce specific failures.

## Offline conversion result

The four supplied caches were rerun on 2026-10-08 with OG profile 1.11.0 and the
pinned catalog. Every map recognized all ten admitted variants and reported the
same seven `unverified` entries at `canonical_weapons`. None emitted a V5 cache;
the original map hashes remained unchanged. The converter did not remove the
unverified weapons or replace their authored pickups. The focused pipeline,
backend, asset, HUD, placement and lineage suite passed 198 tests. No app or
gameplay testing was performed.

Catalog 1.1.0/profile 1.12.0 was then run against all four original inputs on
2026-10-08. All four emitted Xbox NTSC V5 caches. Each recognized the sixteen
admitted variants, retained the reviewed Magnum community exception and omitted
the excluded Battle Rifle without substituting another weapon.

| Map | Output bytes | Battle Rifle reference omissions |
| --- | ---: | ---: |
| Chillout | 38,510,592 | 1 |
| Damnation | 42,037,248 | 3 |
| Exhibit | 41,541,632 | 1 |
| Prisoner | 40,099,840 | 1 |

Each map lost permutation 9 from `item collections/fiesta/fiesta_long`.
Damnation also lost permutation 0 from the single Battle Rifle collection and
its now-empty scenario pickup at `netgame_equipment[22]`. The receipts identify
each original tag, field and action. Native compiled-cache readback verified the
remaining placement graph, exact original weapon registry and authored-placement
capability in every output. The source files and converter code remained unchanged
during the batch.

The native Globals weapon list stays at its original fourteen roles. Additional
admitted weapons remain resident through a separate tag collection attached to
Xbox's implicit multiplayer Soul root; they do not consume new registry slots.
This avoids the native authoring limit of twenty registry entries and preserves
the engine's existing behavior for unregistered weapons.

The run record, complete diagnostics, source/output checksums and every omission
are under `build/digsite-approved-conversion-20261008-r23wcham`. The caches still
carry compiler warnings, including animation-count limits, absent LoD cutoffs,
zero node checksums and non-square particle sprite sheets. Conversion and native
readback passed; visual, audio, gameplay and network behavior remain untested.
All 238 focused pipeline, backend, asset, HUD, placement, residency and lineage
tests passed after the final generic dependency fix. Its negative control fails
for every supported source version (5, 6, 7, 609 and 13). The offline conversion
did not build or launch the app. At the user's subsequent request, the dual-renderer
app and all four exact converted caches were installed locally; the installed
signature and cache checksums were verified. Gameplay was not launched. Preview
images and editorial metadata still need review before distribution.

## What map preparers can provide

For a new unverified variant, supply its original Halo 1 ancestor and exact authoring source or provenance for the finished model/animation/HUD implementation. A community exception requires a specific user decision and exact variant review. The reviewed Battle Rifle now has an explicit, auditable omission decision; a changed variant still needs its own decision or a map revision. Do not silently substitute a rocket launcher, change another pickup's identity, or remove authored collections merely to pass conversion.

All 17 reviewed weapon paths were reachable through positive-weight authored Fiesta collections in these maps; this review does not assume they are unused.
