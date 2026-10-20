"""Water and lava as a conservative cellular automaton on the liquid layer.

Each cell holds an amount 0..8 and a lava bit.  Liquid falls, then levels out sideways.  Lava moves at half speed.
Lava meeting water turns to obsidian (consuming a unit of water); liquids are displaced by solid blocks.
Only *active* cells are visited, with a per-call budget, so a big lake costs nothing while it is still.
"""
from __future__ import annotations

from . import constants as K
from .world import World

NEIGH = ((0, 1), (-1, 0), (1, 0), (0, -1))


def step(world: World, budget: int = 900, tick: int = 0) -> int:
    """Advance the fluid simulation; returns the number of cells processed."""
    act = world.active_liquid
    if not act:
        return 0
    cells = sorted(act, key=lambda c: (-c[1], c[0] if tick % 2 == 0 else -c[0]))[:budget]
    for c in cells:
        act.discard(c)
    liq = world.grid.liq
    blocks = world.grid.blocks
    solid = world.reg.solid
    n = 0
    for (x, y) in cells:
        if not (0 <= x < world.w and 0 <= y < world.h):
            continue
        v = int(liq[y, x])
        a, lava = v & K.LIQ_AMOUNT_MASK, bool(v & K.LIQ_LAVA)
        if a == 0:
            continue
        n += 1
        if solid[blocks[y, x]]:
            liq[y, x] = 0                                         # displaced by a block placed on it
            continue
        if lava and (tick & 1):
            act.add((x, y))
            continue
        # lava against water makes obsidian
        touched = False
        for dx, dy in NEIGH:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < world.w and 0 <= ny < world.h):
                continue
            nv = int(liq[ny, nx])
            if nv & K.LIQ_AMOUNT_MASK and bool(nv & K.LIQ_LAVA) != lava:
                lx, ly, wx, wy = (x, y, nx, ny) if lava else (nx, ny, x, y)
                liq[ly, lx] = 0
                blocks[ly, lx] = K.OBSIDIAN
                world.grid.mark(lx, ly)
                wa = int(liq[wy, wx]) & K.LIQ_AMOUNT_MASK
                liq[wy, wx] = (wa - 1) if wa > 1 else 0
                world.grid.mark(wx, wy)
                world.events.append(("hiss", {"x": lx, "y": ly}))
                act.add((wx, wy))
                touched = True
                break
        if touched:
            continue
        # fall
        by = y + 1
        if by < world.h and not solid[blocks[by, x]]:
            bv = int(liq[by, x])
            ba, blava = bv & K.LIQ_AMOUNT_MASK, bool(bv & K.LIQ_LAVA)
            if ba == 0 or blava == lava:
                move = min(a, K.LIQ_MAX - ba)
                if move > 0:
                    _set(world, x, y, a - move, lava)
                    _set(world, x, by, ba + move, lava)
                    act.add((x, by))
                    act.add((x, y))
                    for dx in (-1, 1):
                        act.add((x + dx, y))
                    a -= move
                    if a == 0:
                        continue
        # spread sideways towards the lower neighbour
        order = ((-1, 1) if (x + y + tick) % 2 == 0 else (1, -1))
        for dx in order:
            nx = x + dx
            if not (0 <= nx < world.w) or solid[blocks[y, nx]]:
                continue
            nv = int(liq[y, nx])
            na, nlava = nv & K.LIQ_AMOUNT_MASK, bool(nv & K.LIQ_LAVA)
            if na and nlava != lava:
                continue
            if a > na + 1:
                give = (a - na) // 2
                if give > 0:
                    _set(world, x, y, a - give, lava)
                    _set(world, nx, y, na + give, lava)
                    act.add((nx, y))
                    act.add((x, y))
                    a -= give
                    if a <= 0:
                        break
    return n


def _set(world: World, x: int, y: int, amount: int, lava: bool) -> None:
    world.grid.liq[y, x] = (amount | (K.LIQ_LAVA if lava else 0)) if amount > 0 else 0
    world.grid.mark(x, y, neighbours=False)
    act = world.active_liquid
    act.add((x, y))
    act.add((x - 1, y))
    act.add((x + 1, y))
    act.add((x, y - 1))
    act.add((x, y + 1))


def total(world: World, lava: bool | None = None) -> int:
    """Sum of liquid units (optionally only water or only lava): used by tests to check conservation."""
    liq = world.grid.liq
    amt = (liq & K.LIQ_AMOUNT_MASK).astype(int)
    if lava is None:
        return int(amt.sum())
    is_l = (liq & K.LIQ_LAVA) > 0
    return int(amt[is_l == lava].sum())


def settle(world: World, max_steps: int = 400) -> int:
    """Run the automaton until it comes to rest (or the step cap); returns steps used."""
    for i in range(max_steps):
        if not world.active_liquid:
            return i
        step(world, 5000, i)
    return max_steps
