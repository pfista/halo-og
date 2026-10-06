# Coherent rendering after a simulation catch-up

Smooth Motion uses the same interpolation code with ANGLE and native Metal.
Objects save their node matrices after every simulation tick. Cameras save an
observer sample on the first rendered frame after a tick. If rendering stalls
long enough to advance multiple ticks, the object's final two snapshots cover
one tick, while the camera's two samples can span several. Blending both with
the same fraction makes a tracking camera and its object disagree about time.

The shared renderer now draws the current tick whenever a rendered frame has
advanced more than one simulation tick. The shared fraction is one for camera,
object nodes, first-person pose and animated shader time. Later frames within
that same tick keep this choice, even if their incoming fraction is smaller;
otherwise motion could rewind after the catch-up frame. On the next tick the
normal previous/current blend resumes.

The first enabled frame and the first frame after a map reset also start
current. They seed the existing raw-object snapshot path once, without running
a game tick, so the next tick has a real object pair. Disabling Smooth Motion
invalidates its histories; enabling it on a frame with no tick starts from the
current scene. Internal interpolation tick counters and gap comparisons use
unsigned arithmetic, including at counter wrap.

During a fallback tick, the camera retains its captured observer sample across
frames that run no tick. A camera cut occurring later in that tick may therefore
wait until the next tick, at most about 33 ms at normal simulation speed. Normal
fractional-frame camera cuts and object teleports keep their existing snap
rules. The optional direct facing camera and camera/object network-correction
glide are retained. Particles and contrails keep their existing per-frame update
path; this change does not alter their simulation.

This changes presentation only when Smooth Motion is enabled, including when
its render cap is 30 FPS. With Smooth Motion off, original 30 FPS rendering is
preserved. The 30 Hz gameplay simulation, assets, director/observer update
cadence and existing settings are preserved in either mode. It does not
extrapolate or invent an intermediate cinematic camera path.

## Focused validation

Run `python3 -m unittest tools.test_render_interpolation -v`. The CPU fixture
compiles the full production interpolation translation unit and production
object accessor with deterministic game dependencies and 32-bit-normalized C
long. It exercises the real tick snapshot, frame-begin, camera, object,
first-person and shader-time functions.

The tracking case advances ticks in gaps of 1, 2, 1, 3 and 1. It checks constant
camera separation from two object nodes, consistent first-person pose time and
nondecreasing shader time. Catch-up ticks include zero-tick frames with incoming
fractions of one, 0.1 and 0.9. A regression control disabling the new fallback
fails on camera/object separation. Additional cases cover initialization,
normal zero/one-tick interpolation, captured-camera holding, map resets,
disabled/enabled transitions with and without intervening draws, camera cuts,
object teleports, counter wrap, direct facing and network corrections. Address
and undefined-behavior sanitizers are used on non-Windows hosts.

These source tests demonstrate the timing correction; they do not prove that
the reported Silent Cartographer intro stutter is resolved. A direct comparison
of the same fresh B30 intro with Smooth Motion off at 30 FPS and on at 60 FPS,
for each renderer, should correlate observed jumps with frame intervals and
simulation tick gaps. They also do not establish original Xbox cinematic or
pixel parity, sustained frame rate or an actual ILP32/GPU execution result.
