# -*- coding: utf-8 -*-
"""Merge CinderQuestieData (+ gaps) into pfQuest-turtle db files."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from lupa import LuaRuntime

# tools/ → addon root → db/
ROOT = Path(__file__).resolve().parent.parent
PFQ = ROOT / "db"

# источники (поправь под свои пути)
CINDER = Path(
    r"F:\Game\WOW Turtle\1_14\Ravencraft 1.14\_classic_era_\Interface\AddOns"
    r"\CinderQuestieData\Data.lua"
)
BASE_ITEMS = Path(
    r"F:\Game\WOW Turtle\twmoa_1180\Interface\AddOns\pfQuest\db\items.lua"
)
# опционально: куда ещё скопировать db после мержа (None = не копировать)
ADDONS = None

lua = LuaRuntime(unpack_returned_tuples=True)


def load_cinder_blob(src: str, name: str):
    m = re.search(rf"ns\.{name} = \[\[return ({{.*?}})\]\]", src, re.S)
    if not m:
        raise SystemExit(f"missing ns.{name}")
    return lua.eval(m.group(1))


def lua_list(tbl) -> list[int]:
    if tbl is None:
        return []
    return [int(tbl[k]) for k in tbl if tbl[k] is not None]


def lua_spawns(spawns_tbl) -> list[tuple[float, float, int]]:
    if spawns_tbl is None:
        return []
    coords = []
    for zone in spawns_tbl:
        pts = spawns_tbl[zone]
        if pts is None:
            continue
        zid = int(zone)
        for i in pts:
            pt = pts[i]
            if pt is None:
                continue
            coords.append((float(pt[1]), float(pt[2]), zid))
    return coords


def fmt_num(n: float) -> str:
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.1f}"


def format_item_entry(iid: int, npcs: dict[int, int], objs: dict[int, int]) -> str:
    lines = [f"  [{iid}] = {{"]
    if objs:
        lines.append('    ["O"] = {')
        for oid in sorted(objs):
            lines.append(f"      [{oid}] = {objs[oid]},")
        lines.append("    },")
    if npcs:
        lines.append('    ["U"] = {')
        for uid in sorted(npcs):
            lines.append(f"      [{uid}] = {npcs[uid]},")
        lines.append("    },")
    lines.append("  },")
    return "\n".join(lines)


def format_unit_entry(
    uid: int, coords: list[tuple[float, float, int]], fac: str | None, lvl: str
) -> str:
    lines = [f"  [{uid}] = {{"]
    if coords:
        lines.append('    ["coords"] = {')
        for i, (x, y, z) in enumerate(coords, 1):
            lines.append(f"      [{i}] = {{ {fmt_num(x)}, {fmt_num(y)}, {z}, 0 }},")
        lines.append("    },")
    if fac:
        lines.append(f'    ["fac"] = "{fac}",')
    lines.append(f'    ["lvl"] = "{lvl}",')
    lines.append("  },")
    return "\n".join(lines)


def format_object_entry(oid: int, coords: list[tuple[float, float, int]]) -> str:
    lines = [f"  [{oid}] = {{"]
    if coords:
        lines.append('    ["coords"] = {')
        for i, (x, y, z) in enumerate(coords, 1):
            lines.append(f"      [{i}] = {{ {fmt_num(x)}, {fmt_num(y)}, {z} }},")
        lines.append("    },")
    lines.append("  },")
    return "\n".join(lines)


def extract_entry(text: str, iid: int) -> tuple[int, int, str] | None:
    """Return (start, end, body) of top-level `  [id] = ...` (exactly 2-space indent)."""
    # ^  [id] =  — must be line-start so nested `      [id]` never matches
    m = re.search(rf"(?m)^  \[{iid}\]\s*=\s*", text)
    if not m:
        return None
    start = m.start()
    i = m.end()
    if i >= len(text):
        return None
    if text[i] != "{":
        m2 = re.match(r'"[^"]*"|_', text[i:])
        if not m2:
            return None
        end = i + m2.end()
        if end < len(text) and text[end] == ",":
            end += 1
        return start, end, text[start:end].rstrip(",").rstrip()
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                j += 1
                break
        elif c in "'\"":
            q = c
            j += 1
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == q:
                    j += 1
                    break
                j += 1
            continue
        j += 1
    end = j
    if end < len(text) and text[end] == ",":
        end += 1
    return start, end, text[start:j]


def parse_chance_map(body: str, key: str) -> dict[int, int]:
    """Parse ["U"] = { [id] = chance, ... } from entry body."""
    m = re.search(rf'\["{key}"\]\s*=\s*\{{', body)
    if not m:
        return {}
    i = m.end() - 1
    depth = 0
    j = i
    while j < len(body):
        c = body[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    block = body[i:j]
    out: dict[int, int] = {}
    for id_, ch in re.findall(r"\[(\d+)\]\s*=\s*([0-9.]+)", block):
        # keep int if whole number
        fv = float(ch)
        out[int(id_)] = int(fv) if abs(fv - int(fv)) < 1e-9 else int(fv)
    return out


def rebuild_with_updates(text: str, updates: dict[int, str], inserts: dict[int, str]) -> str:
    m = re.search(r"(pfDB\[[^\]]+\]\[[^\]]+\]\s*=\s*\{)", text)
    if not m:
        raise SystemExit("pfDB header not found")
    header_end = m.end()
    depth = 0
    i = header_end - 1
    end = None
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        elif c in "'\"":
            q = c
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == q:
                    break
                i += 1
        i += 1
    if end is None:
        raise SystemExit("could not find table end")

    body = text[header_end:end]
    # apply updates sorted by position descending to keep indices stable
    positions: list[tuple[int, int, int, str]] = []
    for iid, new_entry in updates.items():
        found = extract_entry(body, iid)
        if not found:
            inserts[iid] = new_entry
            continue
        s, e, _ = found
        positions.append((s, e, iid, new_entry))
    positions.sort(key=lambda x: -x[0])
    for s, e, iid, new_entry in positions:
        body = body[:s] + new_entry + body[e:]

    if inserts:
        add = "\n".join(inserts[i] for i in sorted(inserts))
        if not body.endswith("\n"):
            body += "\n"
        body += add + "\n"

    return text[:header_end] + body + text[end:]


def locale_insert(path: Path, entries: dict[int, str]) -> int:
    if not path.exists() or not entries:
        return 0
    text = path.read_text(encoding="utf-8")
    to_add = {
        i: n
        for i, n in entries.items()
        if not re.search(rf"(?m)^  \[{i}\]\s*=", text)
    }
    if not to_add:
        return 0
    m = re.search(r"(pfDB\[[^\]]+\]\[[^\]]+\]\s*=\s*\{)", text)
    if not m:
        return 0
    # find end
    depth = 0
    i = m.end() - 1
    end = None
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end is None:
        return 0
    lines = []
    for iid in sorted(to_add):
        name = to_add[iid].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  [{iid}] = "{name}",')
    add = "\n".join(lines) + "\n"
    new = text[:end] + add + text[end:]
    path.write_text(new, encoding="utf-8", newline="\n")
    return len(to_add)


def base_has_sources(base_text: str, iid: int) -> bool:
    found = extract_entry(base_text, iid)
    if not found:
        return False
    body = found[2]
    return '["U"]' in body or '["O"]' in body or '["V"]' in body or '["R"]' in body


def main() -> int:
    print("loading Cinder…")
    src = CINDER.read_text(encoding="utf-8")
    item_data = load_cinder_blob(src, "itemData")
    npc_data = load_cinder_blob(src, "npcData")
    object_data = load_cinder_blob(src, "objectData")

    cinder_drops: dict[int, tuple[list[int], list[int]]] = {}
    item_names: dict[int, str] = {}
    for iid in item_data:
        e = item_data[iid]
        npcs = lua_list(e[2])
        objs = lua_list(e[3])
        iid = int(iid)
        if e[1]:
            item_names[iid] = str(e[1])
        if npcs or objs:
            cinder_drops[iid] = (npcs, objs)

    print(f"cinder items with U/O drops: {len(cinder_drops)}")

    base_text = BASE_ITEMS.read_text(encoding="utf-8") if BASE_ITEMS.exists() else ""
    items_path = PFQ / "items-turtle.lua"
    text = items_path.read_text(encoding="utf-8")

    updates: dict[int, str] = {}
    inserts: dict[int, str] = {}
    needed_units: set[int] = set()
    needed_objects: set[int] = set()
    n_filled = n_merged = n_inserted = n_skip_base = 0

    for iid, (npcs, objs) in sorted(cinder_drops.items()):
        needed_units.update(npcs)
        needed_objects.update(objs)
        found = extract_entry(text, iid)
        if found is None:
            # only insert if base also lacks sources (avoid wiping vanilla with turtle stub)
            if base_has_sources(base_text, iid):
                n_skip_base += 1
                continue
            npcs_m = {n: 100 for n in npcs}
            objs_m = {o: 100 for o in objs}
            inserts[iid] = format_item_entry(iid, npcs_m, objs_m)
            n_inserted += 1
            continue

        _, _, body = found
        npcs_m = parse_chance_map(body, "U")
        objs_m = parse_chance_map(body, "O")
        changed = False
        # empty or missing keys: add from cinder without overwriting existing chances
        for n in npcs:
            if n not in npcs_m:
                npcs_m[n] = 100
                changed = True
        for o in objs:
            if o not in objs_m:
                objs_m[o] = 100
                changed = True
        if not changed:
            continue
        if not npcs_m and not objs_m and (npcs or objs):
            # was empty
            npcs_m = {n: 100 for n in npcs}
            objs_m = {o: 100 for o in objs}
            n_filled += 1
        else:
            n_merged += 1
        updates[iid] = format_item_entry(iid, npcs_m, objs_m)

    text2 = rebuild_with_updates(text, updates, inserts)
    items_path.write_text(text2, encoding="utf-8", newline="\n")
    print(
        f"items: filled/merged updates={len(updates)} inserts={n_inserted} "
        f"skip_base_has_src={n_skip_base}"
    )

    # units
    units_path = PFQ / "units-turtle.lua"
    utext = units_path.read_text(encoding="utf-8")
    unit_updates: dict[int, str] = {}
    unit_inserts: dict[int, str] = {}
    unit_names: dict[int, str] = {}
    units_patched = units_added = 0

    for uid in sorted(needed_units):
        npc = npc_data[uid]
        if npc is None:
            continue
        coords = lua_spawns(npc[7])
        fac = npc[13]
        fac_s = str(fac) if fac not in (None, 0) else None
        min_l = int(npc[4] or 0)
        max_l = int(npc[5] or min_l)
        lvl = str(min_l) if min_l == max_l else f"{min_l}-{max_l}"
        if npc[1]:
            unit_names[uid] = str(npc[1])
        entry = format_unit_entry(uid, coords, fac_s, lvl)
        found = extract_entry(utext, uid)
        if found:
            body = found[2]
            if '["coords"]' not in body and coords:
                unit_updates[uid] = entry
                units_patched += 1
        elif coords:
            unit_inserts[uid] = entry
            units_added += 1

    if unit_updates or unit_inserts:
        utext2 = rebuild_with_updates(utext, unit_updates, unit_inserts)
        units_path.write_text(utext2, encoding="utf-8", newline="\n")
    print(f"units patched={units_patched} added={units_added}")

    # objects
    objects_path = PFQ / "objects-turtle.lua"
    otext = objects_path.read_text(encoding="utf-8")
    obj_updates: dict[int, str] = {}
    obj_inserts: dict[int, str] = {}
    obj_names: dict[int, str] = {}
    obj_patched = obj_added = 0
    for oid in sorted(needed_objects):
        obj = object_data[oid]
        if obj is None:
            continue
        coords = lua_spawns(obj[4])
        if obj[1]:
            obj_names[oid] = str(obj[1])
        entry = format_object_entry(oid, coords)
        found = extract_entry(otext, oid)
        if found:
            if '["coords"]' not in found[2] and coords:
                obj_updates[oid] = entry
                obj_patched += 1
        else:
            if coords:
                obj_inserts[oid] = entry
                obj_added += 1
    if obj_updates or obj_inserts:
        otext2 = rebuild_with_updates(otext, obj_updates, obj_inserts)
        objects_path.write_text(otext2, encoding="utf-8", newline="\n")
    print(f"objects patched={obj_patched} added={obj_added}")

    # locales (enUS)
    n_il = locale_insert(PFQ / "enUS" / "items-turtle.lua", item_names)
    n_ul = locale_insert(PFQ / "enUS" / "units-turtle.lua", unit_names)
    n_ol = locale_insert(PFQ / "enUS" / "objects-turtle.lua", obj_names)
    print(f"locales added items={n_il} units={n_ul} objects={n_ol}")

    # verify 41687
    t2 = items_path.read_text(encoding="utf-8")
    found = extract_entry(t2, 41687)
    print("41687:", found[2] if found else "MISSING")

    if ADDONS and ADDONS.is_dir():
        for name in (
            "items-turtle.lua",
            "units-turtle.lua",
            "objects-turtle.lua",
            "enUS/items-turtle.lua",
            "enUS/units-turtle.lua",
            "enUS/objects-turtle.lua",
        ):
            src_f = PFQ / name
            dst = ADDONS / name
            if src_f.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(src_f.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        print("synced -> AddOns")

    return 0


if __name__ == "__main__":
    sys.exit(main())
