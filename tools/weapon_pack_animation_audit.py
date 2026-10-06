"""Bounded read-only animation clip audit for pinned Invader HEK antr tags.

Layouts follow Invader7d25a855's model_animations.json and HEK serializer.
Pointers in source tags are unused; child blocks follow their parent arrays.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

# size, (field offset, array child type or 'dependency'/'data')
LAYOUTS = {
    "root": (128, ((0, "object"), (12, "seat"), (24, "weapon_animations"),
                   (36, "vehicle"), (48, "device"), (60, "index"), (72, "fp"),
                   (84, "sound"), (104, "node"), (116, "clip"))),
    "object": (20, ()), "index": (2, ()), "ik": (64, ()),
    "seat": (100, ((64, "index"), (76, "ik"), (88, "weapon"))),
    "weapon": (188, ((152, "index"), (164, "ik"), (176, "weapon_type"))),
    "weapon_type": (60, ((48, "index"),)),
    "weapon_animations": (28, ((16, "index"),)),
    "vehicle": (116, ((92, "index"), (104, "suspension"))),
    "suspension": (20, ()), "device": (96, ((84, "index"),)),
    "fp": (28, ((16, "index"),)), "sound": (20, ((0, "dependency"),)),
    "node": (64, ()), "clip": (180, ((72, "data"), (140, "data"), (160, "data"))),
}


def graph_records(path: Path) -> dict:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Animation source tag exceeds the audit bound")
    data = path.read_bytes()
    if len(data) < 192 or data[36:40] != b"antr" or data[60:64] != b"blam":
        raise ValueError("Animation audit requires an HEK model_animations tag")
    cursor = 192
    records = {}
    nodes = []
    seats = {}

    def consume(size: int) -> bytes:
        nonlocal cursor
        if size < 0 or cursor + size > len(data):
            raise ValueError("Animation child block exceeds source tag bounds")
        result = data[cursor:cursor + size]
        cursor += size
        return result

    def label(position: int) -> str:
        raw = data[position:position + 32]
        if b"\0" not in raw:
            raise ValueError("Unterminated animation label")
        return raw.split(b"\0", 1)[0].decode("ascii")

    def walk(kind: str, position: int, seat: str | None = None) -> None:
        nonlocal cursor
        size, fields = LAYOUTS[kind]
        if position < 64 or position + size > len(data):
            raise ValueError("Animation parent block exceeds source tag bounds")
        if kind == "seat":
            seat = label(position).casefold()
            seats.setdefault(seat, set())
        elif kind == "weapon_type" and seat is not None:
            seats[seat].add(label(position).casefold())
        elif kind == "node":
            nodes.append({"name": label(position),
                          "next_sibling_node_index": str(struct.unpack_from(">h", data, position + 32)[0]),
                          "first_child_node_index": str(struct.unpack_from(">h", data, position + 34)[0]),
                          "parent_node_index": str(struct.unpack_from(">h", data, position + 36)[0])})
        payloads = []
        for offset, child in fields:
            at = position + offset
            if child == "dependency":
                count = struct.unpack_from(">I", data, at + 8)[0]
                if count:
                    value = consume(count + 1)
                    if count > 255 or value[-1:] != b"\0" or b"\0" in value[:-1]:
                        raise ValueError("Invalid animation sound dependency")
            elif child == "data":
                count = struct.unpack_from(">I", data, at)[0]
                if count > 1048576:
                    raise ValueError("Animation payload exceeds reviewed limits")
                payloads.append(hashlib.sha256(consume(count)).hexdigest())
            else:
                count = struct.unpack_from(">I", data, at)[0]
                if count > 2048:
                    raise ValueError("Animation array exceeds reviewed limits")
                child_size = LAYOUTS[child][0]
                start = cursor
                consume(count * child_size)
                for index in range(count):
                    walk(child, start + index * child_size, seat)
        if kind == "clip":
            raw_name = data[position:position + 32]
            if b"\0" not in raw_name:
                raise ValueError("Unterminated animation clip name")
            name = raw_name.split(b"\0", 1)[0].decode("ascii")
            if not name or name in records:
                raise ValueError("Animation clip names must be unique for this audit")
            header_fields = {field: struct.unpack_from(">H", data, position + offset)[0]
                             for offset, field in ((32, "type"), (34, "frame_count"), (36, "frame_size"),
                                 (38, "frame_info_type"), (44, "node_count"), (46, "loop_frame_index"),
                                 (52, "key_frame_index"), (54, "second_key_frame_index"),
                                 (56, "next_animation"), (58, "flags"), (60, "sound"), (62, "sound_frame_index"))}
            header_fields.update(node_list_checksum=struct.unpack_from(">i", data, position + 40)[0],
                                 weight=struct.unpack_from(">f", data, position + 48)[0],
                                 left_foot_frame_index=struct.unpack_from(">b", data, position + 64)[0],
                                 right_foot_frame_index=struct.unpack_from(">b", data, position + 65)[0])
            records[name] = {"header_sha256": hashlib.sha256(data[position:position + size]).hexdigest(),
                             "header_fields": header_fields,
                             "frame_info_sha256": payloads[0], "default_data_sha256": payloads[1],
                             "frame_data_sha256": payloads[2]}

    walk("root", 64)
    if cursor != len(data):
        raise ValueError("Animation tag has unparsed data; source layout needs review")
    return {"clips": records, "nodes": nodes,
            "seat_weapon_labels": {key: sorted(value) for key, value in seats.items()}}


def clip_records(path: Path) -> dict:
    return graph_records(path)["clips"]


def compare_clips(stock: Path, imported: Path) -> dict:
    baseline, candidate = clip_records(stock), clip_records(imported)
    shared = sorted(baseline.keys() & candidate.keys())
    changed_payloads, changed_headers = {}, {}
    for name in shared:
        if any(baseline[name][field] != candidate[name][field]
               for field in ("frame_info_sha256", "default_data_sha256", "frame_data_sha256")):
            changed_payloads[name] = {"stock": baseline[name], "imported": candidate[name]}
        if baseline[name]["header_sha256"] != candidate[name]["header_sha256"]:
            fields = {field: {"stock": value, "imported": candidate[name]["header_fields"][field]}
                      for field, value in baseline[name]["header_fields"].items()
                      if value != candidate[name]["header_fields"][field]}
            stock_next = baseline[name]["header_fields"]["next_animation"]
            imported_next = candidate[name]["header_fields"]["next_animation"]
            changed_headers[name] = {"stock": baseline[name]["header_sha256"],
                                     "imported": candidate[name]["header_sha256"], "changed_fields": fields,
                                     "stock_next_clip": list(baseline)[stock_next] if stock_next < len(baseline) else None,
                                     "imported_next_clip": list(candidate)[imported_next] if imported_next < len(candidate) else None}
    return {"stock_clip_count": len(baseline), "imported_clip_count": len(candidate),
            "shared_clip_count": len(shared), "added_clip_names": sorted(candidate.keys() - baseline.keys()),
            "missing_stock_clip_names": sorted(baseline.keys() - candidate.keys()),
            "changed_shared_payloads": changed_payloads, "changed_shared_headers": changed_headers,
            "scope": "Compatible imported graph selected only for Fiesta; payload equality is not presumed"}
