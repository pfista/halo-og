# Menu repeat speed

Open **Settings → Game Settings → Controller → Menu Repeat** from the main
menu. During a game, open **Game Settings → Controller → Menu Repeat** from
Pause.

| Choice | Repeat interval | Behavior |
| --- | --- | --- |
| Original | 250 ms | Preserves the existing Xbox-derived menu repeat timing |
| Faster | 100 ms | Moves through menus and the on-screen keyboard more quickly while a direction is held |

**Original** is the default. Select **Accept** to save and apply the choice;
Cancel discards the draft. The preference belongs to the local installation
and applies to every local controller. It is outside player profiles and
host-selected game rules.

Menu Repeat applies to held keyboard arrows, D-pad directions and analog-stick
navigation in menus, including the on-screen keyboard used to name profiles
and game types. Fresh button presses continue to bypass the repeat delay. The
choice changes the interval between held-direction repeats; it does not add a
separate delay before the first repeat.

The interval is a minimum elapsed-time threshold. Input and menus run once per
rendered frame, so movement occurs on the first available frame after that
threshold. Frame scheduling can make the observed interval slightly longer.
The setting does not change the 30 Hz game simulation, movement, aiming,
controller dead zones or gameplay button hold timing.

## Configuration

The preference saves in `config.toml` as `input.fast_menu_repeat`:

```toml
[input]
fast_menu_repeat = false
```

`false` selects Original; `true` selects Faster. An absent key uses Original.

## Scope and verification

This setting speeds held navigation. It does not repair separate input issues
that can lose rapid presses: keyboard press latches can merge events between
polls, the on-screen keyboard can reduce queued navigation to one action, and
an exact neutral analog-stick state can leave the previous menu deflection
recorded. Those behaviors require separate changes and fidelity review.

The original 250 ms thresholds are present in the reconstructed Xbox input
and menu code. Faster is an explicit optional departure from that timing.
Focused checks pass for both choices, independent fresh presses, held D-pad
directions, both analog sticks, on-screen name entry, live setting changes,
save failures and cancellation. Settings fixtures cover main-menu, pause,
campaign and split-screen layouts, including widths measured with the original
UI fonts. The existing gameplay button-hold counter retains its behavior.

The local Mac app builds and passes strict signature verification. Separate
hidden eight-second menu launches with Original and Faster exit cleanly,
rendering 226 and 238 frames. These launch checks do not measure navigation
latency. Physical-controller timing and feel require interactive playtesting;
isolated logic checks establish the threshold behavior without proving retail
Xbox runtime parity.
