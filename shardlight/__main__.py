"""Command line entry:  python -m shardlight [--mode ID] [--slot N] [--seed S] [--no-audio] ...

pygbag's boot script awaits ``main()`` as a coroutine, so it must define ``async def main``,
on all platforms.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys


async def main(argv: list[str] | None = None) -> int:
    try:
        return await _main(argv)
    except BaseException:
        _report_fatal()
        raise


def _report_fatal() -> None:
    """Report a fatal error: to the browser console and, in the browser, on the page."""
    try:
        import traceback

        text = traceback.format_exc()
    except Exception:
        text = "unknown error"
    try:
        import js  # type: ignore[import-not-found]  # provided by pygbag

        js.console.error("[shardlight] FATAL\n" + text)
    except Exception:
        pass
    try:
        sys.stderr.write(text + "\n")
    except Exception:
        pass
    _show_error_page(text)


def _show_error_page(text: str) -> None:
    """Put the error on the page itself, so a broken build is obvious without devtools."""
    try:
        import js  # type: ignore[import-not-found]

        doc = js.document
        panel = doc.getElementById("shardlight-error")
        if panel is None:
            panel = doc.createElement("pre")
            panel.id = "shardlight-error"
            style = panel.style
            style.position = "fixed"
            style.left = "0"
            style.top = "0"
            style.right = "0"
            style.bottom = "0"
            style.zIndex = "9999"
            style.margin = "0"
            style.padding = "16px"
            style.overflow = "auto"
            style.background = "#14060a"
            style.color = "#ffb4a8"
            style.font = "13px/1.5 ui-monospace, monospace"
            style.whiteSpace = "pre-wrap"
            doc.body.appendChild(panel)
        panel.textContent = "SHARDLIGHT failed to start\n\n" + text
    except Exception:
        pass
    try:
        sys.stderr.write(text + "\n")
    except Exception:
        pass


def _log_browser_env() -> None:
    """Report what the browser build's pygame actually provides.

    The wasm build ships a reduced pygame, so the console needs to say which parts
    of it exist before anything else breaks.
    """
    try:
        import pygame

        ver = getattr(pygame, "ver", "?")
        parts = [
            f"pygame {ver}",
            f"SDL {getattr(pygame, 'get_sdl_version', lambda: '?')()}",
            f"Vector2={hasattr(pygame, 'Vector2')}",
            f"math.Vector2={hasattr(getattr(pygame, 'math', None), 'Vector2')}",
            f"SCALED={hasattr(pygame, 'SCALED')}",
            f"mixer={hasattr(pygame, 'mixer')}",
            f"font={hasattr(pygame, 'font')}",
            f"file={getattr(pygame, '__file__', 'none')}",
        ]
        msg = "[shardlight] env: " + " ".join(parts)
    except Exception as exc:
        msg = f"[shardlight] env probe failed: {exc}"
    try:
        import js  # type: ignore[import-not-found]

        js.console.log(msg)
    except Exception:
        print(msg)


async def _main(argv: list[str] | None = None) -> int:
    try:
        import js  # type: ignore[import-not-found]  # provided by pygbag

        js.console.log("[shardlight] boot: main() reached")
    except Exception:
        pass
    if sys.platform == "emscripten":
        _log_browser_env()
    ap = argparse.ArgumentParser(prog="shardlight", description="SHARDLIGHT - eight shards, one lens")
    ap.add_argument("--mode", help="jump straight into a shard (dev/testing), e.g. cinder")
    ap.add_argument("--slot", type=int, default=None, help="save slot (0-2) to load or create for --mode")
    ap.add_argument("--seed", type=int, default=None, help="deterministic seed for procedural content")
    ap.add_argument("--no-audio", action="store_true", help="run without sound")
    ap.add_argument("--headless", action="store_true", help="no window (smoke test); use with --frames")
    ap.add_argument("--frames", type=int, default=None, help="exit after N rendered frames")
    ap.add_argument("--admin-token", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--screenshot", help="save a screenshot to this path when exiting")
    ap.add_argument("--debug", action="store_true", help="verbose logging and FPS overlay")
    args = ap.parse_args(argv)

    if args.headless:
        import os

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    from .core import log

    log.setup(logging.DEBUG if args.debug else logging.INFO)

    from .core.app import App
    from .hub.title import TitleScene
    from .core.admin import verify_token, resolve_admin_token

    if sys.platform == "emscripten":
        # pygbag/WASM rule: give the browser one frame (canvas size + media gesture)
        # before SDL creates its surface, otherwise the window never paints.
        await asyncio.sleep(0)

    app = App(headless=args.headless, seed=args.seed, audio=not args.no_audio)
    app.debug = args.debug
    app.admin = verify_token(args.admin_token) or verify_token(resolve_admin_token())
    app.screenshot_on_exit = args.screenshot
    from .core import log as _log

    _log.get("main").info("shardlight starting (platform=%s)", sys.platform)
    try:
        if args.mode:
            slot = 0 if args.slot is None else args.slot
            if not (app.saves.exists(slot) and app.load_game(slot)):
                app.new_game(slot)
            app.scenes.reset_to(TitleScene(app), fade=False)
            app.scenes.process(0)
            if not app.enter_mode(args.mode):
                print(f"mode {args.mode!r} is not available", file=sys.stderr)
                return 2
        else:
            app.scenes.reset_to(TitleScene(app), fade=False)
            app.scenes.process(0)
        if sys.platform == "emscripten":
            await app.run_web()
        else:
            app.run(max_frames=args.frames)
    except KeyboardInterrupt:
        pass
    except Exception:
        _log.get("main").exception("fatal error while running the game")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
