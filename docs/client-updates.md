# Client updates and signed releases

GitHub Actions builds every Halo OG package. Clients then check a public update
feed; no running update server or push notification is required. Cloudflare R2
hosts that feed and immutable downloads, while GitHub releases provide the
familiar public download page.

**Mac installs updates in the app; Windows and Linux show a notice and install
manually.** Mac builds embed Halo's Sparkle feed and public key, and one local
command signs a published release's DMG and advances the feed. No release has
been published to that feed or update-tested yet, and Mac builds from `v0.5.2`
and earlier need one manual installation first. Windows and Linux installation
is the next stage. Community-map downloads remain independent of client updates.

## Current behavior

The new desktop setup source checks public releases in **pfista/halo-og**,
including published prereleases. It requires a source-commit link in the release
description, the exact platform download, and attached `SHA256SUMS` and
`provenance.json`. Drafts, incomplete uploads, and malformed metadata are ignored.
The notice opens the platform download in a browser; installation remains manual.
It does not fetch those checksum/provenance files to authenticate or install code.

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
| Windows/Linux | A background check waits for the local main menu, then offers **Open download**, **Later**, or **Stop checking**. Existing `[update] auto` controls checks. No prompt interrupts a match or pregame lobby. |
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
[Mac notice controller](../port/macos/native/HaloReleaseUpdates.m), and
[testing-release publisher](../tools/testing_release.py).

The cybersecurity updater was reviewed at `193cbf59`. Its desktop path uses
GitHub releases and a numeric build comparator, downloads a ZIP over HTTPS,
then replaces individual files. It does not provide signed desktop archives
or a transactional package rollback. That is useful reference code for
background checks, but the signed installation stage will use each platform's
updater and package format below. See the reviewed
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

Mac already follows this order, with the signing step run locally instead of
in Actions. CI builds the DMG, and the [release tool](../tools/macos_release.py)'s
`publish-release` signs that exact file with the update key from 1Password. It
uploads a versioned DMG without replacing an existing different archive,
verifies the public download, then publishes and verifies the appcast through
the map publisher's R2 credential route. Moving that step into Actions would
mean storing the private update key and the Cloudflare token as Actions secrets.

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
`updates/mac/testing/appcast.xml`. Keep other platforms under their own
`updates/<platform>/` prefix.

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

## Windows: WinSparkle and an installer

The portable ZIP is useful for testing. For installation updates, add a pinned
**32-bit WinSparkle** library to match the current x86 executable, and build a
real installer that upgrades the installation consistently. Embed the public
Ed25519 key, appcast URL, and increasing app/build versions. WinSparkle verifies
the update signature before installation.
[Integration](https://winsparkle.org/guides/integrating-winsparkle/) and
[EdDSA signing](https://winsparkle.org/guides/getting-started/).

Choose and validate an x86 installer, such as an EXE installer or MSI. Sign the
game and installer with an **Authenticode** identity usable by the CI runner,
and add an RFC 3161 timestamp with SHA-256. Then Ed25519-sign the final installer
for WinSparkle. Authenticode and updater signatures serve separate verification
steps; retain both. Provider-held keys may require a signing service instead of
an exported key file. Verify the result with SignTool before publication.
[Microsoft signing/timestamps](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures) and
[SignTool verification](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool).

Publish an appcast targeting `windows-x86`, not `windows-x64` merely because the
player runs 64-bit Windows. Keep installation progress/errors visible and use
WinSparkle's shutdown callbacks to coordinate a saved, clean game exit before
files are replaced. Preserve `%APPDATA%\Halo OG`, imported maps, and existing
configuration when moving from portable ZIPs to the installer.
[Platform/installer feed options](https://winsparkle.org/guides/publishing-updates/) and
[shutdown callbacks](https://winsparkle.org/c-api/callbacks/).

WinSparkle integration, installer migration, signing, permissions, and end-to-end
update installation remain unimplemented and untested.

## Linux and Android

Linux has no Sparkle installation path in Halo OG. Choose the supported package
format first. A future portable-build updater needs signed release metadata and
archives verified by a public key embedded in the client. It should stage a
complete new version, validate it, wait for clean exit, switch versions without
partially overwriting the running build, and retain a recoverable previous
version if launch fails. This is a proposed design, not a working installer.
Keep `maps`, `config.toml`, and the XDG save folder separate from replacement
binaries. Distribution/package-manager installations need their own upgrade
ownership and runtime compatibility checks.

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
