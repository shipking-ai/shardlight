"""Frame-data validator: catches broken characters (also from mods) before they reach a match."""
from __future__ import annotations

from .consts import MAX_METER, SUB
from .moves import Character, Move

CANCEL_TAGS = {"special", "super", "normal", "heavy", "dash", "jump", "light", "any"}
MAX_REACH = 150 * SUB
MAX_DAMAGE = {"normal": 130, "special": 190, "throw": 260, "super": 420, "follow": 260, "system": 100}


def _rect_ok(r, where: str, out: list[str], hurt: bool = False, relative: bool = False) -> None:
    x, y, w, h = r
    if relative:        # projectile/zone rects are relative to their own centre: only check size
        if w <= 0 or h <= 0 or w > 200 * SUB or h > 130 * SUB:
            out.append(f"{where}: rect size out of range")
        return
    if w <= 0 or h <= 0:
        out.append(f"{where}: rect has non-positive size")
    if abs(x) > MAX_REACH or x + w > MAX_REACH or x + w < -MAX_REACH:
        out.append(f"{where}: rect x range outside +/-{MAX_REACH // SUB}px")
    if y < -10 * SUB or y > 130 * SUB or y + h > 160 * SUB:
        out.append(f"{where}: rect vertical range out of bounds")
    if w > 140 * SUB or h > 130 * SUB:
        out.append(f"{where}: rect implausibly large")


def validate_move(ch: Character, mv: Move) -> list[str]:
    out: list[str] = []
    w = f"{ch.id}.{mv.key}"
    if mv.startup < 1:
        out.append(f"{w}: startup must be >= 1")
    if mv.active < 1:
        out.append(f"{w}: zero active frames")
    if mv.recovery < 0:
        out.append(f"{w}: negative recovery")
    if mv.total > 140:
        out.append(f"{w}: total length {mv.total} exceeds 140 frames")
    has_effect = bool(mv.boxes or mv.projectile or mv.throw or mv.zone or mv.counter or "stance" in mv.tags
                      or mv.armor or mv.invuln or mv.steps)
    if not has_effect:
        out.append(f"{w}: move does nothing (no hitbox, projectile, throw, zone, counter or movement)")
    if mv.kind in ("normal", "special", "super") and not (mv.boxes or mv.projectile or mv.zone or mv.counter
                                                           or mv.invuln or mv.steps or mv.throw):
        out.append(f"{w}: attack has no hitbox or projectile")
    for b in mv.boxes:
        _rect_ok(b.rect, f"{w}.hitbox", out)
        if not (1 <= b.f0 <= b.f1 <= mv.total):
            out.append(f"{w}: hitbox frames {b.f0}-{b.f1} outside move (1-{mv.total})")
        elif b.f0 < mv.startup or b.f1 > mv.last_active:
            out.append(f"{w}: hitbox frames {b.f0}-{b.f1} outside active window {mv.startup}-{mv.last_active}")
    for b in mv.hurt:
        _rect_ok(b.rect, f"{w}.hurt", out, True)
        if not (1 <= b.f0 <= b.f1 <= mv.total):
            out.append(f"{w}: hurtbox frames {b.f0}-{b.f1} outside move")
    hits = [mv.hit] + [b.hit for b in mv.boxes if b.hit]
    if mv.projectile:
        hits.append(mv.projectile.hit)
        _rect_ok(mv.projectile.rect, f"{w}.projectile", out, relative=True)
        if not 1 <= mv.projectile.frame <= mv.total:
            out.append(f"{w}: projectile spawn frame outside move")
        if mv.projectile.life < 1:
            out.append(f"{w}: projectile lifetime must be positive")
    if mv.throw:
        hits.append(mv.throw.hit)
        if mv.throw.reach > 80 * SUB:
            out.append(f"{w}: throw reach too long")
    if mv.zone:
        _rect_ok(mv.zone.rect, f"{w}.zone", out, relative=True)
    cap = MAX_DAMAGE.get(mv.kind, 130)
    for h in hits:
        if h.damage > cap:
            out.append(f"{w}: damage {h.damage} exceeds cap {cap} for kind {mv.kind}")
        if h.damage and h.hitstun <= 0 and not h.knockdown and not h.launch:
            out.append(f"{w}: hit deals damage but has no hitstun")
        if h.damage and h.blockstun <= 0 and not h.unblockable and mv.throw is None:
            out.append(f"{w}: blockable hit has no blockstun")
    if mv.boxes and mv.throw is None and not mv.air:
        adv_b = mv.adv_on(False, mv.last_active)
        if adv_b is not None and adv_b > 8:
            out.append(f"{w}: +{adv_b} on block at last active frame is too plus")
    for c in mv.cancels:
        if not 1 <= c.f0 <= min(c.f1, mv.total + 999):
            out.append(f"{w}: cancel window {c.f0}-{c.f1} invalid")
        if c.f0 > mv.total:
            out.append(f"{w}: cancel starts after move ends")
        for tgt in c.into:
            if tgt not in ch.moves and tgt not in CANCEL_TAGS:
                out.append(f"{w}: cancel into unknown move or tag {tgt!r}")
    for inv in mv.invuln:
        if not 1 <= inv.f0 <= inv.f1 <= mv.total:
            out.append(f"{w}: invulnerability {inv.f0}-{inv.f1} outside move")
    if mv.armor and not 1 <= mv.armor.f0 <= mv.armor.f1 <= mv.total:
        out.append(f"{w}: armour window outside move")
    if mv.counter:
        if mv.counter.into not in ch.moves:
            out.append(f"{w}: counter references unknown move {mv.counter.into!r}")
        if not 1 <= mv.counter.f0 <= mv.counter.f1 <= mv.total:
            out.append(f"{w}: counter window outside move")
    for s in mv.steps:
        if not 1 <= s.f0 <= s.f1 <= mv.total:
            out.append(f"{w}: movement step outside move")
        if abs(s.vx) > 200 or abs(s.vy) > 400:
            out.append(f"{w}: movement step velocity implausible")
    if mv.kind == "super" and not 0 < mv.cost <= MAX_METER:
        out.append(f"{w}: super needs a meter cost between 1 and {MAX_METER}")
    if mv.kind in ("special", "super", "throw", "normal") and not mv.notation:
        out.append(f"{w}: input move without notation")
    if mv.kind == "follow" and mv.notation:
        out.append(f"{w}: follow-up moves must not have an input")
    return out


