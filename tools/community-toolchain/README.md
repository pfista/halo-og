# Halo OG content helpers

By default this source recipe builds `invader-extract` and `invader-build`. It includes
the pinned Invader and RIAT revisions, exact dependency sources, the reviewed
Cargo lockfile, offline vendored Rust crates, licenses and build customization.
No Halo disc, original map, community tag or game data is part of this archive.

Install developer build prerequisites: Git, a native C/C++ compiler, Python 3.12+
with `cmake==3.31.10` and `ninja==1.13.0`, and Rust 1.95.0 including its standard
library documentation. These tools are build-time dependencies. Players need
only the compiled helpers packaged with their application.

From the Halo OG repository root:

```
python -m tools.community_toolchain --output build/content-tools-candidate
```

Offline map authors can select the seven conversion helpers explicitly:

```
python -m tools.community_toolchain --toolset authoring --output build/map-tools-authoring
```

This selection adds `dependency`, `convert`, `refactor`, `edit` and `bludgeon`.
It uses the same source pins and applies the checked-in starting-profile
compiler repair needed for preserved Digsite HSC. Patch identity and compiler
source hashes are recorded in `source-manifest.json`; the patch is included in
the corresponding source archive. A generic scripted map conversion requires
this source-patch record. See the [directory conversion guide](../../docs/map-conversion-pipeline.md).
Desktop packaging continues to accept only the existing independently reviewed
extract/build trust set. An authoring candidate is never bundled automatically.
Use the same `--toolset` when finalizing an interrupted build; the authoring
selection requires its original `toolset-build.json` receipt and unchanged
patched compiler source.

The output directory must not exist. The recipe never installs globally or
changes application preferences. `--source-cache` optionally reuses a reviewed
Invader Git checkout plus RIAT submodule, dependency archives and Cargo cache;
the checked Git objects and archive hashes still determine the build inputs.
`--rust-bin` selects the pinned developer Rust bin directory explicitly.

macOS uses arm64 and macOS 14.0 for every C/C++ dependency and the Rust build.
Windows uses x86_64 native MinGW/MSVCRT plus Rust's
`x86_64-pc-windows-gnu`; mixing UCRT and MSVCRT static objects is refused.
Linux uses x86_64 and `x86_64-unknown-linux-gnu` on Ubuntu 24.04.
All builds use static zlib 1.2.12 and scalar Squish without OpenMP.
The recipe limits zlib's obsolete classic-Mac `fdopen` fallback to non-Apple
targets so SDK 27 headers compile; its compression algorithm is unchanged.
Rust stripping is explicitly disabled to avoid the proc-macro LINKEDIT
alignment defect tracked at https://github.com/rust-lang/rust/issues/157750.

`source-manifest.json` records unsigned helper SHA256 values, runtime libraries,
minimum system, compiler versions, licenses and the corresponding source archive
SHA256. CI archives this review candidate. CI never changes trusted hashes or
publishes a game release. Independently review the candidate and validate real
stock extraction and exact package output before updating checked-in platform
binary pins or enabling release use. A matched source revision alone does not
prove cross-platform compiled map identity: consumers still enforce each
package's original input hashes and final output hash, size and Xbox v5 header.

`halo-content-tools-source.tar.gz` contains the complete modified Invader/RIAT
source, static dependencies, vendored Cargo dependencies and this build recipe.
Invader and RIAT are GPL-3.0-only; full GPL and other dependency notices accompany
the helpers. The archive's source/recipe directory contains the pins and exact
build customization. To reproduce outside the application, place the recipe
directory and community_toolchain.py in the same repository layout or obtain
the Halo OG source revision recorded with the CI artifact. The archive includes
original source archives at source/archives; pass that directory as
`--source-cache` to reproduce without downloading the sources again. Preserve this source
archive and the licenses whenever distributing the compiled helpers.

The recipe pins source inputs and records the host C/C++ compiler/SDK. It does
not yet certify byte-identical helper binaries across compiler or runner image
updates, nor exact game-map output on Windows/Linux. Those require the CI and
private original-data acceptance results described above.
