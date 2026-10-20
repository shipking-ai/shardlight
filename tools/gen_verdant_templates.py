"""Compose the Hollowmere landmark templates (data/verdant.template/*.json) from a small layout DSL.

The JSON files are the shipped data (mods may replace any of them); this script is just how they were authored,
so layouts can be tweaked in code and re-emitted.  Run:  python tools/gen_verdant_templates.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "verdant.template"
MARK_CHARS = "[]{}()|?\\/<>"


class Canvas:
    def __init__(self, w: int, h: int, fill: str = "."):
        self.w, self.h = w, h
        self.g = [[fill] * w for _ in range(h)]
        self.buildings: list[dict] = []
        self.spots: dict[str, str] = {}
        self.markers: dict[str, dict] = {}
        self._mchar: dict[str, str] = {}

    def put(self, x: int, y: int, ch: str) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.g[y][x] = ch

    def get(self, x: int, y: int) -> str:
        return self.g[y][x] if 0 <= x < self.w and 0 <= y < self.h else "."

    def fill(self, x: int, y: int, w: int, h: int, ch: str) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, ch)

    def rect_outline(self, x: int, y: int, w: int, h: int, ch: str, gaps: tuple = ()) -> None:
        for xx in range(x, x + w):
            for yy in (y, y + h - 1):
                if (xx, yy) not in gaps:
                    self.put(xx, yy, ch)
        for yy in range(y, y + h):
            for xx in (x, x + w - 1):
                if (xx, yy) not in gaps:
                    self.put(xx, yy, ch)

    def disc(self, cx: float, cy: float, r: float, ch: str, only: str | None = None) -> None:
        for y in range(self.h):
            for x in range(self.w):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r and (only is None or self.g[y][x] in only):
                    self.g[y][x] = ch

    def spot(self, name: str, x: int, y: int, ch: str) -> None:
        self.spots[ch] = name
        self.put(x, y, ch)

    def marker(self, x: int, y: int, **spec) -> None:
        key = json.dumps(spec, sort_keys=True)
        if key not in self._mchar:
            self._mchar[key] = MARK_CHARS[len(self._mchar)]
            self.markers[self._mchar[key]] = spec
        self.put(x, y, self._mchar[key])

    def building(self, bid: str, x: int, y: int, w: int, h: int, style: str, label: str, door: int | None = None,
                 shop: str = "", enter: str = "", lit: bool = True) -> None:
        b = {"id": bid, "x": x, "y": y, "w": w, "h": h, "style": style, "label": label, "lit": lit}
        if door is not None:
            b["door"] = door
        if shop:
            b["shop"] = shop
        if enter:
            b["enter"] = enter
        self.buildings.append(b)
        self.fill(x, y, w, h, ",")

    def emit(self, name: str, title: str, default_ground: str = "", meta: dict | None = None, mirror: bool = True) -> dict:
        d = {"name": title, "rows": ["".join(r) for r in self.g], "w": self.w, "h": self.h,
             "default_ground": default_ground, "spots": self.spots, "markers": self.markers,
             "buildings": self.buildings, "meta": meta or {}, "mirror": mirror}
        return d


# ---------------------------------------------------------------------------------------------- towns
def town(seed: str, title: str, top: list[dict], bottom: list[dict], ground: str, street: str, theme: str,
         faction: str, east_gate: bool = True, sea: int = 0) -> dict:
    rnd = random.Random(seed)
    wt = sum(b["w"] for b in top) + 2 * (len(top) - 1)
    wb = sum(b["w"] for b in bottom) + 2 * (len(bottom) - 1)
    W = max(wt, wb, 28) + 18 + sea
    land_w = W - sea
    ht = max(b["h"] for b in top)
    hb = max(b["h"] for b in bottom)
    y_top = 3
    y1 = y_top + ht
    y2b = y1 + 4
    y2 = y2b + hb
    H = y2 + 2 + 5
    c = Canvas(W, H, ".")
    c.fill(0, 0, land_w, H, ground)
    mid = land_w // 2
    # fringe scatter
    for y in range(H):
        for x in range(land_w):
            edge = min(x, y, land_w - 1 - x, H - 1 - y)
            if edge < 3 and rnd.random() < 0.34 and not (y in (y1, y1 + 1) or (abs(x - mid) <= 1 and y > y2)):
                c.put(x, y, rnd.choice({"meadow": "TTbj", "moor": "xxY;t", "marsh": "VRR6K", "harbor": "tbT"}[theme]))
    # streets
    c.fill(0, y1, land_w, 2, street)
    c.fill(2, y2, land_w - 4, 2, street)
    c.fill(mid - 1, y1, 3, y2 + 2 - y1 + 5, street)
    plaza = (mid - 3, y1 + 1, 7, 5)
    c.fill(*plaza, street)
    c.put(mid, y1 + 3, "o")
    c.put(mid - 2, y1 + 2, "N")
    c.put(mid + 2, y1 + 4, "u")
    # buildings
    def lay(row: list[dict], by_bottom: int, front_street_y: int, total: int):
        x = 3
        for b in row:
            by = by_bottom - b["h"]
            if x <= mid + 1 and x + b["w"] > mid - 2:       # keep the central link clear: shift past it
                x = mid + 3
            if x + b["w"] > land_w - 2:
                raise ValueError(f"{title}: row too wide")
            c.building(b["id"], x, by, b["w"], b["h"], b["style"], b["label"], b.get("door"), b.get("shop", ""),
                       b.get("enter", ""), b.get("lit", True))
            dxs = b.get("door", b["w"] // 2)
            for yy in range(by_bottom, front_street_y):
                c.put(x + dxs, yy, "d" if street == "c" else street)
            for xx in range(x - 1, x + b["w"] + 1):                        # yard / garden
                for yy in range(by - 1, by):
                    if c.get(xx, yy) == ground and rnd.random() < 0.3:
                        c.put(xx, yy, "b" if theme != "moor" else "x")
            x += b["w"] + 2
    lay(top, y1, y1, wt + 0)
    lay(bottom, y2, y2, wb + 0)
    # lamps along the second row of each street
    for sy in (y1 + 1, y2 + 1):
        for x in range(4, land_w - 3, 8):
            if abs(x - mid) > 3 and c.get(x, sy) == street:
                c.put(x, sy, "L")
    c.put(mid - 2, y2 + 1 + 3, "L")
    c.put(mid + 2, y2 + 1 + 3, "L")
    # gates and spots
    c.spot("front", mid, y1 + 1, "@")
    c.spot("gate_w", 0, y1, "1")
    c.spot("gate_s", mid, H - 1, "3")
    c.spot("arrival", mid, H - 3, "!")
    if east_gate:
        c.spot("gate_e", land_w - 1, y1, "2")
    for i in range(3):          # a mid-street barrel / crate or two for dressing
        x = rnd.randrange(5, land_w - 5)
        if c.get(x, y1 + 1) == street and abs(x - mid) > 3:
            c.put(x, y1 + 1, rnd.choice("uX"))
    return c, W, H


def harbor_sea(c: Canvas, W: int, H: int, sea: int, y1: int) -> None:
    land_w = W - sea
    for y in range(H):
        for x in range(land_w, W):
            depth = x - land_w
            wob = (y * 7 + x * 3) % 3
            c.put(x, y, "w" if depth < 2 + wob % 2 else "v")
    for x in range(land_w - 2, W - 2):          # pier
        for yy in (y1, y1 + 1):
            c.put(x, yy, "p")
    for x in range(land_w, W - 2, 2):
        c.put(x, y1 - 1, "P")
        c.put(x, y1 + 2, "P")
    c.put(land_w + 3, y1 - 2, "J")
    c.put(land_w + 4, y1 + 4, "J")
    c.put(land_w - 3, y1 + 3, "n")
    c.put(land_w - 4, y1 - 1, "u")


def mk(bid, w, h, style, label, **kw):
    return dict(id=bid, w=w, h=h, style=style, label=label, **kw)


def wickering():
    top = [mk("inn", 10, 6, "inn", "The Kettle & Wick", enter="inn"),
           mk("store", 7, 5, "shop", "Pell & Daughter, General Goods", shop="general", enter="store"),
           mk("lamp_house", 6, 5, "lamp_house", "Marrow's Lamp House", enter="lamp_house", lit=False)]
    bottom = [mk("cottage_a", 6, 5, "cottage", "Cottage", enter="cottage"),
              mk("healer", 6, 5, "cottage", "The Poultice Door", enter="healer", shop="healer"),
              mk("smithy", 7, 5, "smithy", "Ansel's Smithy", enter="smithy", shop="smith"),
              mk("cottage_b", 6, 5, "cottage", "Cottage", enter="cottage")]
    c, W, H = town("wickering", "Wickering", top, bottom, "g", "c", "meadow", "wickering")
    return c.emit("wickering", "Wickering", "grass", {"faction": "wickering", "interior": ""})


def tidewick():
    top = [mk("harbormaster", 8, 5, "hall", "Harbourmaster's Office", enter="harbormaster"),
           mk("chandler", 7, 5, "shop", "Gull & Rope Chandlery", shop="chandler", enter="store"),
           mk("tavern", 9, 6, "inn", "The Drowned Rat", enter="tavern")]
    bottom = [mk("carpenter", 8, 5, "smithy", "Brisk the Carpenter", enter="carpenter", shop="carpenter"),
              mk("cottage_a", 6, 5, "cottage", "Net-Mender's Cottage", enter="cottage"),
              mk("cottage_b", 6, 5, "cottage", "Cottage", enter="cottage")]
    sea = 9
    c, W, H = town("tidewick", "Tidewick", top, bottom, "s", "c", "harbor", "tidewick", east_gate=False, sea=sea)
    y1 = 3 + max(b["h"] for b in top)
    harbor_sea(c, W, H, sea, y1)
    return c.emit("tidewick", "Tidewick", "sand", {"faction": "tidewick"})


def harrow():
    top = [mk("forge_hall", 8, 6, "smithy", "The Harrow Forge", enter="forge", shop="smith2"),
           mk("moot", 9, 6, "hall", "Moot House", enter="moot"),
           mk("cottage_a", 6, 5, "longhouse", "Cairnkeeper's House", enter="cairnkeeper")]
    bottom = [mk("cottage_b", 6, 5, "longhouse", "Longhouse", enter="cottage"),
              mk("alehouse", 8, 5, "inn", "The Heather Cup", enter="alehouse"),
              mk("cottage_c", 6, 5, "longhouse", "Longhouse", enter="cottage")]
    c, W, H = town("harrow", "Harrow Cairn", top, bottom, ";", "c", "moor", "harrow")
    return c.emit("harrow_cairn", "Harrow Cairn", "moor", {"faction": "harrow"})


def reedholm():
    top = [mk("healer", 7, 5, "hut", "Sister Ilse's Hospice", enter="hospice", shop="healer2"),
           mk("trader", 7, 5, "shop", "Reed & Cattail Trading", enter="store", shop="marsh"),
           mk("stilts_a", 6, 5, "hut", "Stilt House", enter="cottage")]
    bottom = [mk("stilts_b", 6, 5, "hut", "Stilt House", enter="cottage"),
              mk("oilpress", 8, 5, "smithy", "Lamp-Oil Press", enter="oilpress", shop="oil"),
              mk("stilts_c", 6, 5, "hut", "Stilt House", enter="cottage")]
    c, W, H = town("reedholm", "Reedholm", top, bottom, "m", "p", "marsh", "reedholm")
    return c.emit("reedholm", "Reedholm", "mud", {"faction": "reedholm"})


# ---------------------------------------------------------------------------------------------- sites
def hollow_hall():
    c = Canvas(34, 28)
    c.fill(2, 2, 30, 24, "g")
    c.fill(4, 4, 26, 18, "_")                      # courtyard flags
    c.rect_outline(3, 3, 28, 20, "h", gaps=((16, 22), (17, 22), (10, 22), (9, 3)))
    for x in (7, 12, 21, 26):
        c.put(x, 8, "I"); c.put(x, 14, "I")
    c.building("hall", 10, 5, 14, 7, "ruined_hall", "Hollow Hall", door=7, enter="hollow_hall", lit=False)
    for x in range(14, 21):                         # path from hall door to the south gap
        pass
    c.fill(16, 13, 2, 10, "l")
    c.put(14, 15, "Z"); c.put(19, 15, "Z")
    c.put(8, 17, "G"); c.put(9, 19, "G"); c.put(25, 17, "G"); c.put(27, 19, "G"); c.put(24, 15, "O"); c.put(9, 14, "O")
    c.put(6, 20, "t"); c.put(28, 21, "t"); c.put(12, 20, "x")
    c.marker(26, 8, kind="chest", loot="ruin_chest", id="hall_chest_a", obj="chest")
    c.marker(6, 8, kind="chest", loot="ruin_chest", id="hall_chest_b", obj="chest")
    c.marker(21, 19, kind="spawn", enemy="shade", count=2, radius=4)
    c.marker(11, 18, kind="spawn", enemy="shade", count=1, radius=3)
    c.spot("front", 16, 24, "@")
    c.put(17, 24, "l")
    return c.emit("hollow_hall", "Hollow Hall", "", {"interior": "hollow_hall"})


def farmstead():
    c = Canvas(26, 20)
    c.fill(1, 1, 24, 18, "g")
    c.fill(2, 8, 14, 9, "f")
    for y in (9, 11, 13, 15):
        for x in range(3, 15, 2):
            c.put(x, y, "8")
    c.rect_outline(1, 7, 16, 11, "=", gaps=((8, 17), (9, 17), (16, 12)))
    c.building("farmhouse", 17, 8, 7, 5, "farmhouse", "Tamsin's Farmhouse", enter="farmhouse")
    c.fill(19, 13, 2, 5, "d")
    c.fill(16, 12, 4, 1, "d")
    c.fill(8, 17, 2, 2, "d")
    c.put(21, 3, "H"); c.put(22, 3, "H"); c.put(23, 5, "H"); c.put(4, 3, "T"); c.put(7, 2, "T"); c.put(12, 3, "b")
    c.put(18, 15, "o"); c.put(22, 15, "u"); c.put(23, 16, "X")
    c.marker(5, 5, kind="chest", loot="farm_chest", id="farm_chest", obj="chest")
    c.marker(11, 3, kind="npc", npc="tamsin_pasture", obj="")
    c.spot("front", 20, 17, "@")
    return c.emit("farmstead", "Tamsin's Farm", "", {"interior": "farmhouse"})


def cairn_of_debts():
    c = Canvas(24, 20)
    c.fill(1, 1, 22, 18, ";")
    c.disc(12, 9, 8.5, "~", only=";")
    c.rect_outline(5, 3, 14, 12, "h", gaps=((11, 14), (12, 14), (11, 3)))
    for (x, y) in ((7, 5), (16, 5), (7, 12), (16, 12)):
        c.put(x, y, "U")
    for (x, y) in ((9, 8), (14, 8), (10, 11), (13, 5)):
        c.put(x, y, "G")
    c.put(3, 4, "x"); c.put(20, 15, "x"); c.put(21, 5, "i"); c.put(2, 14, "i")
    c.marker(12, 6, kind="entrance", area="cairn_of_debts", obj="stairdown")
    c.marker(18, 11, kind="chest", loot="ruin_chest", id="cairn_chest", obj="chest")
    c.marker(10, 16, kind="spawn", enemy="shade", count=2, radius=4)
    c.fill(11, 14, 2, 5, "d")
    c.spot("front", 12, 18, "@")
    return c.emit("cairn_of_debts", "Cairn of Debts", "", {"interior": "cairn_of_debts"})


def drowned_chapel():
    c = Canvas(28, 22)
    c.fill(1, 1, 26, 20, "m")
    c.disc(14, 9, 10, "w", only="m")
    c.disc(14, 9, 6, "v", only="w")
    c.disc(14, 9, 4, "m")
    c.rect_outline(10, 5, 9, 8, "h", gaps=((14, 12), (15, 5)))
    c.fill(13, 13, 3, 8, "p")
    c.put(12, 7, "G"); c.put(17, 7, "G"); c.put(11, 10, "I"); c.put(17, 10, "I"); c.put(5, 4, "V"); c.put(22, 15, "V")
    for (x, y) in ((4, 16), (22, 5), (6, 8), (23, 12), (3, 12)):
        c.put(x, y, "R")
    c.marker(14, 7, kind="entrance", area="drowned_chapel", obj="stairdown")
    c.marker(13, 11, kind="chest", loot="ruin_chest", id="chapel_chest", obj="chest")
    c.marker(7, 15, kind="spawn", enemy="drowned", count=2, radius=4)
    c.marker(20, 17, kind="spawn", enemy="bogwight", count=1, radius=3)
    c.spot("front", 14, 20, "@")
    return c.emit("drowned_chapel", "The Drowned Chapel", "", {"interior": "drowned_chapel"})


def sedge_hut():
    c = Canvas(16, 14)
    c.fill(1, 1, 14, 12, "m")
    c.disc(11, 4, 3.4, "w", only="m")
    c.building("hut", 3, 4, 6, 4, "hut", "Sedge Hut", enter="sedge_hut")
    c.fill(5, 8, 2, 4, "p")
    for (x, y) in ((2, 10), (10, 9), (13, 6), (2, 2), (9, 11)):
        c.put(x, y, "R")
    c.put(11, 7, "J"); c.put(9, 8, "n"); c.put(12, 11, "6"); c.put(4, 2, "V")
    c.marker(10, 12, kind="npc", npc="sedge_hermit", obj="")
    c.spot("front", 5, 11, "@")
    return c.emit("sedge_hut", "Sedge Hut", "", {"interior": "sedge_hut"})


def listening_stones():
    c = Canvas(22, 22)
    c.fill(1, 1, 20, 20, ";")
    c.disc(11, 11, 7.6, "l", only=";")
    cx = cy = 11
    import math
    for k in range(12):
        a = k / 12 * math.tau
        x, y = round(cx + 6 * math.cos(a)), round(cy + 6 * math.sin(a))
        if (x, y) not in ((11, 17), (10, 17), (12, 17)):
            c.put(x, y, "i")
    c.marker(11, 11, kind="entrance", area="listening_stones", obj="stairdown", hidden=True)
    for (x, y) in ((4, 4), (18, 4), (4, 18), (18, 17)):
        c.put(x, y, "x")
    c.fill(11, 17, 1, 4, "d")
    c.spot("front", 11, 19, "@")
    return c.emit("listening_stones", "The Listening Stones", "", {"interior": "listening_stones"})


def bandit_camp():
    c = Canvas(26, 20)
    c.fill(1, 1, 24, 18, "g")
    c.disc(13, 10, 9, "d", only="g")
    c.rect_outline(4, 3, 18, 14, "+", gaps=((12, 16), (13, 16)))
    for (x, y) in ((7, 5), (16, 5), (6, 11), (18, 11)):
        c.put(x, y, "^"); c.put(x + 1, y, "^")
    c.put(12, 10, "*"); c.put(10, 11, "W"); c.put(15, 9, "W")
    c.put(8, 14, "X"); c.put(9, 14, "u"); c.put(19, 14, "X"); c.put(20, 8, "u"); c.put(5, 8, "H")
    c.marker(20, 5, kind="chest", loot="camp_chest", id="camp_chest", obj="chest")
    c.marker(12, 6, kind="spawn", enemy="rook_captain", count=1, radius=2, unique=True)
    c.marker(9, 9, kind="spawn", enemy="bandit", count=3, radius=4)
    c.marker(17, 13, kind="spawn", enemy="bandit_archer", count=2, radius=4)
    c.fill(12, 16, 2, 3, "d")
    c.spot("front", 12, 18, "@")
    return c.emit("bandit_camp", "Rook's Camp", "", {"faction": "rooks"})


def roots_entrance():
    c = Canvas(18, 16)
    c.fill(1, 1, 16, 14, ":")
    c.disc(9, 7, 5, "y", only=":")
    c.disc(9, 7, 2.2, "y")
    for (x, y) in ((3, 3), (14, 3), (4, 11), (14, 11), (2, 7), (16, 8)):
        c.put(x, y, "K")
    for (x, y) in ((6, 4), (12, 4), (7, 11), (11, 10)):
        c.put(x, y, "4")
    c.marker(9, 6, kind="entrance", area="hollow_roots", obj="stairdown")
    c.marker(13, 7, kind="spawn", enemy="crawler", count=2, radius=3)
    c.fill(9, 10, 1, 5, "d")
    c.spot("front", 9, 13, "@")
    return c.emit("roots_entrance", "The Hollow Roots", "", {"interior": "hollow_roots"})


def wolf_den():
    c = Canvas(16, 13)
    c.fill(1, 1, 14, 11, ":")
    c.disc(8, 6, 4.5, "~", only=":")
    for (x, y) in ((4, 3), (12, 3), (3, 8), (13, 9), (8, 2)):
        c.put(x, y, "x")
    c.put(7, 6, "t"); c.put(9, 7, "t"); c.put(6, 8, "t")
    c.marker(8, 6, kind="spawn", enemy="wolf", count=3, radius=4)
    c.marker(10, 4, kind="chest", loot="den_cache", id="den_chest", obj="chest")
    c.spot("front", 8, 11, "@")
    return c.emit("wolf_den", "Wolf Den", "", {})


def wayshrine():
    c = Canvas(11, 11)
    c.fill(1, 1, 9, 9, "g")
    c.disc(5, 5, 3.6, "c")
    c.put(5, 4, "Z"); c.put(3, 3, "L"); c.put(7, 3, "L"); c.put(3, 7, "j"); c.put(7, 7, "j"); c.put(5, 7, "W")
    c.marker(5, 5, kind="shrine", obj="")
    c.fill(5, 8, 1, 3, "d")
    c.spot("front", 5, 8, "@")
    return c.emit("wayshrine", "Wayshrine", "", {})


BUILDERS = {"wickering": wickering, "tidewick": tidewick, "harrow_cairn": harrow, "reedholm": reedholm,
            "hollow_hall": hollow_hall, "farmstead": farmstead, "cairn_of_debts": cairn_of_debts,
            "drowned_chapel": drowned_chapel, "sedge_hut": sedge_hut, "listening_stones": listening_stones,
            "bandit_camp": bandit_camp, "roots_entrance": roots_entrance, "wolf_den": wolf_den, "wayshrine": wayshrine}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for tid, fn in BUILDERS.items():
        d = fn()
        d = {"id": tid, **d}
        entries.append(d)
    (OUT / "verdant_templates.json").write_text(json.dumps({"entries": entries}, indent=0), encoding="utf-8")
    print(f"wrote {len(entries)} templates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
