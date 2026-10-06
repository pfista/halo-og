# Native Metal shader function reuse

Program creation previously compiled both emitted Metal source strings for
every guest program. Original programs can share the same vertex source while
their fragment programs or texture contracts differ. The host now reuses a
successful `MTLFunction` when its complete emitted source and compile contract
match. Original assets, shader text, draw order and the 30 Hz simulation remain
unchanged.

The key contains every source byte, the vertex/fragment stage, fast-math choice
and invariance choice. It uses exact string comparison rather than a hash-only
identity. The existing `MTLCompileOptions`, stage names, function-type checks,
UTF-8 validation and embedded-NUL rejection still apply. The cache belongs to
one host context and Metal device; shutdown releases it before a new context is
initialized.

Each cache holds at most 256 functions and 8 MiB of retained source-key bytes.
Insertion evicts the oldest entries, while a hit leaves their order unchanged.
An oversized entry is compiled normally and skipped by the cache. Live programs
retain their functions independently, so eviction does not invalidate a guest
resource or a pipeline using it. These bounds cover retained keys and entry
count; they do not measure Metal's private compiled-code storage.

Deletion and rejected-packet cleanup remove pipelines only for function stages
that no other live program references. Reusing a vertex stage therefore does
not cause deleting one fragment variant to discard another variant's warm
pipeline.

New functions first enter a bounded cache owned by the packet's `Prepared`
state. Identical later program creations in that packet can reuse them. Only
after every command validates are successful candidates published to the
context cache. A later invalid command or failed compilation discards those
candidates and leaves live program generations, visibility state, resource
contents and submitted/completed sequences unchanged. Failed compilations are
retried on a later request. Packet execution and GPU completion remain
synchronous.

The publication step can allocate. If it reports a memory-allocation failure,
some successful compiler entries may have been retained or older cache entries
evicted before the failure. This affects internal warm-cache state only;
execution has not begun and live resources, query state and sequence counters
remain unchanged. The no-publication guarantee applies to ordinary preflight
validation and compilation failures, rather than allocation failure during
publication.

The existing GPU statistics log adds `shader-compile-hits`,
`shader-compile-misses`, `shader-compile-us`, `shader-function-cache` and
`shader-function-source-bytes` after its existing fields. Hits and misses count
compile requests during attempted preflight, including candidates in a rejected
packet. Compile time measures the synchronous `newLibraryWithSource` call,
including a failed call; it excludes source validation, cache lookup and
`newFunctionWithName`. No application setting or environment variable is added.

## Focused verification

The CPU test includes the production cache helper and checks exact source and
contract identity, count/byte eviction, duplicate insertion, retained values,
move and reset behavior. The headless GPU test includes the production backend,
submits real resource packets and checks reuse within/across packets, generation
replacement, rejection after program/query preparation, failed-compile retry,
compile-contract separation and context reset. It also compares controlled
render bytes through the shared draw encoder from cached and newly compiled
functions with Metal API validation enabled. Warm pipeline identity is checked
after cache-hit packet rejection and deletion of a sharing program.

```sh
PYTHONPATH=tools python3 -m unittest tools.test_metal_function_cache
```

Production ordered-frame and coalesced-frame replays provide a separate check
using original captured draws, attachments and visibility results. Prepare new
output directories from the original capture manifest; never replace source
hashes in an old proof. The source snapshots include the new helper header.
These checks establish behavior for their fixtures, rather than all-scene Xbox
parity or achieved gameplay FPS. A fresh live measurement is required to assess
shader hitch reduction; the earlier performance matrix uses the pre-cache host.

## October 5 focused result

Both focused tests passed against an unchanged copied source tree, including
strict host/encoder compilation and observed Metal API validation. The cached
and freshly compiled draws produce the same 64 color bytes, SHA256
`4aff2a0461a4094b6488f5bde9f6e640b5b7afdc5f4d7fa65391634194b8cfeb`.
All 28 related packet-input, unequal-attachment and ordered/coalesced replay CPU
tests also pass.

Focused evidence is retained in
`build/metal-poc/function-cache-proof-attempt2/result.json`, SHA256
`a7729d8552309b79402988ede6577e464089d0e9c17047d7caac7e60280bbab5`.
Its source-snapshot manifest SHA256 is
`02e25818b9ac51b9681978f10ac07101efcc91c00d2d2e791e3839ff73ca7324`.
The first attempt remains preserved; its fixture expected the wrong existing
status for an unknown opcode and was corrected without a backend change.

The rebuilt original ILP32 replay preserves all 378 color/depth/stencil/query
checkpoints with API validation. Its comparison is
`build/metal-poc/function-cache-ordered-frame-attempt1/comparison.json`, SHA256
`9ff3b0db2d4e2b55eadda8e3119f912e2db1e458b9254ab51ee60ade6b76b42b`.
The rebuilt coalesced replay preserves all six final outputs from 126 draws in
one packet. Its result is
`build/metal-poc/function-cache-coalesced-frame-attempt3/result.json`, SHA256
`7a9c8bc41f6bef0c1162926557de06364245cc5beaf64cf4ddc18c5931e8bc15`.
Earlier coalesced preparation attempts rejected stale historical tool hashes
or a missing independent comparison; they are retained and are not passing
proofs. The final run uses the fresh, independently compared ordered baseline.

### Campaign measurements

A four-run A/B/B/A comparison retains the same pre-motion-fix guest and original
Silent Cartographer opening. Both hosts already reuse opaque passes; only the
second host adds this function cache. Each run lasts 40 seconds at native
3600x2338, uncapped, VSync off, FXAA and interpolation on, with isolated saves,
audio off and logging included. All four foreground/configuration/exit checks
pass. Evidence is
`build/macos-metal/performance-pass-attempt1/function-cache-timing-attempt1/result.json`,
SHA256 `7dc204dd1343d8d6f42b047ff88a67285322695283e868c0d69a7a14cc22c1ef`.

| Run | Host | FPS | p95 ms | p99 ms | Maximum ms |
| --- | --- | ---: | ---: | ---: | ---: |
| A1 | Pass reuse only | 30.52 | 47.78 | 135.80 | 283.95 |
| B1 | Pass reuse + function reuse | 38.17 | 34.57 | 85.17 | 195.99 |
| B2 | Pass reuse + function reuse | 42.69 | 43.57 | 79.11 | 185.27 |
| A2 | Pass reuse only | 43.92 | 37.15 | 87.88 | 202.85 |

The mean of each variant's two run-level FPS values is 37.22 versus 40.43;
this is not a pooled frame distribution or a precise causal improvement.
Baseline drift is large and the last baseline outperforms the adjacent cached
run. Camera phase, resource loading and system conditions remain limitations.
This change does not establish sustained 60/120 FPS or eliminate every hitch.

The cached runs avoid 316 of 400 and 356 of 440 reported stage compilation
requests. Both retain 84 function entries and 546,096 source-key bytes. This
confirms that duplicate compilation work is avoided in the real campaign;
unique sources and render-pipeline creation still compile synchronously.
The original host has no compile-request counters, so its missing fields must
not be interpreted as zero compilation cost.
