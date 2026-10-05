# macOS presentation stutter investigation

Solo Blood Gulch tests reproduced long presentation waits in both the native
Metal preview and the installed ANGLE build. Several frames spent approximately
one second inside `CAMetalLayer.nextDrawable`, before the native frame was
committed. Actual presentation callbacks stopped during that wait. Draw counts,
shader compilation, sampler misses and texture uploads did not explain those
particular pauses.

The explicit-guest preview launcher skips `host_menu_initialize_application`
in `host_main.c`. Visible windows could render while the application remained
inactive and had no key window. The native window-creation path now applies the
existing Regular activation policy **after SDL creates its application**, then
raises the visible window. This preserves `SDL3Application` and its graceful
Quit handler. Hidden native windows skip both calls; ANGLE and packaged GUI
startup keep their existing paths.

This corrects an observed preview startup condition. It does not establish the
underlying WindowServer/driver cause, or explain every foreground stutter
reported by regular-app players. Packaged GUI startup already initializes the
application. A request to activate the app is not proof of activation; the
runtime checks below recorded the actual active/key state.

## Observations

Tests used original Blood Gulch assets, scripted solo input and isolated saves.
They disabled screenshots during timing runs. Diagnostic overhead is included.
Muted runs still execute the original silent audio mixer, so they do not rule
out mixer contention generally. CLI tests skip native-menu download setup.

| Observation | Duration | Largest steady frame interval | Attribution |
| --- | ---: | ---: | --- |
| Installed ANGLE, original 30 FPS | 90 s | 37.360 ms | No interval over 50 ms |
| Installed ANGLE, Smooth Motion | 90 s | 758.821 ms | Existing CSV alone cannot attribute this frame |
| Installed ANGLE, wait probe, actual app inactive | 90 s | 1,045.002 ms | `nextDrawable`: 1,037.011 / 1,041.552 ms; presentation feedback stopped |
| Previous native host, wait probe, actual app inactive | 120 s | 1,028.149 ms | `nextDrawable`: 965.416 / 1,008.910 ms |
| Previous native host, temporary activation control, actual app active | 120 s | 31.108 ms | No interval over 50 ms |
| Rebuilt native host, observation only, actual app active | 120 s | 34.733 ms | No interval over 50 ms; no drawable wait over 20 ms |

The native rows use 3600x2338 backing, a 60 FPS cap and VSync off. The long runs
are limited observations, not a guarantee against intermittent stalls or
sustained 60/120 FPS certification. The original 30 Hz simulation remains;
the rebuilt guest is byte-identical to the prior fullscreen guest (SHA256
`e7d61574ab0f3dcbf15b94ebe76874947e874730936c3077794fab1034619216`).
The original local time clamp can discard excess wall time after a real pause,
which can make recovery appear as a jump.

Additional checks: 88 targeted CPU tests passed. A menu Command-Q key-equivalent
test was handled by the real SDL application's menu, logged `window closed`
and `Game exited (0)`, and returned host/guest exit 0. A hidden-window test
created a real hidden window, recorded zero raise calls, no visible/key window
or active application, and normal host/guest exit 0.

The texture-cache scan every 600 ANGLE frames did not coincide with the large
measured spikes; native excludes that scan. The measured ANGLE waits were also
not in `glClientWaitSync`. Shared audio locks, demand-driven asset IO and the
hosted-solo once-per-second address query remain candidates for other pauses,
without measured attribution. None justifies changing simulation timing.

## Local evidence and refreshed preview

The rebuilt no-ANGLE host proof is
`build/macos-metal/native-stutter-build-proof-attempt1/result.json`, SHA256
`346968859ea11f6c575c55dcf87e85d35ac8493929be45478e11e308fe961666`.
The observed build completed with exit 0 and binds 41 source/binary inputs.

Raw logs, temporary wait probes, their frozen sources/binaries and per-run JSON
are under `build/stutter-investigation/`. These local diagnostics interpose
wait calls and add presentation callbacks; they are excluded from the product
build. They preserve earlier captures rather than rewriting their conclusions.

Refreshed profiles are under `build/macos-metal/native-stutter-playtests-attempt1/`.
All five independent 20-second API-validation runs passed with host/guest exit 0,
no renderer/API errors and complete 3600x2338 captures under
`build/macos-metal/native-stutter-runtime-attempt1/`. The 13 BMP captures were
validated structurally; one selected image per profile was inspected for
world/weapon/HUD presence. This is not Xbox pixel parity certification.
The promoted chooser retains native 60/120 caps with VSync on/off and native
uncapped rendering. Normal human launches use the production binaries without
injected probes.
