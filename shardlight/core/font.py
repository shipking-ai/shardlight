"""Original 5x8 pixel font (ASCII 32-126) drawn from hex row tables, with caching, outline and wrapping.

Every glyph is 8 rows of 5 bits (MSB = leftmost pixel).  The font is part of the game's identity: all
text at the 480x270 internal resolution uses it so type is crisp at any window scale.
"""
from __future__ import annotations

import pygame

_TABLE = """
32:00 00 00 00 00 00 00 00
33:04 04 04 04 04 00 04 00
34:0A 0A 0A 00 00 00 00 00
35:0A 0A 1F 0A 1F 0A 0A 00
36:04 0F 14 0E 05 1E 04 00
37:18 19 02 04 08 13 03 00
38:0C 12 14 08 15 12 0D 00
39:04 04 08 00 00 00 00 00
40:02 04 08 08 08 04 02 00
41:08 04 02 02 02 04 08 00
42:00 04 15 0E 15 04 00 00
43:00 04 04 1F 04 04 00 00
44:00 00 00 00 0C 04 08 00
45:00 00 00 1F 00 00 00 00
46:00 00 00 00 00 0C 0C 00
47:00 01 02 04 08 10 00 00
48:0E 11 13 15 19 11 0E 00
49:04 0C 04 04 04 04 0E 00
50:0E 11 01 02 04 08 1F 00
51:1F 02 04 02 01 11 0E 00
52:02 06 0A 12 1F 02 02 00
53:1F 10 1E 01 01 11 0E 00
54:06 08 10 1E 11 11 0E 00
55:1F 01 02 04 08 08 08 00
56:0E 11 11 0E 11 11 0E 00
57:0E 11 11 0F 01 02 0C 00
58:00 0C 0C 00 0C 0C 00 00
59:00 0C 0C 00 0C 04 08 00
60:02 04 08 10 08 04 02 00
61:00 00 1F 00 1F 00 00 00
62:08 04 02 01 02 04 08 00
63:0E 11 01 02 04 00 04 00
64:0E 11 17 15 17 10 0E 00
65:0E 11 11 1F 11 11 11 00
66:1E 11 11 1E 11 11 1E 00
67:0E 11 10 10 10 11 0E 00
68:1C 12 11 11 11 12 1C 00
69:1F 10 10 1E 10 10 1F 00
70:1F 10 10 1E 10 10 10 00
71:0E 11 10 17 11 11 0F 00
72:11 11 11 1F 11 11 11 00
73:0E 04 04 04 04 04 0E 00
74:07 02 02 02 02 12 0C 00
75:11 12 14 18 14 12 11 00
76:10 10 10 10 10 10 1F 00
77:11 1B 15 15 11 11 11 00
78:11 11 19 15 13 11 11 00
79:0E 11 11 11 11 11 0E 00
80:1E 11 11 1E 10 10 10 00
81:0E 11 11 11 15 12 0D 00
82:1E 11 11 1E 14 12 11 00
83:0F 10 10 0E 01 01 1E 00
84:1F 04 04 04 04 04 04 00
85:11 11 11 11 11 11 0E 00
86:11 11 11 11 11 0A 04 00
87:11 11 11 15 15 15 0A 00
88:11 11 0A 04 0A 11 11 00
89:11 11 11 0A 04 04 04 00
90:1F 01 02 04 08 10 1F 00
91:0E 08 08 08 08 08 0E 00
92:00 10 08 04 02 01 00 00
93:0E 02 02 02 02 02 0E 00
94:04 0A 11 00 00 00 00 00
95:00 00 00 00 00 00 00 1F
96:08 04 02 00 00 00 00 00
97:00 00 0E 01 0F 11 0F 00
98:10 10 16 19 11 11 1E 00
99:00 00 0E 10 10 11 0E 00
100:01 01 0D 13 11 11 0F 00
101:00 00 0E 11 1F 10 0E 00
102:06 09 08 1C 08 08 08 00
103:00 00 0F 11 11 0F 01 0E
104:10 10 16 19 11 11 11 00
105:04 00 0C 04 04 04 0E 00
106:02 00 06 02 02 02 12 0C
107:10 10 12 14 18 14 12 00
108:0C 04 04 04 04 04 0E 00
109:00 00 1A 15 15 11 11 00
110:00 00 16 19 11 11 11 00
111:00 00 0E 11 11 11 0E 00
112:00 00 1E 11 11 1E 10 10
113:00 00 0F 11 11 0F 01 01
114:00 00 16 19 10 10 10 00
115:00 00 0F 10 0E 01 1E 00
116:08 08 1C 08 08 09 06 00
117:00 00 11 11 11 13 0D 00
118:00 00 11 11 11 0A 04 00
119:00 00 11 11 15 15 0A 00
120:00 00 11 0A 04 0A 11 00
121:00 00 11 11 11 0F 01 0E
122:00 00 1F 02 04 08 1F 00
123:02 04 04 08 04 04 02 00
124:04 04 04 04 04 04 04 00
125:08 04 04 02 04 04 08 00
126:00 00 08 15 02 00 00 00
"""

