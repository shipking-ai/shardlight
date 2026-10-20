"""Contact sheet of fighter poses for visual review.  Usage: python tools/masks_sheet.py <char_id> out.png"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

from shardlight.modes.masks import render
from shardlight.modes.masks.sim.fight import Fighter
from shardlight.modes.masks.sim.moves import build_character
from shardlight.modes.masks.sim.roster import KIND, standalone_db


def main() -> None:
    pygame.init()
    pygame.display.set_mode((10, 10))
    cid, out = sys.argv[1], sys.argv[2]
    db = standalone_db()
    ch = build_character(next(d for d in db.all(KIND) if d["id"] == cid))
    cells = []
    f = Fighter(0, ch, 0, 1)

    def snap(label, **kw):
        f2 = Fighter(0, ch, 0, 1)
        for k, v in kw.items():
            setattr(f2, k, v)
        cells.append((label, f2))

    snap("idle")
    snap("walkf", state="walkf", state_t=6)
    snap("crouch", state="crouch")
    snap("jump", state="air", y=40 * 16, vy=20)
    snap("block", state="block", state_t=3)
    snap("hit", state="hit", state_t=2)
    snap("hitair", state="hitair", y=30 * 16, vy=40)
    snap("down", state="down", state_t=5)
    for key in ("5L", "5H", "2M", "2H", "j.H"):
        mv = ch.moves[key]
        frames = [max(1, mv.startup // 2), mv.startup, mv.last_active + 2, mv.total - 2]
        for fr in frames:
            kw = dict(state="attack", move=mv, mf=fr, state_t=fr)
            if mv.air:
                kw.update(y=34 * 16, vy=-10)
            snap(f"{key}:{fr}", **kw)
    for key, mv in ch.moves.items():
        if mv.kind in ("special", "super"):
            snap(f"{key}:{mv.startup}", state="attack", move=mv, mf=mv.startup, state_t=mv.startup)
    cols = 8
    rows = (len(cells) + cols - 1) // cols
    cw, chh = 120, 120
    sheet = pygame.Surface((cols * cw, rows * chh))
    sheet.fill((222, 206, 184))
    font = render.get_font() if hasattr(render, "get_font") else None
    from shardlight.core.font import get_font
    font = get_font()
    for i, (label, fi) in enumerate(cells):
        cell = pygame.Surface((480, 270))
        cell.fill((222, 206, 184))
        pygame.draw.line(cell, (110, 90, 80), (0, render.GROUND_Y), (480, render.GROUND_Y))
        render.draw_fighter(cell, fi, 0, 10 + i)
        crop = cell.subsurface(pygame.Rect(240 - 60, render.GROUND_Y - 100, 120, 110))
        sheet.blit(crop, ((i % cols) * cw, (i // cols) * chh))
        font.draw(sheet, label, ((i % cols) * cw + 3, (i // cols) * chh + 3), (40, 30, 50), None)
    pygame.image.save(pygame.transform.scale(sheet, (sheet.get_width() * 2, sheet.get_height() * 2)), out)


main()
