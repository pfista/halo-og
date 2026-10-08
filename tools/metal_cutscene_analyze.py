#!/usr/bin/env python3
"""Read Native Metal diagnostic logs without launching or changing the game.

  python3 tools/metal_cutscene_analyze.py build/campaign/host.log --output analysis.json

Guest flush frames are zero based; completed Native timing/scene frames are one
greater. Packet sequence joins do not depend on line order or host/guest clock
epochs. GPU time overlaps completion wait; prepare includes shader compilation
and pipeline creation; stage compilation durations can overlap with each other.
The reported counters are attribution, never exclusive
terms to add into a frame budget. Present gaps also include simulation, guest
translation, cap waits and diagnostic logging. Scene flags identify cinematic
state, but these logs cannot establish camera or animation motion smoothness.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


def _pattern(marker, fields):
    """Build strict field patterns while allowing a logger prefix on the line."""
    return re.compile(re.escape(marker) + fields + r"\s*$")


PATTERNS = {
    "timings": ("Native timing:", _pattern("Native timing:",
        r" frame (?P<frame>\d+), monotonic (?P<ns>\d+) ns, tick (?P<tick>-?\d+), initialized (?P<initialized>[01])")),
    "scenes": ("Native scene:", _pattern("Native scene:",
        r" frame (?P<frame>\d+), cinematic (?P<cinematic>[01]), player-input (?P<player_input>[01])")),
    "guest_work": ("Native guest work:", _pattern("Native guest work:",
        r" frame (?P<frame>\d+), draws (?P<draws>\d+), expansion (?P<expansion_ns>\d+) ns, "
        r"textures (?P<textures_ns>\d+) ns, state (?P<state_ns>\d+) ns, program (?P<program_ns>\d+) ns, "
        r"emit (?P<emit_ns>\d+) ns, submit (?P<submit_ns>\d+) ns")),
    "flushes": ("Native flush:", _pattern("Native flush:",
        r" frame (?P<frame>\d+), sequence (?P<sequence>\d+), reason (?P<reason>[A-Za-z][A-Za-z0-9_-]*), "
        r"commands (?P<commands>\d+), bytes (?P<bytes>\d+), start (?P<start_ns>\d+) ns, "
        r"end (?P<end_ns>\d+) ns, submit (?P<submit_ns>\d+) ns")),
    "packets": ("Native Metal packet:", _pattern("Native Metal packet:",
        r" sequence (?P<sequence>\d+), commands (?P<commands>\d+), bytes (?P<bytes>\d+), "
        r"start (?P<start_ns>\d+) ns, end (?P<end_ns>\d+) ns, copy (?P<packet_copy_ns>\d+) ns, "
        r"prepare (?P<prepare_ns>\d+) ns, encode (?P<encode_ns>\d+) ns, drawable (?P<drawable_wait_ns>\d+) ns, "
        r"commit (?P<commit_ns>\d+) ns, completion (?P<completion_wait_ns>\d+) ns, gpu (?P<gpu_ns>\d+) ns, "
        r"shader-misses (?P<shader_misses>\d+), shader-compile (?P<shader_compile_ns>\d+) ns, "
        r"pipelines (?P<pipelines>\d+), pipeline-create (?P<pipeline_create_ns>\d+) ns, "
        r"draws (?P<draws>\d+), passes (?P<passes>\d+), subresource-copies (?P<subresource_copies>\d+)")),
    "compiles": ("Native Metal compile:", _pattern("Native Metal compile:",
        r" sequence (?P<sequence>\d+), stage (?P<stage>vertex|fragment), source-bytes (?P<source_bytes>\d+), "
        r"fast (?P<fast>[01]), invariant (?P<invariant>[01]), start (?P<start_ns>\d+) ns, "
        r"end (?P<end_ns>\d+) ns, duration (?P<duration_ns>\d+) ns, success (?P<success>[01])")),
    "compile_identities": ("Native Metal compile identity:", _pattern("Native Metal compile identity:",
        r" sequence (?P<sequence>\d+), command-index (?P<command_index>\d+), program (?P<program>\d+), "
        r"generation (?P<generation>\d+), stage (?P<stage>vertex|fragment), "
        r"source-hash (?P<source_hash>[0-9a-fA-F]+), start (?P<start_ns>\d+) ns")),
    "pipeline_events": ("Native Metal pipeline:", _pattern("Native Metal pipeline:",
        r" sequence (?P<sequence>\d+), command-index (?P<command_index>\d+), program (?P<program>\d+), "
        r"generation (?P<generation>\d+), vertex-hash (?P<vertex_hash>[0-9a-fA-F]+), "
        r"fragment-hash (?P<fragment_hash>[0-9a-fA-F]+), packed (?P<packed>[0-9a-fA-F]+), "
        r"color-format (?P<color_format>\d+), depth-format (?P<depth_format>\d+), color-mask (?P<color_mask>\d+), "
        r"blend (?P<blend_enabled>[01])/(?P<blend_source>\d+)/(?P<blend_destination>\d+)/(?P<blend_operation>\d+), "
        r"start (?P<start_ns>\d+) ns, end (?P<end_ns>\d+) ns, duration (?P<duration_ns>\d+) ns, success (?P<success>[01])")),
    "programs": ("Native program:", _pattern("Native program:",
        r" frame (?P<frame>\d+), sequence (?P<sequence>\d+), command-index (?P<command_index>\d+), "
        r"program (?P<program>\d+), vertex-object (?P<vertex_object>\d+), vertex-handle (?P<vertex_handle>[0-9a-fA-F]+), "
        r"declaration-object (?P<declaration_object>\d+), loaded-slot (?P<loaded_slot>\d+), instructions (?P<instructions>\d+), "
        r"packed (?P<packed>[0-9a-fA-F]+), texture-modes (?P<texture_modes>[0-9a-fA-F]+), "
        r"samplers (?P<sampler_0>\d+)/(?P<sampler_1>\d+)/(?P<sampler_2>\d+)/(?P<sampler_3>\d+), "
        r"alpha-border (?P<alpha_border>\d+), volume-border (?P<volume_border>\d+), depth-contract (?P<depth_contract>[01]), "
        r"compilers (?P<vertex_compiler>\d+)/(?P<fragment_compiler>\d+), "
        r"sources (?P<vertex_source_bytes>\d+)/(?P<fragment_source_bytes>\d+) bytes, translation (?P<translation_ns>\d+) ns")),
    "camera_points": ("Native camera:", _pattern("Native camera:",
        r" tick (?P<tick>-?\d+), render-frame (?P<render_frame>-?\d+), kind (?P<kind>point), "
        r"point (?P<point>-?\d+), name (?P<name>.*?), transition (?P<transition>\d+), relative (?P<relative>-?\d+)")),
    "camera_animations": ("Native camera:", _pattern("Native camera:",
        r" tick (?P<tick>-?\d+), render-frame (?P<render_frame>-?\d+), kind (?P<kind>animation), "
        r"graph (?P<graph>-?\d+), animation (?P<animation>-?\d+), name (?P<name>.*?), frames (?P<animation_frames>-?\d+)")),
}
HEX_FIELDS = {"vertex_handle", "packed", "texture_modes", "source_hash", "vertex_hash", "fragment_hash"}
TEXT_FIELDS = {"reason", "stage", "name", "kind"}
BOOL_FIELDS = {"initialized", "cinematic", "player_input", "fast", "invariant", "success", "blend_enabled"}
HOST_TIME_FIELDS = ("packet_copy_ns", "prepare_ns", "encode_ns", "drawable_wait_ns", "commit_ns",
                    "completion_wait_ns", "gpu_ns", "shader_compile_ns", "pipeline_create_ns")
HOST_COUNT_FIELDS = ("shader_misses", "pipelines", "draws", "passes", "subresource_copies")
GUEST_DRAW_PHASE_FIELDS = ("expansion_ns", "textures_ns", "state_ns", "program_ns", "emit_ns")
LIMITATIONS = [
    "Guest flush frame + 1 identifies the completed Native timing/scene frame; sequence joins host packets.",
    "Host and guest monotonic timestamps have separate clock domains and are not subtracted from one another.",
    "GPU timing overlaps completion wait; prepare includes compile and pipeline creation. Counters are not exclusive phases.",
    "Shader stage/event durations may overlap under concurrent compilation; compare prepare and host packet wall time for stalls.",
    "Present gaps include simulation, guest work, cap waits and logging. Counter association alone is not proof of a stall cause.",
    "Cold means a shader miss/compile event or pipeline creation was observed; warm requires complete unique packet joins with none.",
    "Tick startup exclusion and renderer cache warmth are independent. Camera request markers contain no pose or motion evidence.",
    "Compile identities and pipeline events are optional; old logs cannot prove exact emitted-source or pipeline identities.",
    "Source hashes are diagnostic fingerprints only. Cache correctness requires full source and compiler-contract equality.",
    "Camera render-frame is a separate source counter. Native frame candidates share its simulation tick; they are not exact event-frame joins.",
    "Guest CPU is the sum of five instrumented draw phases after excluding nested submit time; it is not all guest frame work.",
    "Guest draw submit time includes synchronous submissions triggered during draws only and overlaps host packet time; it is not all frame submissions.",
    "Guest phase timestamps and diagnostic logging add measurement cost; captures with different instrumentation are not equal-work CPU comparisons.",
]


def parse_log(text):
    result = {name: [] for name in PATTERNS}
    result["parse_errors"] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        matches, markers = [], set()
        for name, (marker, pattern) in PATTERNS.items():
            if marker not in line:
                continue
            markers.add(marker)
            match = pattern.search(line)
            if match:
                matches.append((name, marker, match))
        # Multiple camera kinds share a marker. A valid kind must not become
        # a malformed row merely because it does not match the other kind.
        for marker in sorted(markers - {marker for _, marker, _ in matches}):
            result["parse_errors"].append(dict(line=line_number, marker=marker, text=line))
        for name, _, match in matches:
            row = {key: value if key in TEXT_FIELDS else int(value, 16 if key in HEX_FIELDS else 10)
                   for key, value in match.groupdict().items()}
            for key in BOOL_FIELDS.intersection(row):
                row[key] = bool(row[key])
            row["line"] = line_number
            result[name].append(row)
    return result


def _index(rows, key):
    index = defaultdict(list)
    for row in rows:
        index[row[key]].append(row)
    return index


def _percentile(values, fraction):
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def gap_summary(frames):
    intervals = [frame for frame in frames if frame["present_gap_ns"] is not None]
    values = [frame["present_gap_ns"] / 1e6 for frame in intervals]
    if not values:
        return dict(interval_count=0)
    elapsed = sum(frame["present_gap_ns"] for frame in intervals) / 1e9
    tick_intervals = [frame for frame in intervals if frame["tick_delta"] is not None]
    tick_elapsed = sum(frame["present_gap_ns"] for frame in tick_intervals) / 1e9
    return dict(interval_count=len(values), elapsed_seconds=elapsed, render_fps=len(values) / elapsed,
                p50_ms=_percentile(values, .5), p95_ms=_percentile(values, .95), p99_ms=_percentile(values, .99),
                max_ms=max(values), over_16_67_ms=sum(value > 1000 / 60 for value in values),
                over_33_33_ms=sum(value > 1000 / 30 for value in values), over_50_ms=sum(value > 50 for value in values),
                zero_tick_intervals=sum(frame["tick_delta"] == 0 for frame in tick_intervals),
                catchup_intervals=sum(frame["tick_delta"] > 1 for frame in tick_intervals),
                observed_simulation_hz=(sum(frame["tick_delta"] for frame in tick_intervals) / tick_elapsed
                                        if tick_elapsed else None),
                percentile_method="linear sorted rank (n-1)*p")


def _totals(frames):
    totals = Counter()
    for frame in frames:
        totals.update(frame["totals"])
    return dict(totals)


def _group_summary(frames, key):
    groups = defaultdict(list)
    for frame in frames:
        groups[str(frame[key])].append(frame)
    return {name: dict(frame_count=len(rows), gaps=gap_summary(rows), totals=_totals(rows))
            for name, rows in sorted(groups.items())}


def analyze_log(text, *, top=20, tick_cutoff=150, include_frames=False):
    if top < 0 or tick_cutoff < 0:
        raise ValueError("top and tick_cutoff must be nonnegative")
    parsed = parse_log(text)
    diagnostics = {"parse_errors": parsed["parse_errors"], "duplicate_sequences": [], "duplicate_frames": [],
                   "packet_mismatches": [], "record_errors": [], "discarded_intervals": [],
                   "missing_host_sequences": [], "orphan_host_sequences": [], "unattributed_flush_sequences": [],
                   "unattributed_compile_lines": [], "unattributed_program_lines": [], "unattributed_scene_lines": [],
                   "unattributed_compile_identity_lines": [], "unmatched_compile_identity_lines": [],
                   "duplicate_compile_identities": [], "duplicate_compile_records": [],
                   "unattributed_pipeline_lines": [], "unattributed_guest_work_lines": []}
    guest = _index(parsed["flushes"], "sequence")
    host = _index(parsed["packets"], "sequence")
    compiles = _index(parsed["compiles"], "sequence")
    compile_identities = _index(parsed["compile_identities"], "sequence")
    pipeline_events = _index(parsed["pipeline_events"], "sequence")
    programs = _index(parsed["programs"], "sequence")
    timings = _index(parsed["timings"], "frame")
    scenes = _index(parsed["scenes"], "frame")
    guest_work = _index(parsed["guest_work"], "frame")
    for source, index in (("guest", guest), ("host", host)):
        for sequence, rows in index.items():
            if len(rows) > 1:
                diagnostics["duplicate_sequences"].append(dict(source=source, sequence=sequence,
                                                               lines=[row["line"] for row in rows]))
    for source, index in (("timing", timings), ("scene", scenes), ("guest_work", guest_work)):
        for frame, rows in index.items():
            if len(rows) > 1:
                diagnostics["duplicate_frames"].append(dict(source=source, frame=frame,
                                                            lines=[row["line"] for row in rows]))
    for name, duration_key in (("flushes", "submit_ns"), ("compiles", "duration_ns"),
                               ("pipeline_events", "duration_ns"), ("packets", None)):
        for row in parsed[name]:
            if row["end_ns"] < row["start_ns"] or (duration_key and row[duration_key] != row["end_ns"] - row["start_ns"]):
                diagnostics["record_errors"].append(dict(source=name, line=row["line"], error="invalid duration"))
    invalid_lines = {row["line"] for row in diagnostics["record_errors"]}
    ambiguous_frames = {row["frame"] + 1 for rows in guest.values() if len(rows) != 1 for row in rows}

    packet_by_frame = defaultdict(list)
    attributed_compile_lines, attributed_program_lines = set(), set()
    attributed_identity_lines, attributed_pipeline_lines = set(), set()
    for sequence, rows in guest.items():
        if len(rows) != 1:
            diagnostics["unattributed_flush_sequences"].append(sequence)
            continue
        flush = rows[0]
        frame = flush["frame"] + 1
        matching = host.get(sequence, [])
        packet = matching[0] if len(matching) == 1 else None
        valid = packet is not None and flush["line"] not in invalid_lines
        if not matching:
            diagnostics["missing_host_sequences"].append(sequence)
        if packet:
            valid = valid and packet["line"] not in invalid_lines
            for key in ("commands", "bytes"):
                if flush[key] != packet[key]:
                    valid = False
                    diagnostics["packet_mismatches"].append(dict(sequence=sequence, field=key,
                        guest=flush[key], host=packet[key], guest_line=flush["line"], host_line=packet["line"]))
        identity_rows, pipeline_rows = [], []
        for name, rows, target in (("compile_identities", compile_identities.get(sequence, []), identity_rows),
                                   ("pipeline_events", pipeline_events.get(sequence, []), pipeline_rows)):
            for row in rows:
                if row["command_index"] >= flush["commands"] or not row["program"] or not row["generation"]:
                    diagnostics["record_errors"].append(dict(source=name, line=row["line"],
                        error="command index or program reference disagrees with flush"))
                    continue
                target.append(row)
        by_compile = defaultdict(list)
        for row in identity_rows:
            by_compile[(row["stage"], row["start_ns"])].append(row)
        compile_rows = []
        compile_records = defaultdict(list)
        for row in compiles.get(sequence, []):
            compile_records[(row["stage"], row["start_ns"])].append(row)
        for row in compiles.get(sequence, []):
            matching = by_compile.get((row["stage"], row["start_ns"]), [])
            records = compile_records[(row["stage"], row["start_ns"])]
            identity = matching[0] if len(matching) == 1 and len(records) == 1 else None
            compile_rows.append(dict(row, identity=identity))
            if len(matching) > 1:
                diagnostics["duplicate_compile_identities"].append(dict(sequence=sequence, stage=row["stage"],
                    start_ns=row["start_ns"], lines=[item["line"] for item in matching]))
        for (stage, started), records in compile_records.items():
            if len(records) > 1:
                diagnostics["duplicate_compile_records"].append(dict(sequence=sequence, stage=stage,
                    start_ns=started, lines=[row["line"] for row in records]))
        matched_identity_lines = {row["identity"]["line"] for row in compile_rows if row["identity"]}
        diagnostics["unmatched_compile_identity_lines"].extend(
            row["line"] for row in identity_rows if row["line"] not in matched_identity_lines)
        program_rows = []
        for program in programs.get(sequence, []):
            if program["frame"] != flush["frame"] or program["command_index"] >= flush["commands"]:
                diagnostics["record_errors"].append(dict(source="programs", line=program["line"],
                                                        error="frame or command index disagrees with flush"))
                continue
            program_rows.append(program)
        item = dict(sequence=sequence, guest=flush, host=packet, join_complete=valid,
                    compiles=compile_rows, programs=program_rows, compile_identities=identity_rows,
                    pipeline_events=pipeline_rows)
        packet_by_frame[frame].append(item)
        if len(timings.get(frame, [])) == 1:
            attributed_compile_lines.update(row["line"] for row in compile_rows)
            attributed_program_lines.update(row["line"] for row in program_rows)
            attributed_identity_lines.update(row["line"] for row in identity_rows)
            attributed_pipeline_lines.update(row["line"] for row in pipeline_rows)
        else:
            diagnostics["unattributed_flush_sequences"].append(sequence)
    diagnostics["orphan_host_sequences"] = sorted(sequence for sequence in host if len(guest.get(sequence, [])) != 1)
    diagnostics["unattributed_compile_lines"] = [row["line"] for row in parsed["compiles"]
                                                 if row["line"] not in attributed_compile_lines]
    diagnostics["unattributed_program_lines"] = [row["line"] for row in parsed["programs"]
                                                 if row["line"] not in attributed_program_lines]
    diagnostics["unattributed_scene_lines"] = [row["line"] for row in parsed["scenes"]
                                               if len(timings.get(row["frame"], [])) != 1]
    diagnostics["unattributed_guest_work_lines"] = [row["line"] for row in parsed["guest_work"]
        if len(timings.get(row["frame"], [])) != 1 or len(guest_work[row["frame"]]) != 1]
    diagnostics["unattributed_compile_identity_lines"] = [row["line"] for row in parsed["compile_identities"]
                                                          if row["line"] not in attributed_identity_lines]
    diagnostics["unattributed_pipeline_lines"] = [row["line"] for row in parsed["pipeline_events"]
                                                  if row["line"] not in attributed_pipeline_lines]
    cameras = sorted(parsed["camera_points"] + parsed["camera_animations"], key=lambda row: row["line"])
    tick_frames = defaultdict(list)
    for row in parsed["timings"]:
        if row["initialized"] and len(timings[row["frame"]]) == 1:
            tick_frames[row["tick"]].append(row["frame"])
    camera_markers = [dict(row, candidate_native_frames=tick_frames[row["tick"]],
                           association="same simulation tick candidates") for row in cameras]

    frames, previous = [], None
    for timing in parsed["timings"]:
        if len(timings[timing["frame"]]) != 1:
            previous = None
            continue
        frame_number = timing["frame"]
        items = packet_by_frame.get(frame_number, [])
        work_rows = guest_work.get(frame_number, [])
        work = work_rows[0] if len(work_rows) == 1 else None
        totals = {key: 0 for key in ("guest_submit_ns", "host_packet_ns", "commands", "bytes", "packets",
                    "joined_packets", "compile_events", "compile_event_ns", "compile_failures", "programs",
                    "translation_ns", "pipeline_events", "pipeline_event_ns", "pipeline_failures") + HOST_TIME_FIELDS + HOST_COUNT_FIELDS}
        if work:
            totals["guest_work_frames"] = 1
            totals["guest_work_draws"] = work["draws"]
            totals["guest_cpu_ns"] = sum(work[key] for key in GUEST_DRAW_PHASE_FIELDS)
            totals["guest_draw_submit_ns"] = work["submit_ns"]
            for key in GUEST_DRAW_PHASE_FIELDS:
                totals["guest_" + key] = work[key]
        reasons = Counter()
        for item in items:
            flush, packet = item["guest"], item["host"]
            reasons[flush["reason"]] += 1
            totals["packets"] += 1
            totals["commands"] += flush["commands"]
            totals["bytes"] += flush["bytes"]
            totals["guest_submit_ns"] += flush["submit_ns"]
            if packet:
                totals["joined_packets"] += 1
                totals["host_packet_ns"] += max(0, packet["end_ns"] - packet["start_ns"])
                for key in HOST_TIME_FIELDS + HOST_COUNT_FIELDS:
                    totals[key] += packet[key]
            for row in item["compiles"]:
                totals["compile_events"] += 1
                totals["compile_event_ns"] += row["duration_ns"]
                totals["compile_failures"] += not row["success"]
            for row in item["programs"]:
                totals["programs"] += 1
                totals["translation_ns"] += row["translation_ns"]
            for row in item["pipeline_events"]:
                totals["pipeline_events"] += 1
                totals["pipeline_event_ns"] += row["duration_ns"]
                totals["pipeline_failures"] += not row["success"]
        complete = bool(items) and frame_number not in ambiguous_frames and all(item["join_complete"] for item in items)
        cold_shader = bool(totals["shader_misses"] or totals["compile_events"])
        cold_pipeline = bool(totals["pipelines"] or totals["pipeline_events"])
        cache = "cold" if cold_shader or cold_pipeline else "warm" if complete else "unknown"
        scene_rows = scenes.get(frame_number, [])
        scene = scene_rows[0] if len(scene_rows) == 1 else None
        # Uninitialized scene reads are intentionally gated to false by the
        # engine, and therefore are not evidence that gameplay has begun.
        scene_state = ("cinematic" if scene["cinematic"] else "input-enabled" if scene["player_input"] else "input-disabled") \
            if scene and timing["initialized"] else "unknown"
        gap, tick_delta, previous_frame = None, None, None
        after_startup = False
        if previous:
            previous_frame = previous["frame"]
            error = None
            if frame_number != previous_frame + 1:
                error = "nonconsecutive frame"
            elif timing["ns"] <= previous["ns"]:
                error = "nonincreasing monotonic time"
            elif previous["initialized"] and timing["initialized"] and timing["tick"] < previous["tick"]:
                error = "backwards simulation tick"
            if error:
                diagnostics["discarded_intervals"].append(dict(previous_frame=previous_frame, frame=frame_number, error=error))
            else:
                gap = timing["ns"] - previous["ns"]
                if previous["initialized"] and timing["initialized"]:
                    tick_delta = timing["tick"] - previous["tick"]
                    after_startup = previous["tick"] >= tick_cutoff and timing["tick"] >= tick_cutoff
        frames.append(dict(frame=frame_number, guest_frame=frame_number - 1, timing=timing, scene=scene, guest_work=work,
                           scene_state=scene_state, previous_frame=previous_frame, present_gap_ns=gap,
                           present_gap_ms=gap / 1e6 if gap is not None else None, tick_delta=tick_delta,
                           after_startup=after_startup, cache_state=cache, cold_shader=cold_shader,
                           cold_pipeline=cold_pipeline, packet_coverage_complete=complete,
                           reasons=dict(reasons), totals=totals, packets=items))
        previous = timing
    post_startup = [frame for frame in frames if frame["after_startup"]]
    top_frames = sorted((frame for frame in frames if frame["present_gap_ns"] is not None),
                        key=lambda frame: (-frame["present_gap_ns"], frame["frame"]))[:top]
    reason_totals = defaultdict(Counter)
    for row in parsed["flushes"]:
        reason_totals[row["reason"]].update(packets=1, commands=row["commands"], bytes=row["bytes"], submit_ns=row["submit_ns"])
    result = dict(schema_version=1, tick_cutoff=tick_cutoff, limitations=LIMITATIONS,
                  counts={key: len(parsed[key]) for key in PATTERNS}, diagnostics=diagnostics,
                  camera_markers=camera_markers,
                  summary=dict(frame_count=len(frames), all_gaps=gap_summary(frames),
                               post_startup_gaps=gap_summary(post_startup), totals=_totals(frames),
                               by_cache_state=_group_summary(frames, "cache_state"),
                               post_startup_by_cache_state=_group_summary(post_startup, "cache_state"),
                               by_scene=_group_summary(frames, "scene_state"),
                               post_startup_by_scene=_group_summary(post_startup, "scene_state"),
                               flush_reasons={name: dict(values) for name, values in sorted(reason_totals.items())}),
                  top_gaps=top_frames)
    result["post_startup_top_gaps"] = sorted(post_startup, key=lambda frame: (-frame["present_gap_ns"], frame["frame"]))[:top]
    if include_frames:
        result["frames"] = frames
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path, help="Existing combined guest/host diagnostic log")
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout; the input is never overwritten")
    parser.add_argument("--top", type=int, default=20, help="Number of largest completed-present gaps (default 20)")
    parser.add_argument("--tick-cutoff", type=int, default=150, help="Separate intervals beyond this simulation tick (default 150)")
    parser.add_argument("--include-frames", action="store_true", help="Include every frame and its joined records")
    args = parser.parse_args(argv)
    if args.top < 0 or args.tick_cutoff < 0:
        parser.error("--top and --tick-cutoff must be nonnegative")
    if args.output and (args.log.resolve() == args.output.resolve() or
                        args.output.exists() and args.log.samefile(args.output)):
        parser.error("--output cannot overwrite the input log")
    result = analyze_log(args.log.read_text(errors="replace"), top=args.top, tick_cutoff=args.tick_cutoff,
                         include_frames=args.include_frames)
    result["input"] = str(args.log.resolve())
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