GLYPH_W = 5
GLYPH_H = 8
ADVANCE = 6
LINE_H = 10


def _parse() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for line in _TABLE.strip().splitlines():
        code, rows = line.split(":")
        out[chr(int(code))] = [int(r, 16) for r in rows.split()]
    return out


class PixelFont:
    def __init__(self) -> None:
        self.glyphs: dict[str, pygame.Surface] = {}
        for ch, rows in _parse().items():
            s = pygame.Surface((GLYPH_W, GLYPH_H), pygame.SRCALPHA)
            for y, bits in enumerate(rows):
                for x in range(GLYPH_W):
                    if bits & (0x10 >> x):
                        s.set_at((x, y), (255, 255, 255, 255))
            self.glyphs[ch] = s
        self._cache: dict[tuple, pygame.Surface] = {}
        self.scale = 1       # set from accessibility settings (1 or 2)

    def width(self, text: str, scale: int | None = None) -> int:
        sc = scale or self.scale
        return max(0, len(text) * ADVANCE - 1) * sc

    def line_height(self, scale: int | None = None) -> int:
        return LINE_H * (scale or self.scale)

    def render(self, text: str, color=(255, 255, 255), outline=None, scale: int | None = None) -> pygame.Surface:
        sc = scale or self.scale
        key = (text, tuple(color), tuple(outline) if outline else None, sc)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        pad = 1 if outline else 0
        w = max(1, self.width(text, 1))
        base = pygame.Surface((w + pad * 2, GLYPH_H + pad * 2), pygame.SRCALPHA)
        x = pad
        for ch in text:
            g = self.glyphs.get(ch, self.glyphs["?"])
            if outline:
                tint = g.copy()
                tint.fill((*outline, 255), special_flags=pygame.BLEND_RGBA_MULT)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                    base.blit(tint, (x + dx, pad + dy))
            x += ADVANCE
        x = pad
        for ch in text:
            g = self.glyphs.get(ch, self.glyphs["?"]).copy()
            g.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
            base.blit(g, (x, pad))
            x += ADVANCE
        if sc != 1:
            base = pygame.transform.scale(base, (base.get_width() * sc, base.get_height() * sc))
        if len(self._cache) > 3000:
            self._cache.clear()
        self._cache[key] = base
        return base

    def draw(self, surf: pygame.Surface, text: str, pos, color=(255, 255, 255), outline=(0, 0, 0),
             anchor: str = "topleft", scale: int | None = None) -> pygame.Rect:
        img = self.render(text, color, outline, scale)
        r = img.get_rect()
        setattr(r, anchor, (int(pos[0]), int(pos[1])))
        surf.blit(img, r)
        return r

    def wrap(self, text: str, max_w: int, scale: int | None = None) -> list[str]:
        lines: list[str] = []
        for para in text.split("\n"):
            cur = ""
            for word in para.split(" "):
                trial = f"{cur} {word}".strip() if cur else word
                if self.width(trial, scale) <= max_w or not cur:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = word
            lines.append(cur)
        return lines

    def draw_wrapped(self, surf: pygame.Surface, text: str, rect: pygame.Rect, color=(255, 255, 255),
                     outline=(0, 0, 0), scale: int | None = None, max_lines: int | None = None) -> int:
        y = rect.y
        lines = self.wrap(text, rect.w, scale)
        if max_lines:
            lines = lines[:max_lines]
        for ln in lines:
            self.draw(surf, ln, (rect.x, y), color, outline, scale=scale)
            y += self.line_height(scale)
        return y


_font: PixelFont | None = None


def get_font() -> PixelFont:
    global _font
    if _font is None:
        _font = PixelFont()
    return _font
