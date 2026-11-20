# Halo OG Mac menu, local data and releases

The native AppKit menu runs in the game's process. Its monochrome helmet opens
Settings, changes fullscreen immediately, selects game data, opens saves and
controls, checks updates, and quits through the normal game exit path. Settings
is also available with Command-comma; Control-Command-F toggles fullscreen.
Fullscreen hides the menu bar and Dock while the game has focus. Release the
captured mouse with F12 and move it to the top edge to reveal the menu bar.
Opening native settings or leaving fullscreen restores normal system controls.
The existing Dock icon is retained; `port/macos/Helmet.svg` generates a vector
template PDF.

## GitHub Actions DMG

The [macOS DMG workflow](https://github.com/pfista/halo-og/actions/workflows/macos-dmg.yml)
builds on relevant `main` pushes and manual runs. It produces the
`halo-macos-arm64-dmg` artifact with the DMG, installation notes, build provenance
and checksums. Use [player installation](playtesting.md#mac) for download/run
instructions. Artifacts expire after 14 days.

CI uses public dependencies and checked-in SDK declarations. It excludes game
data, private inputs and checkout paths, and verifies every Mach-O architecture
is ad-hoc signed without developer certificates. The displayed name is Halo OG;
the bundle ID is `local.halo.og`. CI builds embed Halo's
update feed and public key (`--update-feed`), so a published build installs
later releases through Sparkle. Neither value is a secret, and no developer
identity is involved. Builds are not notarized, so macOS still asks the player
to approve the first launch of a new installation; see
[client updates](client-updates.md).

## Manual testing prerelease

The fork's **Publish testing prerelease** workflow runs only when explicitly
dispatched on `main` with a new `vMAJOR.MINOR.PATCH` tag, for example `v0.3.1`.
The release title is `Halo OG v0.3.1`; tags have no testing or feature suffix.
Testing releases still use GitHub's prerelease flag. It publishes the latest
`main` commit using successful **Build** and **macOS DMG** outputs and an
**Apple regression checks** result from that exact commit.
It does not rebuild, sign with a personal identity, or include game data.

The version after `v` must match `HALO_OG_VERSION` in
`port/linux/include/halo_og_version.h`. Before building `v0.3.1`, change that
header to `0.3.1` and commit it, then wait for matching platform builds. The
examples below describe that future release; they do not bump the current
version or relabel an existing build. Existing tags and assets remain immutable.

The historical `test-v0.3.0-net11-maps1` testing release added automatic complete-map
downloads on Mac, Windows and Linux. Fresh Mac settings enable downloads;
previously saved opt-outs remain off. After compatible original NTSC data is
selected, all 40 approved community maps queue in the background. The older
`test-v0.3.0-net11-dmg2` Mac build still requires opt-in, and its Windows/Linux
builds use manual community maps. See [player setup](playtesting.md#community-maps)
for platform controls and the current download links.

After release authorization, wait for both builds and Apple regression checks
to succeed on the same latest `main` commit. In GitHub Actions, choose
**Publish testing prerelease → Run workflow**, select `main`, and enter an unused
version tag such as `v0.3.1`. This explicit dispatch publishes
a prerelease; code pushes do not publish. Prepare/collection uses a read-only
token; the separate publication job alone receives `contents: write`.

The helper rejects another source revision, non-main runs, unsuccessful runs,
missing/expired artifacts, changed hashes, unexpected Mac contents, and reused
tags/releases. Before publication it rechecks latest main, build provenance and
the recorded Apple regression run. Older candidates without that check's
provenance must be prepared again.
If main advances while publication is queued, dispatch again after the new
commit's builds finish. Workflow artifacts must still exist: Mac artifacts last
14 days and other platform artifacts last 3 days. Manually run the required
workflows on latest main if checks/artifacts are missing, including after a
documentation-only or service-only commit that skips native CI.

The prerelease includes:

- `Halo-OG-macos-arm64.dmg`, `macos-README.txt` and `macos-BuildInfo.txt`.
- `halo-windows-release.zip`, `halo-linux-release.zip` and `halo-android-release.zip`.
- `SHA256SUMS` and `provenance.json` with source SHA, network protocol, CI run IDs,
  artifact IDs and SHA-256 hashes. Debug builds are omitted.

Release notes start with a short description and direct platform download links,
followed by an **Overview** with a short prose paragraph and player-facing
highlight bullets, then the full commit list. Both the annotated tag
message and release notes include concise commit subjects with short SHAs since
the previous reachable Halo OG release tag, plus a GitHub compare link for that
range. The platform asset filenames and download-link layout stay unchanged.

Follow the [release-notes authoring prompt](releases/README.md) to review the
entire range and explain the main features and fixes in player terms. Before
building, commit `docs/releases/<tag>.json` containing `summary` and `highlights`.
Preparation reads this overview from the exact source SHA, records it in
`provenance.json`, and renders the same substantive overview in the annotated
tag and release notes. Missing or invalid overviews stop preparation; there is
no automatic fallback to recent commit subjects. Publication verifies the
overview against that source again, so editing a prepared candidate cannot
silently replace it.

History comes from GitHub's published Halo OG releases, including legacy
`test-v...` releases for the first version-only tag. The nearest ancestor is
selected regardless of publication order; upstream build/launcher and content
tool tags are excluded. New version-only releases must increase the version.
When no recognized published Halo OG release exists, the first release uses
the pinned October 2, 2026 baseline commit
`6c1f1ae8b9caa4b1cd06c6d1a1fa855127b682ef` (17:12 America/Panama).
The notes label it as a baseline commit, not a previous release tag. This
one-time fallback requires the same strict ancestry and complete comparison;
after a recognized release is published, normal release history always wins.
Highlights are authored for the release's significant player-facing changes;
the complete list includes merges and every commit in the range. Publication
rechecks that history.
Notes must fit the 16 KiB limit in existing desktop clients; oversized complete
changelogs are rejected rather than silently truncated.

Historical download example for the `test-v0.3.0-net11-maps1` tag:

```text
https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-maps1/Halo-OG-macos-arm64.dmg
```

The URL becomes usable only after that tag is published. Public release assets
require no GitHub sign-in and are retained until the release is deleted.
Prereleases cannot be GitHub's “Latest” release, so share the tagged URL instead
of `releases/latest/download`. Tags and assets are not overwritten. A failed
publication can leave a new tag or incomplete release; inspect that state and
use a fresh tag for a retry instead of overwriting it.

Testers should use the same tag across platforms. Current source uses protocol
**11**, which cannot join protocol 10 sessions; metadata extracts the actual
protocol from the selected source instead of assuming it from the tag name.
The DMG is Apple Silicon/macOS 26+, ad-hoc signed and unnotarized. Windows builds
are portable x86 executables; Linux builds still need the documented 32-bit
OpenGL/SDL/audio runtime dependencies. Android signing depends on the existing
CI signing configuration. Build success does not establish cross-platform play.
Fork CI builds disable the upstream installer that targets cybersecurity's
different build. New setup builds add Halo OG notices with manual downloads;
the published `test-v0.3.0-net11-gameplay1` predates those notices. Mac builds
from `v0.5.2` and earlier have no update feed and need one manual installation
of a later release.

After the prerelease is published, [advance the Mac update feed](#publishing-a-mac-update)
so installed copies are offered it.

Read-only local preparation and verification are available without publication:

```sh
python3 tools/testing_release.py prepare --sha FULL_LATEST_MAIN_SHA \
  --tag v0.3.1 --directory /tmp/halo-testing-candidate
python3 tools/testing_release.py verify --sha FULL_LATEST_MAIN_SHA \
  --tag v0.3.1 --directory /tmp/halo-testing-candidate
```

Use Python 3.11 or later, a fresh directory and the authenticated GitHub CLI. `prepare` downloads the
existing artifacts and writes a candidate; only the explicit `publish` command
creates a tag/release. The workflow uses that command in its publication job.

GitHub documents [artifact download access](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts),
[artifact metadata and download](https://docs.github.com/en/rest/actions/artifacts),
[workflow source/run filters](https://docs.github.com/en/rest/actions/workflow-runs),
and [prerelease/latest behavior](https://docs.github.com/en/rest/releases/releases).

## Independently supplied data

After the initial game build and public dependency setup, build without a local
checkout path:

```sh
python3 tools/macos_build.py --host-only --no-data-path
python3 -m venv build/macos/dmg-packaging-venv
build/macos/dmg-packaging-venv/bin/python -m pip install -r tools/macos-dmg-requirements.txt
build/macos/dmg-packaging-venv/bin/python tools/macos_release.py local-dmg
```

The resulting `build/macos/Halo-OG-<version>-local.dmg` uses the app's canonical
product version and is a local test artifact. It has
no notarization ticket and is not a verified public release. It includes an
Applications shortcut and the app, without maps, ISOs or a local checkout path.
The Finder window has a Retina background, positioned app/folder icons and a
drag arrow. Rendering uses macOS's native SVG support; the Python dependencies
write Finder metadata without scripting Finder and are only used at build time.

To repackage an existing signed app, pass `--app "/path/to/Halo OG.app"` and a
fresh `--output` filename to `local-dmg`. Packaging checks every bundle file,
directory permission and symlink target against the source and verifies the
copied signature. It preserves the app's build information and does not rebuild
the game or change user data. Existing output files are never replaced.

The Mac app includes SDL3, Sparkle and the compiled engine and uses the system
Metal framework. First launch accepts the user's locally obtained
original Xbox Halo XISO/ISO, or extracted game folder (its `maps` subfolder also
works). Original data is imported locally and is not uploaded. Selecting
compatible original NTSC data enables background community downloads when the
saved download preference allows them. Disc imports copy maps to a fresh
directory in:

```text
~/Library/Application Support/Halo OG/Game Data/<import-id>/maps/
```

Header checks require a supported Xbox release, including `ui.map` and `a10.map`.
PC/Custom Edition/MCC maps and mixed releases are rejected. This checks the
format, not completeness of every level: use a complete set from one disc.
Failed imports preserve the previous selection and data. Successful imports
retain earlier imports rather than deleting the person's files.

Extracted-folder selection offers **Copy and Manage**, **Use This Folder**, or
**Cancel**. Managed copies use the same Application Support layout and preserve
the original files. Community downloads have their own Settings control and a
verified library under `Community Maps/maps/`; user-supplied files take priority.
See [managed storage and map downloads](community-maps.md#managed-storage-and-downloads) for the catalog,
missing-map readiness flow and hosting configuration. The selected publisher
is `https://dl.oghalo.com`. Fresh settings enable all 40 complete-map downloads
(about 863 MiB); existing saved opt-outs remain off. Verified maps persist
outside the app and remain usable offline. Hosted caches include their required
embedded Halo dependencies; separate disc, stock, campaign and UI map files are
not hosted. Local package reconstruction is set aside for this release path.

`macos-settings.json` in the Halo OG Application Support directory records the
data/source-image paths and fullscreen preference. Saves, profiles, cache and
`config.toml` stay in their established locations outside the signed app.
Settings, file-picker sheets and disc imports return control to SDL while the
game is running, so the simulation and networking continue. First-launch data
selection can wait before the engine starts. Data changes apply on the next launch.
Advanced Settings opens `config.toml` in TextEdit; restart to apply control edits.

Existing `HALO_DATA_ROOT`, `HALO_SAVE_ROOT` and `HALO_WINDOWED` development
overrides remain available. Passing an explicit guest image bypasses the native
chooser and preserves the command-line test runner behavior.

## Sparkle configuration

Sparkle 2.10.0 is pinned by checksum in `port/macos/dependencies.json`. It starts
only with a valid HTTPS feed and 32-byte public Ed25519 key in the app's
`Info.plist`. CI builds embed both with `--update-feed`; a plain local build
omits them and keeps the GitHub notice below. Standard Sparkle UI handles update
consent and downloads. Scheduled reminders wait in the menu while playing;
installations requiring a relaunch wait for clean game exit. Sparkle replaces
the app only. Maps, saves, profiles and settings live outside the app and are
untouched.

When no Sparkle feed/key is embedded, **Check for Updates…** opens Settings
with Halo OG's GitHub release status, and **Download Update…** opens the Mac
download in the browser. The checkbox **Automatically check for updates** checks
metadata only; it does not install the download. Clean matching-main CI builds
record source SHA/date for comparisons; local builds can open the releases page
manually. See [client updates](client-updates.md) for the other platforms.

Update hosting is set in the non-secret checked-in file
`port/macos/release-config.json`:

| Field | Value |
| --- | --- |
| `feed_url` | `https://dl.oghalo.com/updates/mac/testing/appcast.xml`, the testing channel's appcast |
| `public_update_key` | Halo's public Sparkle Ed25519 key |
| `download_base_url` | `https://dl.oghalo.com/updates`; a release's DMG is `mac/<build>/Halo-OG-<version>.dmg` beneath it |

Updates share the community maps' R2 account, bucket and public origin from
`tools/map-publisher.json`; an object's key is its public URL path. No release
has been published to this feed yet. No new application environment variables
or committed credentials are needed.

Sparkle orders updates by build number (`CFBundleVersion`). CI uses the macOS
DMG workflow's run number and attempt, such as `512.1`, which only increases.
Renaming or recreating that workflow restarts the count, so keep it.

### The update key

Halo's Sparkle key was created on November 19, 2026 with
`python3 tools/macos_release.py setup-updates`. Installed apps refuse an update
signed with any other key, so losing it strands every installed copy.

The private half is the 1Password document
**Halo OG Sparkle update signing key (private)**. `publish-release` asks the
1Password command-line tool (`op`) for that document by title and pipes it
straight into Sparkle's signer, so the key is never written to disk or held by
the release tool. 1Password asks for approval each time. When more than one
1Password account is signed in, name the one holding the document:

```sh
export OP_ACCOUNT=my.1password.com
```

The Mac that created the key also has a copy in its login Keychain;
`--keychain-key` signs with that copy instead. To replace a lost key you must
ship a build with a new public key through the old key first, so there is no
recovery once both copies are gone.

### Publishing a Mac update

The feed offers the same DMG as the GitHub release. After the
[testing prerelease](#manual-testing-prerelease) for a tag is published, and
with the user's explicit instruction to release it:

```sh
python3 tools/macos_release.py publish-release v0.6.0 --dry-run
python3 tools/macos_release.py publish-release v0.6.0 \
  --credential-file /path/to/approved/1password-mount.env
```

`publish-release` needs the authenticated GitHub CLI and `op`. It:

1. Downloads `Halo-OG-macos-arm64.dmg` and `SHA256SUMS` from the published
   release and checks the DMG against its listed hash.
2. Mounts the DMG and audits the app: package contents, ad-hoc signing with no
   certificate or team, the tag's version, and the embedded feed and public key.
   A build without them is refused, because its installed copies could never
   update again.
3. Refuses a build number lower than the one the live feed already offers.
4. Signs the DMG with the key from 1Password and verifies that signature with
   the committed public key, which is the check installed apps make.
5. Uploads the DMG to its versioned URL only if nothing exists there, reads the
   public download back and checks its hash, then replaces the feed last and
   verifies the live XML. A different DMG already at that URL stops publication.

`--dry-run` stops after step 4 and uploads nothing. The record and feed are
written to `build/macos/releases/<tag>/`. The Cloudflare token comes through
the map publisher's route: `CLOUDFLARE_API_TOKEN` in the environment, that
mounted file, or a hidden prompt. Rerunning after a failed upload is safe.

### Developer ID and notarization

Halo OG releases are ad-hoc signed and not notarized. The older route for a
Developer ID signed, notarized DMG remains in the tool and has never produced a
release. From a clean, committed tree, with the packaging virtual environment
prepared above and the update key in the login Keychain:

```sh
build/macos/dmg-packaging-venv/bin/python tools/macos_release.py build --version 0.3.1 --build-number 8 \
  --sign-identity 'Developer ID Application: YOUR NAME (TEAMID)' \
  --notary-profile YOUR_EXISTING_KEYCHAIN_PROFILE
python3 tools/macos_release.py publish build/macos/releases/8 \
  --credential-file /path/to/approved/1password-mount.env
```

`build` rebuilds a fresh app, signs nested helpers/libraries and the app with
hardened runtime, audits resources, notarizes/staples the app, creates an
Applications-link DMG, notarizes/staples it, and Sparkle-signs it. The custom
guest loader needs unsigned executable-memory permission, declared in
`port/macos/host.entitlements`. Developer ID launch, notarization, and an update
from an installed ad-hoc copy to a Developer ID build are untested. `publish`
re-verifies checksum, certificate signature, stapled ticket and Sparkle
signature, then uploads in the same order as above.

The app and feed report the minimum OS required by their bundled Mach-O code.
The current Homebrew SDL3 requires macOS 26.0; this build is Apple Silicon.
Older targets need a compatible SDL3 build selected with the existing
`HALO_MACOS_SDL_PREFIX` option, followed by validation on those Macs.

The audit rejects disc images/maps, XBE/debug/SDK inputs, private signing inputs,
external symlinks and unexpected resources. It establishes a packaging boundary,
not redistribution rights for compiled code or artwork. Public dependency
licenses are included. This product includes software developed by in
<in@fishtank.com>.

The packaging audit verifies resource and signature boundaries, not third-party
redistribution rights. Dependency licenses are included; notarization is separate
from gameplay and fidelity validation. See [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
and [Sparkle](https://sparkle-project.org/documentation/) for distribution tooling.

## Validation

```sh
python3 tools/test_macos_menu.py
python3 tools/test_macos_menu.py --check-ui
HALO_MACOS_LLVM_BIN=/opt/homebrew/opt/llvm@22/bin python3 tools/test_macos_runtime.py
```

Menu tests use authored synthetic XDVDFS/map headers. No copyrighted test data
is checked in. `port/macos/tests/menu_ui.m` exercises the real settings/menu and
SDL window bridge in a separate test app without running a game.
