"""Command line entry:  python -m shardlight [--mode ID] [--slot N] [--seed S] [--no-audio] ..."""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
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

    app = App(headless=args.headless, seed=args.seed, audio=not args.no_audio)
    app.debug = args.debug
    from .core.admin import verify_token, resolve_admin_token
    app.admin = verify_token(args.admin_token) or verify_token(resolve_admin_token())
    app.screenshot_on_exit = args.screenshot
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
            app.run_web()
        else:
            app.run(max_frames=args.frames)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
