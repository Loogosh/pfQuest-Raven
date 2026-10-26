# -*- coding: utf-8 -*-
"""Insert Cinder quests missing from both base pfQuest and turtle overlay."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent
PFQ = ROOT / "db"

CINDER = Path(
    r"F:\Game\WOW Turtle\1_14\Ravencraft 1.14\_classic_era_\Interface\AddOns"
    r"\CinderQuestieData\Data.lua"
)
BASE = Path(r"F:\Game\WOW Turtle\twmoa_1180\Interface\AddOns\pfQuest\db\quests.lua")
ADDONS = None  # опциональный sync в игровой AddOns

lua = LuaRuntime(unpack_returned_tuples=True)


def top_level_ids(text: str) -> set[int]:
    return {int(x) for x in re.findall(r"(?m)^  \[(\d+)\]\s*=", text)}


def lua_id_list(tbl) -> list[int]:
    if tbl is None:
        return []
    out = []
    for k in tbl:
        v = tbl[k]
        if v is None:
            continue
        # Questie sometimes nests {id, nil} inside objective rows
        if hasattr(v, "keys") or type(v).__name__ == "LuaTable":
            try:
                out.append(int(v[1]))
                continue
            except Exception:
                pass
        try:
            out.append(int(v))
        except Exception:
            pass
    return out


def started_finished(tbl) -> tuple[list[int], list[int], list[int]]:
    """Questie startedBy/finishedBy: {npcs, objects, items?}."""
    if tbl is None:
        return [], [], []
    npcs = lua_id_list(tbl[1]) if tbl[1] is not None else []
    objs = lua_id_list(tbl[2]) if tbl[2] is not None else []
    items = lua_id_list(tbl[3]) if tbl[3] is not None else []
    return npcs, objs, items


def objectives_items_units_objects(obj_tbl) -> tuple[list[int], list[int], list[int]]:
    """
    Questie objectives index 10:
      { creatureObjectives, objectObjectives, itemObjectives, ... }
    creature/object rows are often {id, ...}; items are ids.
    """
    if obj_tbl is None:
        return [], [], []
    units, objects, items = [], [], []
    creat = obj_tbl[1]
    if creat is not None:
        for k in creat:
            row = creat[k]
            if row is None:
                continue
            try:
                units.append(int(row[1]))
            except Exception:
                try:
                    units.append(int(row))
                except Exception:
                    pass
    objs = obj_tbl[2]
    if objs is not None:
        for k in objs:
            row = objs[k]
            if row is None:
                continue
            try:
                objects.append(int(row[1]))
            except Exception:
                try:
                    objects.append(int(row))
                except Exception:
                    pass
    it = obj_tbl[3]
    if it is not None:
        for k in it:
            row = it[k]
            if row is None:
                continue
            try:
                items.append(int(row[1]))
            except Exception:
                try:
                    items.append(int(row))
                except Exception:
                    pass
    return units, objects, items


def fmt_id_list(ids: list[int]) -> str:
    return ", ".join(str(i) for i in ids)


def format_quest(
    qid: int,
    min_lvl,
    lvl,
    race,
    start_u,
    start_o,
    start_i,
    end_u,
    end_o,
    obj_u,
    obj_o,
    obj_i,
    pre,
) -> str:
    lines = [f"  [{qid}] = {{"]
    if end_u or end_o:
        lines.append('    ["end"] = {')
        if end_o:
            lines.append(f'      ["O"] = {{ {fmt_id_list(end_o)} }},')
        if end_u:
            lines.append(f'      ["U"] = {{ {fmt_id_list(end_u)} }},')
        lines.append("    },")
    if lvl is not None:
        lines.append(f"    [\"lvl\"] = {int(lvl)},")
    if min_lvl is not None:
        lines.append(f"    [\"min\"] = {int(min_lvl)},")
    if obj_u or obj_o or obj_i:
        lines.append('    ["obj"] = {')
        if obj_i:
            lines.append(f'      ["I"] = {{ {fmt_id_list(obj_i)} }},')
        if obj_o:
            lines.append(f'      ["O"] = {{ {fmt_id_list(obj_o)} }},')
        if obj_u:
            lines.append(f'      ["U"] = {{ {fmt_id_list(obj_u)} }},')
        lines.append("    },")
    if pre:
        lines.append(f'    ["pre"] = {{ {fmt_id_list(pre)} }},')
    if race is not None and int(race) != 0:
        lines.append(f'    ["race"] = {int(race)},')
    if start_u or start_o or start_i:
        lines.append('    ["start"] = {')
        if start_i:
            lines.append(f'      ["I"] = {{ {fmt_id_list(start_i)} }},')
        if start_o:
            lines.append(f'      ["O"] = {{ {fmt_id_list(start_o)} }},')
        if start_u:
            lines.append(f'      ["U"] = {{ {fmt_id_list(start_u)} }},')
        lines.append("    },")
    lines.append("  },")
    return "\n".join(lines)


def main() -> int:
    print("loading…", flush=True)
    src = CINDER.read_text(encoding="utf-8")
    quests = lua.eval(
        re.search(r"ns\.questData = \[\[return (\{.*?\})\]\]", src, re.S).group(1)
    )
    base_ids = top_level_ids(BASE.read_text(encoding="utf-8"))
    qpath = PFQ / "quests-turtle.lua"
    qtext = qpath.read_text(encoding="utf-8")
    turtle_ids = top_level_ids(qtext)
    print(f"base={len(base_ids)} turtle={len(turtle_ids)}", flush=True)

    inserts: dict[int, str] = {}
    names: dict[int, str] = {}
    for raw_id in quests:
        qid = int(raw_id)
        if qid in turtle_ids or qid in base_ids:
            continue
        e = quests[raw_id]
        name = str(e[1]) if e[1] else None
        if name:
            names[qid] = name
        su, so, si = started_finished(e[2])
        eu, eo, _ = started_finished(e[3])
        ou, oo, oi = objectives_items_units_objects(e[10])
        pre = lua_id_list(e[13]) if e[13] is not None else []
        # also preQuestGroup
        if e[12] is not None:
            pre = list(dict.fromkeys(pre + lua_id_list(e[12])))
        inserts[qid] = format_quest(
            qid,
            e[4],
            e[5],
            e[6],
            su,
            so,
            si,
            eu,
            eo,
            ou,
            oo,
            oi,
            pre,
        )

    print(f"quest inserts: {len(inserts)}", flush=True)
    if inserts:
        # append before final }
        m = re.search(r"(pfDB\[[^\]]+\]\[[^\]]+\]\s*=\s*\{)", qtext)
        if not m:
            raise SystemExit("no header")
        depth = 0
        i = m.end() - 1
        end = None
        while i < len(qtext):
            c = qtext[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            i += 1
        add = "\n".join(inserts[i] for i in sorted(inserts)) + "\n"
        qtext = qtext[:end] + add + qtext[end:]
        qpath.write_text(qtext, encoding="utf-8", newline="\n")

    # locales
    loc = PFQ / "enUS" / "quests-turtle.lua"
    if loc.exists() and names:
        lt = loc.read_text(encoding="utf-8")
        have = top_level_ids(lt)
        to_add = {i: n for i, n in names.items() if i not in have}
        if to_add:
            depth = 0
            m = re.search(r"(pfDB\[[^\]]+\]\[[^\]]+\]\s*=\s*\{)", lt)
            i = m.end() - 1
            end = None
            while i < len(lt):
                if lt[i] == "{":
                    depth += 1
                elif lt[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
                i += 1
            lines = []
            for iid in sorted(to_add):
                n = to_add[iid].replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'  [{iid}] = "{n}",')
            loc.write_text(lt[:end] + "\n".join(lines) + "\n" + lt[end:], encoding="utf-8", newline="\n")
            print(f"quest locales added: {len(to_add)}", flush=True)

    if ADDONS and ADDONS.is_dir():
        for name in ("quests-turtle.lua", "enUS/quests-turtle.lua"):
            src_f = PFQ / name
            if src_f.exists():
                (ADDONS / name).write_text(
                    src_f.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
                )
        print("synced quests -> AddOns", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
