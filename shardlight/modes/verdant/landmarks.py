"""Hand-authored landmark templates (JSON, kind ``verdant.template``) and the stamper that writes them
into a ``WorldMap``.  A template is an ASCII picture plus explicit building rectangles, named spots and
typed markers; the generator only decides *where* it goes (and whether it is mirrored).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import tiles as T
from .worldmap import Building, Feature, Marker, Site, WorldMap

# char -> (ground name | None=keep, object name | None=keep | "none"=clear)
_GROUND_CHARS = {
    "g": "grass", "d": "dirt", "c": "cobble", "p": "plank", "s": "sand", "w": "shallow", "v": "deep", "m": "mud",
    "k": "bog", "f": "farm", "r": "road", "_": "ruin", "l": "flag", ";": "moor", ":": "forest", "#": "cliff",
    "%": "cavewall", "&": "cryptwall", "y": "cave", "z": "crypt", "q": "woodfloor", "0": "void", "e": "carpet",
    "$": "blight", "~": "rock",
}
_OBJ_CHARS = {
    "T": "oak", "Y": "pine", "b": "bush", "L": "lamp", "o": "well", "u": "barrel", "X": "crate", "=": "fence",
    "S": "stall", "N": "notice", "H": "haystack", "*": "campfire", "^": "tent", "i": "standing", "I": "pillar",
    "Z": "statue", "R": "reeds", "B": "bed", "D": "table", "E": "shelf", "W": "bench", "F": "forge", "G": "grave",
    "O": "brazier", "J": "boat", "n": "net", "P": "pierpost", "a": "signpost", "h": "ruinwall", "t": "stones",
    "j": "flowers", "U": "cairn", "M": "mushroom", "+": "barricade", "A": "hearth", "V": "willow", "K": "dead",
    ">": "stairdown", "<": "stairup", "C": "chest", "x": "boulder", "1": "stump", "2": "log", "3": "candle",
    "4": "glowmoss", "5": "rug", "6": "cattail", "7": "berry", "8": "flax", "9": "ringtree",
}


@dataclass
class Stamp:
    site: str
    rect: tuple[int, int, int, int]
    spots: dict[str, tuple[int, int]] = field(default_factory=dict)
    markers: list[Marker] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)
    features: list[Feature] = field(default_factory=list)


def parse_legend_value(val: str) -> tuple[str | None, str | None]:
    """'ground=cobble,obj=barrel' -> ('cobble', 'barrel'); omitted parts keep the existing cell."""
    ground = obj = None
    for part in val.split(","):
        if "=" not in part:
            continue
        k, v = (s.strip() for s in part.split("=", 1))
        if k == "ground":
            ground = v
        elif k == "obj":
            obj = v
    return ground, obj


def template_problems(tpl: dict) -> list[str]:
    """Structural checks used by tests and by the generator before stamping."""
    errs = []
    rows = tpl.get("rows", [])
    if not rows:
        return ["no rows"]
    w = len(rows[0])
    for i, r in enumerate(rows):
        if len(r) != w:
            errs.append(f"row {i} has length {len(r)} (expected {w})")
    if tpl.get("w", w) != w or tpl.get("h", len(rows)) != len(rows):
        errs.append("declared w/h do not match rows")
    legend = dict(tpl.get("legend", {}))
    known = set(_GROUND_CHARS) | set(_OBJ_CHARS) | set(".,") | set(legend) | set(tpl.get("spots", {})) | set(
        tpl.get("markers", {}))
    for i, r in enumerate(rows):
        for ch in r:
            if ch not in known:
                errs.append(f"row {i}: unknown char {ch!r}")
                break
    for name, v in legend.items():
        g, o = parse_legend_value(v)
        if g is not None and g not in T.G:
            errs.append(f"legend {name!r}: unknown ground {g!r}")
        if o is not None and o not in T.O and o != "none":
            errs.append(f"legend {name!r}: unknown object {o!r}")
    for b in tpl.get("buildings", []):
        if b["x"] < 0 or b["y"] < 0 or b["x"] + b["w"] > w or b["y"] + b["h"] > len(rows):
            errs.append(f"building {b['id']} outside template")
        if not (0 <= b.get("door", b["w"] // 2) < b["w"]):
            errs.append(f"building {b['id']}: door outside footprint")
    return errs


def mirrored_rows(rows: list[str]) -> list[str]:
    return [r[::-1] for r in rows]


def stamp_template(wm: WorldMap, tpl: dict, x0: int, y0: int, site_id: str, mirror: bool = False) -> Stamp:
    """Write ``tpl`` into ``wm`` with its top-left at (x0, y0).  Returns the spots/markers/buildings created."""
    rows = list(tpl["rows"])
    w, h = len(rows[0]), len(rows)
    if mirror:
        rows = mirrored_rows(rows)
    legend = {k: parse_legend_value(v) for k, v in tpl.get("legend", {}).items()}
    spot_chars = tpl.get("spots", {})
    marker_chars = tpl.get("markers", {})
    default_ground = tpl.get("default_ground", "")
    dg = T.G.get(default_ground, -1)
    st = Stamp(site_id, (x0, y0, w, h))
    for ry, row in enumerate(rows):
        y = y0 + ry
        if not (0 <= y < wm.H):
            continue
        for rx, ch in enumerate(row):
            x = x0 + rx
            if not (0 <= x < wm.W) or ch == ".":
                continue
            g_name = o_name = None
            if ch in legend:
                g_name, o_name = legend[ch]
            elif ch in spot_chars:
                st.spots[spot_chars[ch]] = (x, y)
                o_name = "none"
                g_name = default_ground or None
            elif ch in marker_chars:
                spec = marker_chars[ch]
                st.markers.append(Marker(spec.get("kind", "spawn"), x, y, site_id, dict(spec)))
                o_name = spec.get("obj", "none")
                g_name = spec.get("ground", default_ground) or None
            elif ch == ",":
                o_name = "none"
            elif ch in _GROUND_CHARS:
                g_name, o_name = _GROUND_CHARS[ch], "none"
            elif ch in _OBJ_CHARS:
                o_name = _OBJ_CHARS[ch]
                g_name = default_ground or None
            if g_name:
                wm.ground[y, x] = T.G[g_name]
            if o_name:
                wm.obj[y, x] = 0 if o_name == "none" else T.O[o_name]
    for b in tpl.get("buildings", []):
        bx = x0 + (w - b["x"] - b["w"] if mirror else b["x"])
        by = y0 + b["y"]
        dx = b.get("door", b["w"] // 2)
        if mirror:
            dx = b["w"] - 1 - dx
        door = (bx + dx, by + b["h"] - 1)
        front = (door[0], door[1] + 1)
        wm.bmask[by:by + b["h"], bx:bx + b["w"]] = True
        wm.obj[by:by + b["h"], bx:bx + b["w"]] = 0
        bld = Building(f"{site_id}.{b['id']}", site_id, bx, by, b["w"], b["h"], b.get("style", "cottage"), door, front,
                       shop=b.get("shop", ""), enter=b.get("enter", ""), label=b.get("label", ""),
                       lit=b.get("lit", True))
        wm.buildings.append(bld)
        st.buildings.append(bld)
        st.spots[f"{b['id']}.door"] = front
    for name, (sx, sy) in list(st.spots.items()):
        wm.spots[f"{site_id}.{name}"] = (sx, sy)
    for m in st.markers:
        wm.markers.append(m)
    _make_variant_features(wm, tpl, site_id, st)
    return st


def _make_variant_features(wm: WorldMap, tpl: dict, site_id: str, st: Stamp) -> None:
    """Template ``variants``: {"state": {"default": "lean", "states": {"lean": [edits], "rich": [edits]}}}.

    An edit is {"at": "<spot name>", "obj": "banner", "ground": "cobble"}.  All variants share the cell set;
    cells a variant does not mention revert to the value found at stamp time.
    """
    for suffix, spec in tpl.get("variants", {}).items():
        states = spec.get("states", {})
        cells: list[tuple[int, int]] = []
        for edits in states.values():
            for e in edits:
                pos = st.spots.get(e["at"])
                if pos and pos not in cells:
                    cells.append(pos)
        if not cells:
            continue
        base = {c: (int(wm.ground[c[1], c[0]]), int(wm.obj[c[1], c[0]])) for c in cells}
        variants: dict[str, list[tuple[int, int]]] = {}
        for sname, edits in states.items():
            cur = dict(base)
            for e in edits:
                pos = st.spots.get(e["at"])
                if pos is None:
                    continue
                g, o = cur[pos]
                if "ground" in e:
                    g = T.G[e["ground"]]
                if "obj" in e:
                    o = 0 if e["obj"] == "none" else T.O[e["obj"]]
                cur[pos] = (g, o)
            variants[sname] = [cur[c] for c in cells]
        default = spec.get("default", next(iter(states)))
        fid = f"{site_id}.{suffix}"
        wm.features[fid] = Feature(fid, cells, variants, default, label=spec.get("label", suffix))
        wm.apply_feature(fid, default)
