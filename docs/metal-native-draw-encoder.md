# Native draw encoding and guest transport

`port/macos/host/metal_draw_encoder.h/.mm` is the shared encoder for original
NV2A draws. The ILP32 transport uses it; the ordered-frame replay path will use
the same module. It does not clear, upload, commit, wait or present. Every draw
loads and stores its existing color and combined depth/stencil attachments.

The caller supplies generated vertex/fragment functions, four texture/sampler
slots, 256-byte expanded original register records, UInt32 indices and immutable
VS3120/PS608 uniform buffers. Packed register inputs retain their integer bits.
The fixed `halo_metal_draw_state` controls all supported raster state, including
fill mode, viewport, scissor, depth/stencil, winding/culling, depth bias and
constant blending. No packet field supplies replacement scene geometry.

`prepareDraw` validates actual buffer ranges, functions, attachments and used
shader bindings before a command encoder is created. Pipeline and depth states
are cached; retained functions prevent pointer-identity reuse, and program
deletion evicts its pipelines. `usedTextureMaskForDraw` lets the transport verify
initialization of the subresources that the compiled shader actually reads.

`host_metal.mm` copies a complete guest packet, checks every operation against
simulated resource generations/content initialization, compiles all requested
programs and prepares all draws before GPU mutation. Texture, program and
visibility-query IDs have separate typed generation tables. `live_resources`
counts all three tables.
The execute pass uses the prepared GPU objects and immutable original bytes.
An execution failure poisons the context until shutdown; validation failure
leaves its existing resource maps and completed sequence unchanged.

Extended sampled textures support RGBA8, BGRA8 and authored BC1/BC2/BC3 blocks,
2D or cube, with exact mip/face uploads and independently tracked initialization.
The BC2/BC3 cube component fixture at
`build/metal-poc/bc23-cube-20261006-r01/result.json` runs the real ILP32 bridge:
all six faces and five authored mips match pinned ANGLE color/depth/stencil
bytes exactly. It uploads original compressed blocks, never reference pixels.
Compressed volumes fail closed. Render targets are 2D with one mip.
Original initial depth float32 and stencil uint8 seed uploads are separate
aspects of Depth32FloatStencil8. After-draw reference checkpoints never enter
these uploads. Xbox D24/F24 storage precision remains a separate fidelity gate.

The vertex contract defaults to invariant safe compilation; contract 1 requests
the source-derived invariant fast vertex policy validated by the import tools.
The separate fragment contract defaults to invariant safe compilation. Its
explicit contract 1 selects the pinned ANGLE fast fragment policy without
invariance, with per-key source evidence supplied and verified by the producers.
Existing zero-filled program packets retain their earlier safe fragment policy.
The isolated original use4 diagnostic shows why this distinction matters: safe
fragment arithmetic differs at six color bytes; the exact original stage policy
matches every color/depth/stencil byte without changing inputs or state. The host accepts
only the named generated entries `xgpu_vertex` and `xgpu_fragment`; packet
compiler policy is explicit, not inferred from resource shape or declaration.

The fast fragment evidence applies to the original captured GLSL contract.
Extended native DOT_ZW depth handling adds finite guards absent from that GLSL.
It requires safe compilation or a separately verified fast contract; the
captured frame does not exercise it and cannot establish those guard semantics.

Texture readback currently reads only 2D, one-mip render targets. Sampled
cube/mip contents are checked through independent sampled-output fixtures.
Legacy clears write complete color channels; partial channel clears require a
future explicit wire command and cannot silently be widened.

Visibility commands create/delete a typed query, begin an explicit reset and
end the active query. Every queried draw gets a fresh zeroed eight-byte shared
GPU result word. Boolean results combine with OR; sample counts sum after
completion, including draws in different packets and render encoders. Readback
plane 8 returns one raw uint64 after End; earlier reads fail as undefined.
End increments the query content version. Nested Begin, wrong End, active
deletion and stale generations reject before any packet mutation. An invalid
later draw also leaves the active query result and attachments unchanged.

`build/metal-poc/host-query-api-validation/result.json` verifies 26 cases through
the real rebased ILP32 imports: the original opaque draw counts 41,738 samples,
two readonly draws count 83,476 within/across packets, and visible-plus-occluded
Boolean draws retain one. Ten full attachment checks find no color/depth/stencil
or attachment-version changes. This is raw GPU aggregation, not the original
frontend's asynchronous cached-result policy. A subsequent frame420 diagnostic
uses its exact readonly visibility geometry and matches the original Boolean0.
CPU result timing, broader query coverage and asynchronous frame scheduling
remain outstanding.

The isolated encoder GPU test checks ordered color/depth/stencil preservation,
depth occlusion, stencil/mask/scissor/constant blend state, reflected missing
textures and attachment aliases, invalid buffers/indices/state and cache
eviction. The existing rebased ILP32 transport probe retains its 17 resource,
copy, clear, readback and lifetime checks. Passing these checks is not evidence
that the whole gameplay frame has executed natively.
