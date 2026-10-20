"""Authoring tool: builds the Masks roster as plain dicts and writes data/masks.character/<id>.json.

Characters are *data*; this script is the readable source the JSON is generated from (a compact DSL keeps
frame data consistent: block/hit advantage are specified and stun values are derived from them).
Run:  python tools/masks_roster.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "masks.character"

HURT = {"stand": [-13, 0, 26, 78], "crouch": [-13, 0, 26, 46], "air": [-13, 8, 26, 60]}


def move(name, inp, su, ac, rec, rect, dmg, adv_hit, adv_block, kind="normal", height="mid", stance="stand",
         air=False, push=(8, 9), hitstop=None, launch=None, kd=False, cancels=None, meter=(18, 8), chip=0,
         starter=100, spark="light", juggle=1, desc="", **extra):
    total = su + ac + rec - 1
    base = total - su
    hit = {"damage": dmg, "hitstun": max(1, adv_hit + base), "blockstun": max(1, adv_block + base),
           "hitstop": hitstop if hitstop is not None else (7 if dmg < 40 else 9 if dmg < 70 else 11),
           "push_hit": push[0], "push_block": push[1], "height": height, "meter_hit": meter[0],
           "meter_block": meter[1], "chip": chip, "starter": starter, "spark": spark, "juggle": juggle}
    if launch:
        hit["launch"] = list(launch)
    if kd:
        hit["knockdown"] = True
    d = {"name": name, "kind": kind, "startup": su, "active": ac, "recovery": rec, "stance": stance,
         "hit": hit, "desc": desc}
    if inp:
        d["input"] = inp
    if air:
        d["air"] = True
        d["stance"] = "air"
    if rect:
        d["hitboxes"] = [{"rect": rect}]
    if cancels:
        d["cancels"] = cancels
    d.update(extra)
    return d


def chain(*into, on="contact"):
    return [{"on": on, "into": list(into)}]


def throw(name="Throw", reach=26, dmg=90, rec=22):
    return {"name": name, "input": "L+M", "kind": "throw", "startup": 5, "active": 2, "recovery": rec,
            "hit": {"damage": dmg, "hitstun": 20, "blockstun": 0, "hitstop": 10, "knockdown": True,
                    "launch": [26, 95], "starter": 80, "meter_hit": 40, "spark": "heavy", "unblockable": True},
            "throw": {"reach": reach, "tech": True, "grab_frames": 24},
            "desc": "Beats blocking. Tech by pressing L+M within 8 frames."}


def base(cid, name, title, feeling, archetype, desc, color, accent, health=1000, walk=(36, 30), jump=(150, 36),
         dash=(14, 92, 9), back=(18, 84, 6, 4), push=11, mech=""):
    return {"id": cid, "name": name, "title": title, "feeling": feeling, "archetype": archetype, "desc": desc,
            "color": list(color), "accent": list(accent), "health": health, "walk_f": walk[0], "walk_b": walk[1],
            "jump": {"pre": 4, "vy": jump[0], "vx": jump[1], "gravity": 8},
            "dash_f": {"frames": dash[0], "vx": dash[1], "cancel": dash[2]},
            "dash_b": {"frames": back[0], "vx": back[1], "invuln": back[2], "recovery": back[3]},
            "push_half": push, "hurt": dict(HURT), "mech": mech, "moves": {}}


def standard_normals(m, light=(4, 3, 8), med=(7, 3, 12), heavy=(11, 4, 18), reach=1.0, dmg=1.0, heavy_kd=True,
                     special_cancel=("special", "super")):
    """Shared normal set; characters then override or add on top for identity."""
    def r(rect):
        return [int(rect[0]), rect[1], int(rect[2] * reach), rect[3]]

    d = lambda v: int(v * dmg)
    sc = list(special_cancel)
    m["5L"] = move("Jab", "L", *light, r([10, 42, 26, 12]), d(28), 3, 1, cancels=chain("5M", "2M", *sc), push=(7, 8))
    m["5M"] = move("Strike", "M", *med, r([10, 36, 38, 18]), d(50), 3, -1, cancels=chain("5H", *sc), push=(9, 10),
                   spark="med")
    m["5H"] = move("Heavy Strike", "H", *heavy, r([8, 30, 46, 36]), d(82), 8 if heavy_kd else 3, -6, hitstop=11,
                   launch=(26, 90) if heavy_kd else None, kd=heavy_kd, cancels=chain(*sc, on="hit"), spark="heavy",
                   starter=90, push=(12, 12), chip=0)
    m["2L"] = move("Low Jab", "2L", 4, 3, 8, r([10, 6, 26, 14]), d(24), 3, 0, stance="crouch",
                   cancels=chain("2M", "5M", *sc), push=(6, 7))
    m["2M"] = move("Sweeping Low", "2M", 7, 3, 14, r([8, 0, 44, 12]), d(46), 2, -3, height="low", stance="crouch",
                   cancels=chain("2H", *sc), push=(10, 10), spark="med")
    m["2H"] = move("Rising Strike", "2H", 9, 4, 21, r([2, 28, 30, 62]), d(74), 6, -9, stance="crouch", launch=(10, 118),
                   kd=True, cancels=chain(*sc, on="hit"), spark="heavy", starter=90, juggle=2,
                   invuln=[{"from": 1, "to": 4, "kind": "strike"}], desc="Anti-air launcher.")
    m["j.L"] = move("Air Jab", "j.L", 5, 6, 6, r([8, 24, 26, 20]), d(30), 6, 4, air=True, height="high", push=(6, 6),
                    land_recovery=4)
    m["j.H"] = move("Air Heavy", "j.H", 9, 6, 8, r([6, 6, 36, 44]), d(66), 8, 6, air=True, height="high",
                    spark="med", push=(8, 8), launch=(24, 78), kd=True, land_recovery=6)
    m["throw"] = throw()
    return m


def kagari():
    c = base("kagari", "Kagari", "Mask of Rage", "Rage", "rushdown",
             "Fast, close and loud. Kagari wins by never letting the other fighter breathe.",
             (214, 72, 52), (255, 200, 90), health=980, walk=(42, 32), dash=(13, 104, 8), push=10,
             mech="Rushdown: fastest walk and dash, strong frame traps, but fragile.")
    standard_normals(c["moves"], light=(4, 3, 7), med=(6, 3, 11), heavy=(10, 4, 17), dmg=1.0)
    m = c["moves"]
    m["flare"] = move("Flare Rush", "236M", 12, 4, 17, [8, 36, 44, 24], 62, 4, -2, kind="special",
                      steps=None, push=(10, 10), chip=12, spark="med", meter=(30, 14),
                      move=[{"from": 8, "to": 15, "vx": 118}], cancels=chain("super", on="hit"),
                      desc="Lunging punch that closes the whole screen gap.")
    m["flareL"] = move("Short Flare", "236L", 9, 3, 15, [8, 36, 38, 24], 44, 2, -3, kind="special", chip=10,
                       move=[{"from": 6, "to": 11, "vx": 78}], meter=(24, 10))
    m["rising"] = move("Rising Cinder", "623H", 5, 5, 34, [0, 10, 34, 74], 92, 0, -28, kind="special", launch=(16, 128),
                       kd=True, spark="heavy", starter=85, juggle=2, chip=15, meter=(40, 20),
                       invuln=[{"from": 1, "to": 8, "kind": "all"}],
                       desc="Reversal uppercut: invincible startup, hugely punishable on block.")
    m["slide"] = move("Cinder Slide", "214M", 14, 3, 17, [10, 0, 52, 12], 56, -2, -6, kind="special", height="low",
                      stance="crouch", kd=True, push=(8, 8), spark="med", move=[{"from": 10, "to": 16, "vx": 70}],
                      desc="Low slide; mixes with Flare Rush.")
    m["wildfire"] = move("Wildfire", "236236H", 8, 8, 40, [6, 20, 66, 60], 230, 0, -20, kind="super", cost=500,
                         superflash=34, launch=(30, 120), kd=True, spark="heavy", starter=100, hitstop=14, meter=(0, 0),
                         invuln=[{"from": 1, "to": 8, "kind": "all"}], move=[{"from": 6, "to": 14, "vx": 60}])
    return c


def mirei():
    c = base("mirei", "Mirei", "Mask of Sorrow", "Sorrow", "zoner",
             "Keeps the world at arm's length with needles of pale light. Hates being touched.",
             (96, 130, 230), (220, 240, 255), health=940, walk=(32, 30), jump=(160, 34), dash=(16, 84, 10), push=10,
             mech="Zoner: one needle on screen at a time; strong anti-air and a fast back-hop.")
    standard_normals(c["moves"], light=(5, 3, 9), med=(8, 3, 13), heavy=(12, 4, 20), reach=1.1, dmg=0.95)
    m = c["moves"]
    proj = lambda vx, hitd, life=90, hits=1: {"frame": 14, "rect": [-9, -5, 18, 10], "offset": [26, 46], "vx": vx,
                                               "life": life, "hit": hitd, "hits": hits, "limit": 1}
    m["needleL"] = move("Slow Needle", "236L", 13, 2, 22, None, 40, 6, 2, kind="special", chip=8,
                        projectile=proj(52, {"damage": 40, "hitstun": 18, "blockstun": 14, "hitstop": 8, "chip": 8,
                                             "push_hit": 8, "push_block": 9, "spark": "light", "meter_hit": 20,
                                             "meter_block": 8}), desc="Slow needle; leaves you plus at range.")
    m["needleM"] = move("Fast Needle", "236M", 13, 2, 26, None, 48, 4, 0, kind="special",
                        projectile=proj(96, {"damage": 48, "hitstun": 18, "blockstun": 13, "hitstop": 8, "chip": 8,
                                             "push_hit": 9, "push_block": 10, "spark": "light", "meter_hit": 22,
                                             "meter_block": 8}))
    m["needleH"] = move("Pale Comet", "236H", 18, 2, 30, None, 70, 3, -2, kind="special",
                        projectile={"frame": 18, "rect": [-12, -10, 24, 20], "offset": [28, 44], "vx": 74, "life": 110,
                                    "limit": 1, "hits": 2, "destroy_on_hit": False,
                                    "hit": {"damage": 38, "hitstun": 22, "blockstun": 16, "hitstop": 6, "chip": 10,
                                            "push_hit": 6, "push_block": 8, "spark": "med", "meter_hit": 20,
                                            "meter_block": 8}},
                        desc="Slow two-hit comet that eats lighter needles.")
    m["lance"] = move("Dawn Lance", "623M", 6, 4, 30, [0, 10, 32, 80], 76, 0, -24, kind="special", launch=(12, 124),
                      kd=True, spark="heavy", starter=85, juggle=2, invuln=[{"from": 1, "to": 6, "kind": "strike"}])
    m["hop"] = move("Veil Hop", "214L", 3, 1, 28, None, 0, 0, 0, kind="special", air=False,
                    invuln=[{"from": 1, "to": 12, "kind": "all"}],
                    move=[{"from": 1, "to": 12, "vx": -96, "vy": 0}], desc="Backward hop, invulnerable while it moves.")
    m["rain"] = move("Rain of Pins", "236236L", 16, 3, 40, None, 0, 0, 0, kind="super", cost=500, superflash=30,
                     projectile={"frame": 16, "rect": [-70, -4, 140, 8], "offset": [10, 44], "vx": 70, "life": 70,
                                 "limit": 1, "hits": 7, "destroy_on_hit": False,
                                 "hit": {"damage": 34, "hitstun": 22, "blockstun": 16, "hitstop": 5, "chip": 15,
                                         "push_hit": 4, "push_block": 6, "spark": "light", "meter_hit": 0,
                                         "meter_block": 0, "starter": 100}})
    return c


def ushi():
    c = base("ushi", "Ushi", "Mask of Stubbornness", "Stubbornness", "grappler",
             "Slow, wide and immovable. Ushi does not win exchanges - Ushi ends them.",
             (140, 110, 80), (230, 190, 120), health=1120, walk=(28, 24), jump=(142, 30), dash=(18, 70, 12),
             back=(22, 66, 3, 6), push=14, mech="Grappler: biggest health and damage; slow walk; armoured shoulder; command grab.")
    standard_normals(c["moves"], light=(5, 3, 9), med=(8, 4, 14), heavy=(13, 4, 22), reach=1.15, dmg=1.12)
    m = c["moves"]
    m["throw"]["throw"]["reach"] = 32
    m["throw"]["hit"]["damage"] = 110
    m["maw"] = {"name": "Maw Breaker", "input": "63214L", "kind": "special", "startup": 6, "active": 2,
                "recovery": 26,
                "hit": {"damage": 150, "hitstun": 20, "blockstun": 0, "hitstop": 12, "knockdown": True,
                        "launch": [30, 100], "starter": 70, "meter_hit": 50, "spark": "heavy", "unblockable": True},
                "throw": {"reach": 30, "tech": False, "grab_frames": 30},
                "desc": "Command grab: cannot be teched, must be jumped or walked away from."}
    m["shoulder"] = move("Boulder Shoulder", "236M", 15, 4, 24, [4, 24, 44, 52], 78, -2, -8, kind="special",
                         armor={"from": 6, "to": 14, "hits": 1}, move=[{"from": 8, "to": 18, "vx": 56}], chip=14,
                         spark="heavy", kd=True, launch=(18, 86), starter=90, push=(14, 14),
                         desc="One hit of armour while charging; very punishable if blocked.")
    m["hammer"] = move("Hammer Fist", "214H", 20, 4, 24, [6, 50, 40, 36], 96, -3, -10, kind="special", height="high",
                       kd=True, launch=(18, 100), spark="heavy", starter=90, hitstop=13,
                       desc="Slow overhead: only a standing block stops it.")
    m["quake"] = move("Earthbreaker", "63214H", 7, 4, 38, [0, 0, 80, 20], 240, 0, -18, kind="super", cost=500,
                      superflash=32, kd=True, launch=(22, 110), spark="heavy", starter=100,
                      hitstop=14, meter=(0, 0), invuln=[{"from": 1, "to": 8, "kind": "all"}],
                      desc="Invulnerable super: slams the ground in front of Ushi.")
    return c


def shizuka():
    c = base("shizuka", "Shizuka", "Mask of Calm", "Calm", "counter",
             "Stands very still. Whatever you throw at her has already been answered.",
             (150, 190, 160), (240, 245, 220), health=1000, walk=(34, 30), push=10,
             mech="Counter-fighter: stance moves beat a chosen attack height and answer it with a heavy punish.")
    standard_normals(c["moves"], light=(4, 3, 8), med=(7, 3, 12), heavy=(11, 4, 19), reach=1.0, dmg=0.97)
    m = c["moves"]
    m["highstance"] = move("Mountain Stance", "214L", 3, 1, 36, None, 0, 0, 0, kind="special",
                           counter={"from": 4, "to": 22, "height": "high", "into": "crash"})
    m["midstance"] = move("River Stance", "214M", 3, 1, 36, None, 0, 0, 0, kind="special",
                          counter={"from": 4, "to": 22, "height": "mid", "into": "crash"})
    m["lowstance"] = move("Reed Stance", "214H", 3, 1, 36, None, 0, 0, 0, kind="special",
                          counter={"from": 4, "to": 22, "height": "low", "into": "crash"}, stance="crouch")
    m["crash"] = move("Answering Palm", None, 6, 3, 22, [6, 24, 48, 52], 96, 6, -4, kind="follow", launch=(24, 100),
                      kd=True, spark="heavy", starter=90, invuln=[{"from": 1, "to": 6, "kind": "all"}],
                      desc="Automatic answer when a stance catches an attack.")
    m["rising"] = move("Heron Rise", "623M", 7, 4, 30, [0, 10, 30, 78], 70, 0, -22, kind="special", launch=(12, 124),
                       kd=True, spark="heavy", starter=85, juggle=2, invuln=[{"from": 1, "to": 6, "kind": "strike"}])
    m["glide"] = move("Willow Glide", "236M", 11, 3, 18, [8, 36, 42, 22], 52, 1, -3, kind="special", chip=8,
                      move=[{"from": 7, "to": 12, "vx": 86}], spark="med")
    m["still"] = move("Stillwater", "236236M", 9, 6, 38, [0, 10, 70, 70], 210, 0, -18, kind="super", cost=500,
                      superflash=30, launch=(24, 110), kd=True, spark="heavy", starter=100, hitstop=14, meter=(0, 0),
                      invuln=[{"from": 1, "to": 10, "kind": "all"}])
    return c


def toki():
    c = base("toki", "Toki", "Warden of Hours", "Patience", "time",
             "She is never late and never early. She waits for you to run out of your own time.",
             (182, 150, 255), (255, 235, 190), health=980, walk=(30, 28), dash=(15, 80, 10), push=10,
             mech="Time: places a slow zone (opponent acts at 2/3 speed inside it) and echo hits that return 34 frames later.")
    c["requires_unlock"] = "masks.rival.warden_of_hours"
    standard_normals(c["moves"], light=(5, 3, 9), med=(8, 3, 13), heavy=(12, 4, 20), reach=1.05, dmg=0.96)
    m = c["moves"]
    m["zone"] = move("Slow Hour", "236L", 14, 1, 26, None, 0, 0, 0, kind="special",
                     zone={"frame": 14, "rect": [-48, 0, 96, 90], "offset": 74, "life": 190, "slow": 3},
                     desc="Opponents inside the zone move at two thirds speed. One zone at a time.")
    m["echo"] = move("Echo Slash", "214M", 10, 3, 24, [8, 30, 46, 40], 54, 1, -4, kind="special", echo=True,
                     spark="slash", chip=10, desc="The same slash lands again 34 frames later where Toki was standing.")
    m["rewind"] = move("Rewind Step", "623L", 5, 4, 26, [0, 10, 28, 74], 60, 0, -22, kind="special", launch=(12, 120),
                       kd=True, spark="heavy", starter=85, juggle=2,
                       invuln=[{"from": 1, "to": 6, "kind": "strike"}])
    m["stopped"] = move("Stopped Clock", "236236M", 12, 4, 40, [4, 10, 74, 70], 200, 0, -16, kind="super", cost=500,
                        superflash=40, launch=(20, 110), kd=True, spark="heavy", starter=100, hitstop=14,
                        meter=(0, 0), invuln=[{"from": 1, "to": 12, "kind": "all"}],
                        zone={"frame": 12, "rect": [-70, 0, 140, 90], "offset": 40, "life": 160, "slow": 2})
    return c


def silence():
    c = base("silence", "Silence", "Mask of Silence", "Silence", "boss",
             "The last mask has no face. It is only the pause after everything has been said.",
             (60, 56, 78), (240, 232, 214), health=1250, walk=(36, 30), dash=(14, 96, 9), push=12,
             mech="Boss: armoured heavies, a long-range wave and an invulnerable reversal.")
    c["boss"] = True
    c["selectable"] = False
    standard_normals(c["moves"], light=(5, 3, 8), med=(7, 3, 12), heavy=(11, 4, 18), reach=1.1, dmg=1.0)
    m = c["moves"]
    m["5H"]["armor"] = {"from": 8, "to": 12, "hits": 1}
    m["wave"] = move("Hush", "236M", 16, 2, 28, None, 0, 0, 0, kind="special",
                     projectile={"frame": 16, "rect": [-10, -30, 20, 60], "offset": [24, 24], "vx": 62, "life": 120,
                                 "limit": 1, "hits": 1,
                                 "hit": {"damage": 62, "hitstun": 22, "blockstun": 15, "hitstop": 9, "chip": 10,
                                         "push_hit": 10, "push_block": 10, "spark": "med", "meter_hit": 24,
                                         "meter_block": 8}})
    m["reversal"] = move("Last Word", "623H", 4, 5, 34, [0, 10, 36, 78], 88, 0, -26, kind="special", launch=(14, 128),
                         kd=True, spark="heavy", starter=85, juggle=2, invuln=[{"from": 1, "to": 8, "kind": "all"}])
    m["dash"] = move("Pause", "236L", 11, 4, 18, [8, 34, 42, 28], 60, 2, -3, kind="special",
                     move=[{"from": 7, "to": 14, "vx": 100}], chip=10, spark="med")
    m["end"] = move("Final Silence", "236236H", 9, 8, 42, [4, 12, 80, 74], 220, 0, -20, kind="super", cost=500,
                    superflash=34, launch=(26, 112), kd=True, spark="heavy", starter=100, hitstop=14, meter=(0, 0),
                    invuln=[{"from": 1, "to": 9, "kind": "all"}])
    return c


ROSTER = [kagari, mirei, ushi, shizuka, toki, silence]


def clean(d):
    """JSON-safe: drop None values (e.g. steps=None)."""
    if isinstance(d, dict):
        return {k: clean(v) for k, v in d.items() if v is not None}
    if isinstance(d, list):
        return [clean(v) for v in d]
    return d


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in ROSTER:
        c = fn()
        for mv in c["moves"].values():
            mv.pop("steps", None)
        data = clean(c)
        (OUT / f"{c['id']}.json").write_text(json.dumps({"entries": [data]}, indent=1), encoding="utf-8")
        print("wrote", c["id"], len(data["moves"]), "moves")


if __name__ == "__main__":
    sys.exit(main())