def validate_character(ch: Character) -> list[str]:
    out: list[str] = []
    for k in ("stand", "crouch", "air"):
        if k not in ch.hurt:
            out.append(f"{ch.id}: missing hurtbox {k!r}")
        else:
            _rect_ok(ch.hurt[k], f"{ch.id}.hurt.{k}", out, True)
    if "throw" not in ch.moves:
        out.append(f"{ch.id}: needs a move keyed 'throw'")
    seen: dict[str, str] = {}
    for key, mv in ch.moves.items():
        out += validate_move(ch, mv)
        if mv.notation:
            if mv.notation in seen:
                out.append(f"{ch.id}: duplicate input {mv.notation!r} on {seen[mv.notation]} and {key}")
            seen[mv.notation] = key
    referenced: set[str] = set()
    for mv in ch.moves.values():
        for c in mv.cancels:
            referenced.update(t for t in c.into if t in ch.moves)
        if mv.counter:
            referenced.add(mv.counter.into)
    for key, mv in ch.moves.items():
        if mv.kind == "follow" and key not in referenced:
            out.append(f"{ch.id}.{key}: follow-up move is unreachable")
    if not 600 <= ch.health <= 1400:
        out.append(f"{ch.id}: health out of range")
    if ch.dash_f[0] < 6:
        out.append(f"{ch.id}: forward dash too short")
    return out


def validate_all(chars: dict[str, Character]) -> dict[str, list[str]]:
    return {cid: errs for cid, ch in chars.items() if (errs := validate_character(ch))}
