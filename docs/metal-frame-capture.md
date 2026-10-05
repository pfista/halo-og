The ordered frame collector exports actual original game draws. It is disabled
by default. An isolated ILP32 guest build must explicitly enable both
`HALO_MACOS_METAL_SHADER_CAPTURE=1` and `HALO_MACOS_METAL_FRAME_CAPTURE=1`; the
existing `debug.gpu_trace_frame` selects the one frame. Capture uses the existing
save root and creates a fresh `metal-frames/frameN` directory. It never
overwrites an earlier capture.

The shared renderer includes `metal_frame_capture.h` only after the private
device, shader, uniform, framebuffer and trace helpers. Its hooks cover ordinary
and indexed draws, immediate End(), clears, target changes, visibility queries,
internal mip copies/generation, and Present. The isolated import list also needs
`hostgl_glGetFloatv`; the existing host resolver supplies it through ANGLE.
Default-disabled guest compilation includes no collector or extra host import.

Each original draw has a JSON record describing its actual shader use,
declaration, source streams, original uint16 indices, constants, converted draw
uniforms, fixed register values, render/texture states, viewport bits, textures,
samplers and original depth request. Immediate vertices preserve all sixteen
float4 registers. Textures retain authored mip bytes and palettes; sampling a
render target records its GPU target version instead of stale CPU memory.

The ordered JSONL stream records target binding, clears, draws, visibility
operations and presentation. Target versions retain original initial seeds and
GPU attachment values after each mutation. Before-operation references use the
previous target version. Data blobs are deduplicated by candidate hash plus byte
comparison. The Python freezer adds SHA256 hashes for every payload, raw record
and original shader corpus file and checks every draw/use pair and target-history
transition. Only a successful final marker is accepted.

GLES rejects direct depth/stencil ReadPixels on the verified ANGLE host. The
collector reads actual depth float bits by GPU texelFetch into separate RGBA8
storage, and stencil by eight read-only bit tests. An independent stencil165
control validates all bits. Source depth/stencil write masks remain zero, and
every modified game pipeline input is restored. Internal target row0 is already
logical Xbox top; no readback row reflection is performed.

Diagnostic GPU draws must never enter an original visibility query. The
verified frame420 query draw has zero color/depth/stencil writes, so its before
and after target references remain identical without a readback. Query begin,
end, actual CPU-returned result and completed GPU result are retained separately.
Atomic-counter query resources and active-query attachment writes are currently
rejected. GPU copy/mipmap output versions are also rejected until their complete
resource history is implemented. These cases preserve evidence with
`complete:false`.

The verified Blood Gulch frame420 capture contains 126 original draws, two
clears, five target changes, 138 ordered events, 20 vertex variants, 30 pixel
keys, four persistent target textures, 252 GPU versions and 497 payloads. Eight
draws sample original offscreen targets. The capture is at
`build/metal-reference-20261004/ordered-frame-runtime/run/saves/metal-frames/frame420`.
The separate `verification.json` records the unchanged primary host, isolated
guest, all548 link inputs, map and ANGLE hashes, actual camera and backend
evidence. The failed active-query attempt remains separately preserved.

Freeze and verify a completed raw package with:

```sh
python3 tools/metal_frame_capture.py freeze PATH --runner RUNNER.py
python3 tools/metal_frame_capture.py verify PATH/captured_frame.json
```

`metal_frame_replay.py` prepares the shared native encoder's resources and
ordered commands. It imports original streams/topology and generated NV2A MSL,
using the existing draw importer for texture conversion, uniforms, raster state
and the explicit original vertex compiler contract. Persistent targets receive
only version0 seed uploads. ANGLE's later GPU versions are reference checkpoints
and are never uploaded over native draw results. GPU aliases bind persistent
native target identities at their expected generation.

Successful capture or manifest preparation is not native frame execution.
Native ordered replay and live guest draw submission remain separate milestones.
Readbacks synchronize the captured frame, so original asynchronous visibility
timing is not established. The verified host stores GL D24S8 in Metal float32
depth; original physical Xbox depth quantization remains a separate unresolved
fidelity requirement.
