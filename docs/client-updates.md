# Client updates and signed releases

GitHub Actions builds every Halo OG package. Clients then check a public update
feed; no running update server or push notification is required. Cloudflare R2
hosts that feed and immutable downloads, while GitHub releases provide the
familiar public download page.

**Mac, Windows and Linux install updates in the app.** Mac builds embed Halo's
Sparkle feed and public key. Windows and Linux builds install the release they
discover when the update host serves a record for it signed by the same key.
One local command signs a published release for all three and publishes the
result. No release has been published this way or update-tested yet, and builds
from `v0.5.2` and earlier need one manual installation first. Android installs
manually. Community-map downloads remain independent of client updates.

## Current behavior

The new desktop setup source checks public releases in **pfista/halo-og**,
including published prereleases. It requires a source-commit link in the release
description, the exact platform download, and attached `SHA256SUMS` and
`provenance.json`. Drafts, incomplete uploads, and malformed metadata are ignored.
Discovery alone never installs anything: GitHub's metadata is not signed by
Halo OG. A desktop build installs a discovered release only with the signed
record described [below](#windows-and-linux-in-place-installation); otherwise
the notice opens the platform download in a browser.

Build identity comes from a clean, matching `main` CI checkout: repository,
ref, `GITHUB_SHA`, actual Git HEAD, and a clean source checkout must match.
The app records that commit and its UTC commit date. Release discovery compares
source identities/dates, rather than sorting testing tag names or build clocks.
The current GitHub metadata path uses release `created_at` for source ordering;
publishing an old commit later must not make it an upgrade. Signed installers
will use explicit increasing platform build numbers.

| Platform | Notice and download |
| --- | --- |
| Mac | With the embedded Sparkle feed, **Check for Updates…** downloads a verified update and installs it after the game quits; **Automatically check for updates** controls daily background checks. A build without the feed falls back to the GitHub notice: **Check for Updates…** opens Settings and **Download Update…** opens the DMG. |
| Windows/Linux | A background check waits for the local main menu. For a release with a valid signed record it offers **Install update**, **Open download**, **Later**, or **Stop checking**; otherwise the same without **Install update**. Existing `[update] auto` controls checks. No prompt interrupts a match or pregame lobby. |
| Android | Halo OG fork builds keep the upstream automatic installer disabled. Install the matching APK manually. |

Local/development desktop builds do not advertise automatic upgrade ordering;
Mac can open the Halo OG releases page manually. The published
`test-v0.3.0-net11-gameplay1` predates the new notice/discovery code. The setup1
Windows/Linux packages also omitted it because a restored compiler cache failed
the clean-source check. The setup2 pipeline ignores that generated cache and
requires the final desktop binaries to contain their exact source identity and
notice code before upload and publication. Older Windows/Linux builds need one
manual upgrade to setup2.

Source entry points: [build identity](../tools/release_discovery.py),
[shared metadata parser](../port/linux/src/release_discovery.c),
[Mac notice controller](../port/macos/native/HaloReleaseUpdates.m),
[desktop installer](../port/linux/src/update_install.c), and
[testing-release publisher](../tools/testing_release.py).

The cybersecurity updater was reviewed at `193cbf59`. Its desktop path uses
GitHub releases and a numeric build comparator, downloads a ZIP over HTTPS,
then replaces individual files. It does not provide signed desktop archives
or a transactional package rollback. Halo OG's desktop installer reuses its
download, unpacking and file replacement, and adds the signed record and the
rollback. Its release check, which follows cybersecurity's build numbers, stays
compiled out of Halo OG builds. See the reviewed
[desktop updater](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/port/linux/src/updater.c)
and [build workflow](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/.github/workflows/build.yml).

## Future GitHub Actions pipeline

Use one release source commit across platforms, with a short release description
and direct platform links. The proposed publication sequence is:

1. Build and run the required checks from a clean, committed source revision.
   Allocate increasing platform build numbers and record source provenance.
2. Prepare each platform's signed installation package using its own runner.
   Provision GitHub Actions secrets through the approved 1Password process;
   materialize the required credentials only for the release job.
3. Verify signatures, package contents, supported OS/architecture, checksums,
   and applicable notarization tickets. Preserve the application-data boundary.
4. Upload each package at an immutable versioned HTTPS URL and attach the
   matching files, checksums, and provenance to its GitHub release.
5. Read the public downloads back and verify their bytes/signatures.
6. Publish the platform/channel update feed **last**, then read it back.
   Clients poll that feed and offer the verified update. Installation waits for
   a clean game exit and respects the player's update choice.

Releases already follow this order, with the signing step run locally instead
of in Actions. CI builds every package, and the [release tool](../tools/macos_release.py)'s
`publish-release` signs them with the update key from 1Password: the Mac DMG
for Sparkle, and an install record for each of the Windows and Linux packages.
Everything is signed and verified before anything is uploaded. It publishes the
immutable records and the versioned DMG without replacing anything that
differs, verifies the public downloads, then publishes and verifies the Mac
appcast last, through the map publisher's R2 credential route. Moving that step
into Actions would mean storing the private update key and the Cloudflare token
as Actions secrets.

Keep non-secret feed URLs, public verification keys, bucket names, and platform
requirements in checked-in configuration. Mac's
[`release-config.json`](../port/macos/release-config.json) holds its feed,
download base and public key. Private update keys, certificate passwords, notarization
credentials, and upload credentials belong in approved secret storage and
Actions secrets, never in public feeds or app bundles. Release-job variables
are temporary CI plumbing; no new application environment variables are needed.

Use separate testing/stable feeds and publish to the intended channel explicitly.
Current notices include testing prereleases; a future stable installer feed
must not silently enroll players in testing updates. Mac updates live under
`updates/mac/` on `dl.oghalo.com`, beside the maps; the testing feed is
`updates/mac/testing/appcast.xml`. Windows and Linux records live under
`updates/windows/` and `updates/linux/`.

## Mac: Sparkle

Halo OG bundles pinned **Sparkle 2.10.0** and an updater delegate that defers
interruption/relaunch until the game exits. CI builds embed the HTTPS
`SUFeedURL` and the public `SUPublicEDKey`, which are public configuration.
Sparkle verifies each update archive with **Ed25519** and installs it only when
the signature matches that embedded key. Sparkle orders updates by increasing
`CFBundleVersion`, so retries and new releases must never reuse a lower/equal
build number. [Sparkle setup](https://sparkle-project.org/documentation/) and
[publishing updates](https://sparkle-project.org/documentation/publishing/).

Releases are ad-hoc signed and not notarized. No Apple developer identity or
account takes part in building or publishing them. The cost is at first
installation: macOS blocks the downloaded app until the player approves it in
**System Settings → Privacy & Security**. Updates that Sparkle installs do not
repeat that step. Because an ad-hoc signature identifies one exact build, macOS
may ask again for a permission the player granted to an earlier build.

[Publishing a Mac update](macos-menu-and-releases.md#publishing-a-mac-update)
gives the release command, the 1Password-held update key and the checks made
before the feed moves. A real older-to-newer update must still be tested on a
Mac with an installed copy. Preserve `~/Library/Application Support/Halo OG/`.

A Developer ID signed, notarized route also exists in the release tool and is
unused; see [Developer ID and notarization](macos-menu-and-releases.md#developer-id-and-notarization).
The native guest loader's unsigned-executable-memory entitlement for that route
is declared in [host.entitlements](../port/macos/host.entitlements).

## Windows and Linux: in-place installation

The Windows and Linux packages are portable ZIPs: the game, its libraries and
licenses in one folder, with the player's `maps` and `config.toml` beside them.
The game updates that folder in place.

**What authorizes an installation.** For each release, `publish-release`
publishes `updates/<platform>/<tag>.txt` and a 64-byte Ed25519 signature of it
at the same name with `.sig`. The record is fixed text:

```text
Halo OG update 1
platform: windows
tag: v0.6.1
source: <release source commit, 40 hex digits>
date: <the GitHub release's created_at>
file: halo-windows-release.zip
size: <bytes>
sha256: <64 hex digits>
```

After discovery finds a newer release, the game fetches that release's record
and signature, each bounded and without redirects, and checks the signature
with the public key in [`halo_update_key.h`](../port/linux/src/halo_update_key.h)
before reading anything in it. That is the Mac app's `SUPublicEDKey`; a test
keeps the two copies equal. The record must name the tag, source commit,
creation date and platform file that discovery selected. A record for another
release or platform is refused, and so is an older signed release offered as
a newer one, because its signed date is the one compared with the running
build's. Without a valid record the notice only opens the browser download.

**What is installed.** The ZIP is downloaded from the GitHub release into
`update.partial/` beside the executable and must match the record's size and
SHA-256 exactly. The signature check is
[TweetNaCl](https://tweetnacl.cr.yp.to)'s public-domain verification code in
[`halo_ed25519.h`](../port/linux/src/halo_ed25519.h).

**How files are replaced.** Each file at the ZIP's top level is moved over the
game's file of the same name, whose previous version is first renamed
`<name>.old` (a running executable can be renamed, not overwritten). Entries in
folders and `config.toml` are never written. If any file cannot be replaced,
the files already replaced are moved back, so the folder holds one whole
version or the other. The game then starts the new version and exits.

**Going back.** The `.old` files stay until the new version next starts, which
removes them. If the new version cannot start, they are the previous version;
the [Windows](setup-windows.md#update-halo-og) and
[Linux](setup-linux.md#update-halo-og) guides give the steps. There is no
automatic rollback of a version that starts and then fails.

`publish-release` refuses a package the installer would only partly install:
more than 32 files, a file in a folder, `config.toml`, or a missing executable.
The testing-release publisher refuses desktop binaries without the install
option. An installer package and WinSparkle are not used; Authenticode signing
is still absent, so Windows SmartScreen may warn on a first manual download.

The record check, the notice and the installer are tested natively on real
files (`tools/test_release_discovery.py`, `tools/test_update_install.py`). The
Windows and Linux system side of an update, a running executable replacing
itself and restarting, has not been run on those platforms.

## Android

Android must retain the same approved APK signing identity for upgrades and
uses Android's package installer. Its inactive upstream updater does not supply
a Halo OG update pipeline. APK signing continuity, installer handoff, and data
preservation still need a separately validated Halo OG release path.

## Acceptance before enabling installation

Test a real older signed release upgrading to a newer one on each supported
platform, including fresh installation, offline launch, interrupted downloads,
invalid signatures, insufficient permissions, and failure recovery. Confirm
that checks do not interrupt network matches and that maps, profiles, and
settings survive. A successful build/signature check alone does not prove the
installer or subsequent gameplay works.
