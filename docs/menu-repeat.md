# Menu repeat speed

Open **Settings → Game Settings → Controller → Menu Repeat** from the main
menu. During a game, open **Game Settings → Controller → Menu Repeat** from
Pause.

| Choice | First held repeat | Following repeats | Behavior |
| --- | --- | --- | --- |
| Original | 250 ms | 250 ms | Preserves the existing Xbox-derived input and menu behavior |
| Faster | 500 ms | 100 ms | Moves once immediately, then scrolls quickly after a deliberate hold |

**Original** is the default. Select **Accept** to save and apply the choice;
Cancel discards the draft. The preference belongs to the local installation
and applies to every local controller. It is outside player profiles and
host-selected game rules.

Menu Repeat applies to keyboard arrows, movement-key bindings, D-pad directions
and analog-stick navigation in menus, including the on-screen keyboard used to
name profiles and game types. **Original** retains its existing behavior.

With **Faster**, a fresh press moves once immediately. Holding the direction
repeats at 500 ms, then every 100 ms. Release the key or D-pad button, or return
the stick to neutral, to stop and reset the hold timer. The next press moves
immediately again; changing stick direction also starts a fresh hold. Keyboard
presses remain separate even when multiple press/release pairs arrive between
input polls. OS keyboard auto-repeat does not generate additional navigation.
The on-screen keyboard processes those discrete movements in order.

Faster stick navigation uses separate activation and release thresholds to
avoid treating small fluctuations as fresh presses. It retains the left/right
stick event types and their existing menu handlers. Confirmation and Back
buttons retain their existing behavior.

The delays are minimum elapsed-time thresholds. Input and menus run once per
rendered frame, so movement occurs on the first available frame after that
threshold. Frame scheduling can make the observed interval slightly longer;
Faster emits at most one repeat per held direction per update, without a burst
of catch-up movements after a stalled frame.
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

The original 250 ms thresholds and event dispatch remain in the reconstructed
Xbox input and menu path. Original also retains its existing keyboard press
latch, on-screen keyboard action reduction and stick-edge quirks. Faster uses
separate menu-only press tracking, repeat state and event storage; gameplay
packets, button hold counters and network rules retain their existing behavior.

Focused fixtures cover immediate presses, the 500/100 ms hold boundaries,
release/repress, direction changes, exact neutral, stick hysteresis, multiple
keyboard taps in one poll, on-screen name entry, live setting changes and the
unchanged Original/gameplay paths. Separate settings fixtures cover saving,
cancellation and the original UI layouts. Physical-controller timing and feel
require interactive playtesting; logic checks do not establish retail Xbox
runtime parity.
