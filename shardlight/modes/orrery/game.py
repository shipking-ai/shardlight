"""Orrery game rules on top of the galaxy and the civ simulation: the player's ship, travel, trade, missions,
signals and the Last Lamp trial.  Pure logic (no pygame); the scene and the flight simulation call into it.

Time model: one in-game day = ``DAY_SECONDS`` of flight time.  ``advance_clock`` moves the shared clock and advances
the civ simulation (fine detail around the player, batched elsewhere).  ``clock`` is also the time used for
analytic planetary orbits, so the sky is identical whether or not the player watched it.
"""
from __future__ import annotations

import math
from typing import Callable

from ...core.rng import Rng, derive_seed
from . import signals as sigmod
from .civsim import DAY_SECONDS, GalaxySim
from .defs import Defs
from .galaxy import Galaxy, body_state, features_from_unlocks, generate

START_CREDITS = 2400
FUEL_PRICE = 14.0
REPAIR_PRICE = 3.5
MAX_MISSIONS = 6
LAMP_ORDER_NEEDED = 5


class Game:
    VERSION = 1

    def __init__(self, defs: Defs, galaxy: Galaxy, sim: GalaxySim, seed: int):
        self.defs = defs
        self.g = galaxy
        self.sim = sim
        self.seed = seed
        self.rng = Rng(derive_seed(seed, "game"))
        self.hull = "wayfarer"
        self.mods: list[str] = []
        self.credits = float(START_CREDITS)
        stats = self.ship_stats()
        self.fuel = stats["fuel"]
        self.hull_hp = stats["hull"]
        self.cargo: dict[str, int] = {}
        self.sid = galaxy.start
        self.clock = float(sim.day * DAY_SECONDS)
        self.visited: set[int] = {galaxy.start}
        self.revealed: set[tuple[int, int]] = set()
        self.codex: dict[str, dict] = {}
        self.blueprints: set[str] = set()
        self.contacts: set[str] = set()
        self.signals: dict[str, dict] = {}
        self.missions: list[dict] = []
        self.flags: dict = {}
        self.stats = {"jumps": 0, "kills": 0, "trades": 0, "profit": 0.0, "decoded": 0, "days": 0, "lost_ships": 0}
        self.lamp = {"lit": [False] * LAMP_ORDER_NEEDED, "done": False, "resets": 0}
        self.log: list[str] = []
        self.emit: Callable[..., object] = lambda name, **kw: None
        self.add_lore: Callable[[str], object] = lambda lid: None
        self.cleared: dict[int, int] = {}           # sid -> day pirates were last cleared
        self.looted: set[str] = set()               # body ids already looted/scanned
        self.mission_seq = 1
        self.reveal_start()

    # ================================================================================ construction
    @classmethod
    def new(cls, defs: Defs, seed: int, features: tuple[str, ...] = ()) -> "Game":
        gal = generate(seed, features, defs)
        sim = GalaxySim.new(gal, defs)
        g = cls(defs, gal, sim, seed)
        g.features = features
        return g

    features: tuple[str, ...] = ()

    def reveal_start(self) -> None:
        for n in self.g.neighbors(self.sid):
            self.visited.add(n) if False else None

    # ================================================================================ persistence
    def to_dict(self) -> dict:
        self.sim.flush_pending()
        return {"v": self.VERSION, "seed": self.seed, "features": list(self.features), "hull": self.hull,
                "mods": list(self.mods), "credits": self.credits, "fuel": self.fuel, "hp": self.hull_hp,
                "cargo": dict(self.cargo), "sid": self.sid, "clock": self.clock, "visited": sorted(self.visited),
                "revealed": [list(k) for k in sorted(self.revealed)], "codex": self.codex,
                "blueprints": sorted(self.blueprints), "contacts": sorted(self.contacts), "signals": self.signals,
                "missions": self.missions, "flags": self.flags, "stats": self.stats, "lamp": self.lamp,
                "cleared": {str(k): v for k, v in self.cleared.items()}, "looted": sorted(self.looted),
                "mission_seq": self.mission_seq, "sim": self.sim.to_dict(), "log": self.log[-20:]}

    @classmethod
    def from_dict(cls, defs: Defs, d: dict, has_unlock=lambda u: False) -> "Game | None":
        try:
            if d.get("v") != cls.VERSION:
                return None
            feats = tuple(sorted(set(d["features"]) | set(features_from_unlocks(defs, has_unlock))))
            gal = generate(d["seed"], feats, defs)
            sim = GalaxySim.from_dict(gal, defs, d["sim"])
            g = cls(defs, gal, sim, d["seed"])
            g.features = feats
            g.hull, g.mods = d["hull"], list(d["mods"])
            g.credits, g.fuel, g.hull_hp = d["credits"], d["fuel"], d["hp"]
            g.cargo = dict(d["cargo"])
            g.sid, g.clock = d["sid"], d["clock"]
            g.visited = set(d["visited"])
            g.revealed = {tuple(k) for k in d["revealed"]}
            g.codex, g.blueprints, g.contacts = d["codex"], set(d["blueprints"]), set(d["contacts"])
            g.signals, g.missions, g.flags = d["signals"], d["missions"], d["flags"]
            g.stats, g.lamp = d["stats"], d["lamp"]
            g.cleared = {int(k): v for k, v in d["cleared"].items()}
            g.looted = set(d["looted"])
            g.mission_seq = d["mission_seq"]
            g.log = list(d.get("log", []))
            if g.hull not in defs.hulls:
                g.hull = "wayfarer"
            g.mods = [m for m in g.mods if m in defs.modules]
            return g
        except (KeyError, TypeError, ValueError):
            return None

    # ================================================================================ ship
    def ship_stats(self) -> dict[str, float]:
        s = self.defs.hull_stats(self.hull)
        for m in self.mods:
            mod = self.defs.modules.get(m)
            if not mod:
                continue
            for k, v in mod.get("add", {}).items():
                s[k] = s.get(k, 0.0) + v
            for k, v in mod.get("mul", {}).items():
                s[k] = s.get(k, 0.0) * v
        s["mass"] = max(4.0, s["mass"])
        return s

    def power_used(self) -> float:
        return sum(self.defs.modules[m].get("power", 0) for m in self.mods if m in self.defs.modules)

    def can_install(self, mod_id: str) -> tuple[bool, str]:
        mod = self.defs.modules.get(mod_id)
        if mod is None:
            return False, "Unknown module."
        st = self.defs.hull_stats(self.hull)
        if len(self.mods) >= st["slots"]:
            return False, "No free slot."
        if self.power_used() + mod.get("power", 0) > st["power"]:
            return False, "Not enough reactor power."
        if mod_id in self.mods and mod_id in ("missile_rack", "beam_lens", "sensor_array", "hyper_coil", "lock_computer"):
            return False, "Already installed."
        if mod.get("blueprint") and mod_id not in self.blueprints:
            return False, "You do not hold this blueprint."
        return True, "OK"

    def module_available_at(self, sid: int, mod_id: str) -> bool:
        mod = self.defs.modules[mod_id]
        if mod.get("basic"):
            return True
        tech = mod.get("tech")
        if tech:
            owner = self.sim.owner(sid)
            return bool(owner and tech in self.sim.civs[owner].techs) or any(
                tech in st.techs for st in self.sim.civs.values() if self.sim.player_rep.get(st.id, 0) >= 40)
        return mod_id in self.blueprints

    def install(self, mod_id: str) -> bool:
        ok, _ = self.can_install(mod_id)
        price = self.defs.modules[mod_id].get("price", 0)
        if not ok or self.credits < price or not self.module_available_at(self.sid, mod_id):
            return False
        self.credits -= price
        self.mods.append(mod_id)
        self._clamp_to_stats()
        return True

    def remove(self, mod_id: str) -> bool:
        if mod_id not in self.mods:
            return False
        self.mods.remove(mod_id)
        self.credits += self.defs.modules[mod_id].get("price", 0) * 0.5
        self._clamp_to_stats()
        return True

    def hull_available(self, hull_id: str) -> bool:
        h = self.defs.hulls[hull_id]
        need = h.get("unlock")
        return not need or need in self.flags.get("unlocks", []) or hull_id in self.flags.get("hulls", [])

    def buy_hull(self, hull_id: str) -> bool:
        h = self.defs.hulls[hull_id]
        if hull_id == self.hull or not self.hull_available(hull_id):
            return False
        trade_in = self.defs.hulls[self.hull].get("price", 0) * 0.5
        price = h.get("price", 0)
        if self.credits + trade_in < price:
            return False
        self.credits += trade_in - price
        self.hull = hull_id
        self.mods = []
        self._clamp_to_stats()
        self.hull_hp = self.ship_stats()["hull"]
        return True

    def _clamp_to_stats(self) -> None:
        s = self.ship_stats()
        self.fuel = min(self.fuel, s["fuel"])
        self.hull_hp = min(self.hull_hp, s["hull"])
        over = self.cargo_used() - int(s["cargo"])
        if over > 0:                                   # jettison what no longer fits
            for g in sorted(self.cargo):
                take = min(over, self.cargo[g])
                self.cargo[g] -= take
                over -= take
                if self.cargo[g] <= 0:
                    del self.cargo[g]
                if over <= 0:
                    break

    def cargo_used(self) -> int:
        return sum(self.cargo.values())

    def cargo_free(self) -> int:
        return int(self.ship_stats()["cargo"]) - self.cargo_used()

    # ================================================================================ time
    def day(self) -> int:
        return self.sim.day

    def advance_clock(self, seconds: float) -> int:
        """Move time forward; returns the number of whole days that passed (the civ sim advanced by that many)."""
        before = int(self.clock // DAY_SECONDS)
        self.clock += seconds
        after = int(self.clock // DAY_SECONDS)
        n = after - before
        if n > 0:
            self.sim.advance(n, center=self.sid)
            self.stats["days"] += n
            self.on_new_day(n)
        return max(0, n)

    def advance_days(self, days: int) -> None:
        self.advance_clock(days * DAY_SECONDS - (self.clock % DAY_SECONDS) + 0.01 if days else 0)

    def on_new_day(self, n: int) -> None:
        now = self.sim.day
        for m in self.missions:
            if not m.get("done") and m.get("deadline", 10 ** 9) < now:
                m["failed"] = True
        self.missions = [m for m in self.missions if not m.get("failed") or m.get("keep")]

    # ================================================================================ travel
    def known_lanes(self, sid: int | None = None) -> list[int]:
        sid = self.sid if sid is None else sid
        return self.g.neighbors(sid, self.revealed)

    def can_jump(self, dest: int) -> tuple[bool, str]:
        if dest == self.sid:
            return False, "You are already here."
        ln = self.g.lane(self.sid, dest)
        if ln is None or (ln.kind == "hidden" and ln.key not in self.revealed):
            return False, "No known lane."
        st = self.ship_stats()
        if ln.length > st["range"]:
            return False, f"Out of drive range ({ln.length:.0f} > {st['range']:.0f})."
        if self.fuel + 1e-9 < ln.fuel:
            return False, f"Not enough fuel ({ln.fuel:.1f} needed)."
        return True, "OK"

    def jump(self, dest: int) -> dict | None:
        ok, _ = self.can_jump(dest)
        if not ok:
            return None
        ln = self.g.lane(self.sid, dest)
        self.fuel -= ln.fuel
        days = max(1, int(round(self.sim._lane_days(self.sid, dest))))
        origin = self.sid
        self.sid = dest
        self.visited.add(dest)
        self.stats["jumps"] += 1
        self.advance_clock(days * DAY_SECONDS - (self.clock % DAY_SECONDS) + 0.01)
        self.on_arrive(dest)
        return {"from": origin, "to": dest, "days": days, "fuel": ln.fuel}

    def on_arrive(self, sid: int) -> None:
        s = self.g.systems[sid]
        self.codex_add(f"sys:{sid}", "system", s.name, f"{s.star.label}, {len(s.bodies)} bodies.")
        if sid == self.g.last_lamp:
            self.codex_add("lamp", "place", "The Last Lamp", "A guttering star ringed by five unlit gears.")
            self.add_lore("orrery_last_lamp")

    # ================================================================================ trade / services
    def market(self, sid: int | None = None):
        return self.sim.markets.get(self.sid if sid is None else sid)

    def can_trade(self) -> bool:
        return self.market() is not None and self.sim.will_trade(self.sid)

    def buy(self, good: str, qty: int) -> tuple[int, float]:
        if not self.can_trade():
            return 0, 0.0
        qty = min(qty, self.cargo_free())
        unit = self.sim.unit_price(self.sid, good, "buy", max(1, qty))
        qty = min(qty, int(self.credits // max(unit, 1.0)))
        if qty <= 0:
            return 0, 0.0
        got, cost = self.sim.buy(self.sid, good, qty)
        if got <= 0:
            return 0, 0.0
        self.credits -= cost
        self.cargo[good] = self.cargo.get(good, 0) + got
        self.flags.setdefault("paid", {})[good] = self.flags.get("paid", {}).get(good, 0.0) + cost
        self.stats["trades"] += 1
        return got, cost

    def sell(self, good: str, qty: int) -> float:
        have = self.cargo.get(good, 0)
        qty = min(qty, have)
        if qty <= 0 or not self.can_trade():
            return 0.0
        pay = self.sim.sell(self.sid, good, qty)
        self.credits += pay
        self.cargo[good] = have - qty
        if self.cargo[good] <= 0:
            del self.cargo[good]
        paid = self.flags.get("paid", {})
        if good in paid and have > 0:
            avg = paid[good] / have
            paid[good] = max(0.0, paid[good] - avg * qty)
            self.stats["profit"] += pay - avg * qty
        self.stats["trades"] += 1
        return pay

    def refuel(self, amount: float | None = None) -> float:
        st = self.ship_stats()
        m = self.market()
        if m is None:
            return 0.0
        need = st["fuel"] - self.fuel if amount is None else min(amount, st["fuel"] - self.fuel)
        price = FUEL_PRICE * self.sim.rep_price_mod(m.owner, True)
        n = min(need, self.credits / price)
        if n <= 0:
            return 0.0
        self.fuel += n
        self.credits -= n * price
        return n

    def repair(self) -> float:
        st = self.ship_stats()
        m = self.market()
        if m is None:
            return 0.0
        need = st["hull"] - self.hull_hp
        price = REPAIR_PRICE * self.sim.rep_price_mod(m.owner, True)
        n = min(need, self.credits / price)
        if n <= 0:
            return 0.0
        self.hull_hp += n
        self.credits -= n * price
        return n

    # ================================================================================ codex / lore
    def codex_add(self, cid: str, kind: str, name: str, text: str) -> bool:
        if cid in self.codex:
            return False
        self.codex[cid] = {"kind": kind, "name": name, "text": text, "day": self.sim.day}
        return True

    # ================================================================================ discoveries
    def interact_body(self, body, rng: Rng | None = None) -> list[str]:
        """Scan/loot an anomaly or derelict.  Returns message lines."""
        rng = rng or Rng(derive_seed(self.seed, "loot", body.id))
        if body.id in self.looted:
            return ["Nothing more to find here."]
        msgs: list[str] = []
        k = body.sub
        if body.kind == "anomaly" and k != "emitter":
            self.looted.add(body.id)
            self.codex_add(f"anom:{body.id}", "anomaly", body.name, self._anomaly_text(k))
            if k == "lensing_fold":
                hidden = [ln for ln in self.g.lanes.values() if ln.kind == "hidden" and ln.reveal.startswith("anomaly:")
                          and ln.reveal == f"anomaly:{body.id}"] or [ln for ln in self.g.lanes.values()
                                                                  if ln.kind == "hidden" and ln.key not in self.revealed
                                                                  and self.sid in (ln.a, ln.b)]
                for ln in hidden[:1]:
                    self.revealed.add(ln.key)
                    msgs.append(f"The fold shows a lane to {self.g.systems[ln.b if ln.a == self.sid else ln.a].name}.")
                if not hidden:
                    msgs.append("The fold bends light but shows nothing new.")
            elif k == "ancient_beacon":
                for n in self.g.neighbors(self.sid, self.revealed):
                    self.visited.add(n)
                msgs.append("The beacon charts the neighbouring systems for you.")
                self.add_lore("orrery_beacon_old")
            elif k == "crystal_bloom":
                n = min(self.cargo_free(), rng.randint(4, 9))
                if n > 0:
                    self.cargo["crystal"] = self.cargo.get("crystal", 0) + n
                    msgs.append(f"You harvest {n} Prism Crystal.")
                else:
                    self.looted.discard(body.id)
                    msgs.append("Your hold is full.")
            elif k == "orrery_fragment":
                bp = self._pick_blueprint(rng)
                if bp:
                    self.blueprints.add(bp)
                    msgs.append(f"Blueprint recovered: {self.defs.modules[bp]['name']}.")
                else:
                    self.credits += 600
                    msgs.append("The fragment's metal sells for 600.")
            return msgs
        if body.kind == "derelict":
            self.looted.add(body.id)
            self.codex_add(f"der:{body.id}", "derelict", body.name, "A silent wreck, picked clean by you.")
            if k == "wreck_cargo":
                gid = rng.pick(sorted(self.defs.goods))
                n = min(self.cargo_free(), rng.randint(5, 12))
                if n > 0:
                    self.cargo[gid] = self.cargo.get(gid, 0) + n
                    msgs.append(f"Salvaged {n} {self.defs.goods[gid]['name']}.")
                self.credits += rng.randint(100, 300)
            elif k == "blueprint_cache":
                bp = self._pick_blueprint(rng)
                if bp:
                    self.blueprints.add(bp)
                    msgs.append(f"Blueprint recovered: {self.defs.modules[bp]['name']}.")
                else:
                    self.credits += 800
            elif k == "logbook":
                for ln in self.g.lanes.values():
                    if ln.kind == "hidden" and ln.key not in self.revealed and ln.reveal.startswith("fold:"):
                        self.revealed.add(ln.key)
                        msgs.append("The logbook records a shortcut lane.")
                        break
                else:
                    msgs.append("The logbook is a poem about debt.")
                    self.add_lore("orrery_logbook")
            elif k == "fuel_hulk":
                st = self.ship_stats()
                add = min(st["fuel"] - self.fuel, rng.uniform(5, 9))
                self.fuel += add
                msgs.append(f"Siphoned {add:.1f} fuel.")
            return msgs or ["The wreck is empty."]
        return ["There is nothing to scan."]

    @staticmethod
    def _anomaly_text(k: str) -> str:
        return {"lensing_fold": "Space folds over itself here; light takes a shortcut.",
                "ancient_beacon": "A beacon older than the lanes, still charting.",
                "crystal_bloom": "Crystals grown in vacuum, humming to themselves.",
                "orrery_fragment": "A gear of the old Orrery, drifting."}.get(k, "An anomaly.")

    def _pick_blueprint(self, rng: Rng) -> str | None:
        pool = [m for m, d in sorted(self.defs.modules.items()) if d.get("blueprint") and m not in self.blueprints]
        return rng.pick(pool) if pool else None

    # ================================================================================ signals
    def enabled_signals(self) -> list[str]:
        return [s for s in self.defs.signals if s in self.g.signal_sources]

    def sig_state(self, sig: str) -> dict:
        return self.signals.setdefault(sig, {"readings": [], "decoded": False, "attempts": [], "hints": 0, "found": False})

    def positions(self) -> list[tuple[float, float]]:
        return [(s.x, s.y) for s in self.g.systems]

    def listen(self) -> list[tuple[str, dict | None]]:
        """Point the dish: a reading for every enabled signal in range of here (costs one day)."""
        st = self.ship_stats()
        out = []
        pos = self.positions()
        for sig in self.enabled_signals():
            d = self.defs.signals[sig]
            src = self.g.signal_sources[sig]
            rd = sigmod.make_reading(pos, self.sid, src, d["range"], self.seed, sig, st["bearing_error"])
            if rd is None:
                continue
            ss = self.sig_state(sig)
            if not any(r["origin"] == self.sid for r in ss["readings"]):
                ss["readings"].append(rd)
                self.codex_add(f"sig:{sig}", "signal", d["name"], d.get("heard", ""))
            if rd.get("here"):
                ss["found"] = True
            out.append((sig, rd))
        self.advance_clock(DAY_SECONDS * 0.5)
        return out

    def signal_candidates(self, sig: str) -> list[int]:
        ss = self.sig_state(sig)
        if not ss["readings"]:
            return []
        return sigmod.candidates(self.positions(), ss["readings"], self.defs.signals[sig]["range"])

    def puzzle(self, sig: str) -> sigmod.Puzzle:
        d = self.defs.signals[sig]
        return sigmod.make_puzzle(self.seed, sig, d.get("puzzle", "sequence"), int(d.get("length", 4)), int(d.get("symbols", 6)))

    def can_decode(self, sig: str) -> bool:
        ss = self.sig_state(sig)
        return self.g.signal_sources.get(sig) == self.sid and not ss["decoded"]

    def attempt_decode(self, sig: str, guess: tuple[int, ...]) -> dict:
        """Submit a guess.  Returns {'ok': bool, 'feedback': (exact, near) | None, 'reward': [...]}"""
        pz = self.puzzle(sig)
        ss = self.sig_state(sig)
        if ss["decoded"]:
            return {"ok": True, "feedback": None, "reward": []}
        ss["attempts"].append(list(guess))
        if pz.check(tuple(guess)):
            return {"ok": True, "feedback": None, "reward": self._decode_reward(sig)}
        fb = sigmod.lock_feedback(pz.secret, tuple(guess)) if pz.kind == "lock" else None
        return {"ok": False, "feedback": fb, "reward": []}

    def _decode_reward(self, sig: str) -> list[str]:
        d = self.defs.signals[sig]
        ss = self.sig_state(sig)
        ss["decoded"] = True
        self.stats["decoded"] += 1
        rw = d.get("reward", {})
        lines = [d.get("text", "")]
        if rw.get("credits"):
            self.credits += rw["credits"]
            lines.append(f"Reward: {rw['credits']} credits.")
        if rw.get("blueprint") and rw["blueprint"] in self.defs.modules:
            self.blueprints.add(rw["blueprint"])
            lines.append(f"Blueprint: {self.defs.modules[rw['blueprint']]['name']}.")
        if rw.get("contact") and rw["contact"] in self.defs.civs:
            self.contacts.add(rw["contact"])
            self.sim.add_rep(rw["contact"], 20)
            lines.append(f"Contact established: {self.defs.civs[rw['contact']]['name']}.")
        if rw.get("route"):
            n = 0
            for ln in self.g.lanes.values():
                if ln.kind == "hidden" and (ln.reveal == f"signal:{sig}" or ln.reveal.startswith("fold:")) and ln.key not in self.revealed:
                    self.revealed.add(ln.key)
                    n += 1
                    break
            lines.append("A hidden lane is revealed." if n else "The signal charts a route you already know.")
        if rw.get("reveal"):
            near = sorted(range(len(self.g.systems)), key=lambda i: self.g.dist(i, self.sid))[: int(rw["reveal"])]
            self.visited.update(near)
            lines.append("Nearby systems are charted.")
        if rw.get("lore"):
            self.add_lore(rw["lore"])
        self.codex_add(f"sig:{sig}", "signal", d["name"], d.get("text", ""))
        self.codex[f"sig:{sig}"]["text"] = d.get("text", "")
        self.emit("orrery.signal_decoded", signal=sig)
        return lines

    def decoded_count(self) -> int:
        return sum(1 for s in self.signals.values() if s.get("decoded"))

    # ================================================================================ missions
    def refresh_missions(self) -> None:
        """Offer supply runs for the colonies that are actually starving right now."""
        existing = {(m["sid"], m["good"]) for m in self.missions if m["kind"] == "supply"}
        for sh in self.sim.shortages(0.4)[:12]:
            if len([m for m in self.missions if not m.get("done")]) >= MAX_MISSIONS:
                break
            key = (sh["sid"], sh["good"])
            if key in existing or sh["sid"] == self.sid:
                continue
            base = self.sim.base[self.sim.gi[sh["good"]]]
            qty = min(14, max(4, sh["need"]))
            hops = self.g.hops_from(self.sid).get(sh["sid"], 6)
            self.missions.append({"id": self.mission_seq, "kind": "supply", "sid": sh["sid"], "good": sh["good"], "qty": qty,
                                  "reward": int(qty * base * 1.8 + 120), "deadline": self.sim.day + 12 + 6 * hops,
                                  "civ": sh["owner"], "text": f"{self.g.systems[sh['sid']].name} is running short of "
                                  f"{self.defs.goods[sh['good']]['name']}.", "taken": False})
            self.mission_seq += 1
            existing.add(key)

    def offered_missions(self) -> list[dict]:
        return [m for m in self.missions if m["kind"] == "supply" and not m.get("taken") and not m.get("done")]

    def take_mission(self, mid: int) -> bool:
        for m in self.missions:
            if m["id"] == mid and not m.get("taken"):
                m["taken"] = True
                return True
        return False

    def deliver_mission(self, mid: int) -> str:
        for m in self.missions:
            if m["id"] != mid or not m.get("taken") or m.get("done"):
                continue
            if m["sid"] != self.sid or self.market() is None:
                return "Wrong system."
            if self.cargo.get(m["good"], 0) < m["qty"]:
                return f"You need {m['qty']} {self.defs.goods[m['good']]['name']}."
            self.cargo[m["good"]] -= m["qty"]
            if self.cargo[m["good"]] <= 0:
                del self.cargo[m["good"]]
            self.sim.sell(self.sid, m["good"], m["qty"])          # stock enters the colony (ledger stays balanced)
            self.sim.supply_effect(self.sid, m["good"], m["qty"])
            self.credits += m["reward"]
            m["done"] = True
            self.stats["profit"] += m["reward"]
            return f"Delivered. +{m['reward']} credits."
        return "No such mission."

    # ================================================================================ combat results
    def register_kill(self, kind: str) -> None:
        self.stats["kills"] += 1
        m = self.sim.markets.get(self.sid)
        if kind in ("raider", "hunter", "drone"):
            self.sim.menace[self.sid] = max(0.0, self.sim.menace[self.sid] - 0.03)
        if kind == "patrol":
            owner = self.sim.owner(self.sid)
            if owner:
                self.sim.add_rep(owner, -25)

    # ================================================================================ Last Lamp trial
    def lamp_ready(self) -> tuple[bool, str]:
        if self.decoded_count() < 3:
            return False, f"The gears do not answer. Decode {3 - self.decoded_count()} more signal(s)."
        return True, "The gears listen."

    def wind_gear(self, order: int) -> str:
        """Wind gear ``order`` (0 = innermost / smallest).  They must be wound smallest first."""
        ok, msg = self.lamp_ready()
        if not ok:
            return msg
        if self.lamp["done"]:
            return "The Lamp is already lit."
        lit = self.lamp["lit"]
        if lit[order]:
            return "This gear is already wound."
        if order != sum(lit):
            self.lamp["lit"] = [False] * LAMP_ORDER_NEEDED
            self.lamp["resets"] += 1
            return "Wrong order! The gears unwind. The smallest gear goes first, the largest last."
        lit[order] = True
        if all(lit):
            self.lamp["done"] = True
            return "The Last Lamp catches. Light spills down every lane."
        return f"Gear {order + 1} turns and holds."
