# Client updates and signed releases

GitHub Actions can build, sign, notarize, and publish Halo OG updates. Clients
then check a public update feed; no running update server or push notification
is required. Cloudflare R2 can host that feed and immutable downloads, while
GitHub releases provide the familiar public download page.

**Current work provides update notices and manual installation on Mac, Windows,
and Linux.** Signed automatic installation is the next stage. Its identities,
keys, feeds, Windows installer, and production workflow are not configured or
validated yet. Community-map downloads remain independent of client updates.

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
| Mac | **Check for Updates…** opens Settings. **Download Update…** opens the DMG. **Automatically check for updates** controls background checks. Without a configured Sparkle feed/key, this is the GitHub notice fallback. |
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

Mac's existing [release tool](../tools/macos_release.py) already implements the
local build/sign/notarize/staple/archive-sign sequence and the R2/S3 publication
order. Its publisher uploads a versioned DMG without replacing an existing
different archive, verifies the public download, then publishes and verifies
the appcast. It currently uses Keychain identities and an AWS CLI profile.
A CI wrapper still needs to prepare these temporary credentials and keychain;
the current ad-hoc DMG workflow does not do this.

Keep non-secret feed URLs, public verification keys, bucket names, and platform
requirements in checked-in configuration. Mac's
[`release-config.json`](../port/macos/release-config.json) already contains these
fields, currently null. Private update keys, certificate passwords, notarization
credentials, and upload credentials belong in approved secret storage and
Actions secrets, never in public feeds or app bundles. Release-job variables
are temporary CI plumbing; no new application environment variables are needed.

Use separate testing/stable feeds and publish to the intended channel explicitly.
Current notices include testing prereleases; a future stable installer feed
must not silently enroll players in testing updates. For R2, choose public
HTTPS paths beneath the download base; the current Mac publisher requires its
feed there too. Existing `dl.oghalo.com` map hosting can remain independent.

## Mac: Sparkle and Apple distribution

Halo OG already bundles pinned **Sparkle 2.10.0** and an updater delegate that
defers interruption/relaunch until the game exits. Enabling installation needs
both a valid HTTPS `SUFeedURL` and the matching public `SUPublicEDKey`.
Sparkle verifies update archives with **Ed25519**; Apple Developer ID signing
and notarization establish the app's macOS distribution identity. Both belong
in the release process. Sparkle orders updates by increasing `CFBundleVersion`,
so retries and new releases must never reuse a lower/equal build number.
[Sparkle setup](https://sparkle-project.org/documentation/) and
[publishing updates](https://sparkle-project.org/documentation/publishing/).

On a GitHub macOS runner, prepare a temporary keychain, import the approved
**Developer ID Application** certificate, import Halo OG's separate Sparkle
private key under the release tool's account, and store the approved notary
credentials as a temporary Keychain profile. Remove temporary signing inputs
and keychain in cleanup even if the job fails.
[GitHub's certificate/keychain guide](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications).

The release tool signs bundled libraries/helpers and the app with hardened
runtime, submits the app archive using `notarytool`, requires **Accepted**,
staples the app, creates the drag-to-Applications DMG, signs/notarizes/staples it,
then signs the **final DMG bytes** with Sparkle. Verify those final bytes before
publication. Stapling makes the notarization ticket available offline.
[Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution) and
[custom notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).

The native guest loader's unsigned-executable-memory entitlement is already
declared in [host.entitlements](../port/macos/host.entitlements). Its real
Developer ID launch, notarization, and older-to-newer Sparkle update must still
be tested on a fresh Mac. Preserve `~/Library/Application Support/Halo OG/`.

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
