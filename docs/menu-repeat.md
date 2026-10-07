# Menu repeat speed

The faster menu cadence is always enabled: a fresh press moves once, holding
for 500 ms begins repeating, and subsequent movements repeat every 100 ms.
There is no Menu Repeat setting. The behavior applies to every local controller
and remains outside player profiles and host-selected game rules.

Menu Repeat applies to keyboard arrows, movement-key bindings, D-pad directions
and analog-stick navigation in menus, including the on-screen keyboard used to
name profiles and game types.

A fresh press moves once immediately. Holding the direction
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
Menu navigation does not change the 30 Hz game simulation, movement, aiming,
controller dead zones or gameplay button hold timing.

## Configuration

There is no configuration switch. The legacy `input.fast_menu_repeat` key is
accepted silently in older files but ignored; it is no longer generated or
edited by settings.

## Scope

The faster path uses separate menu-only press tracking, repeat state and event
storage. Gameplay packets, button hold counters and network rules retain their
existing behavior. The fixed-default change is a source-only implementation;
no build, test or interactive validation was run for it.
