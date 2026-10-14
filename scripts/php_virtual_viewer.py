#!/usr/bin/env python3
"""Send keys to the sole MuJoCo window on an isolated X display, or capture it.

Example: python scripts/php_virtual_viewer.py --display :99 tap 8 --count 9
"""

import argparse
import os
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default=":99", help="isolated X server (default: :99)")
    commands = parser.add_subparsers(dest="action", required=True)
    tap = commands.add_parser("tap", help="press and release a key")
    tap.add_argument("key", help="X11 keysym, e.g. 8, 9, y, BackSpace")
    tap.add_argument("--count", type=int, default=1)
    tap.add_argument("--interval", type=float, default=0.35)
    hold = commands.add_parser("hold", help="hold a direction key for seconds")
    hold.add_argument("key", help="X11 keysym, e.g. w")
    hold.add_argument("seconds", type=float)
    shot = commands.add_parser("screenshot", help="save the MuJoCo window")
    shot.add_argument("path", type=Path)
    args = parser.parse_args()

    if args.display in (":0", ":1"):
        parser.error("use an isolated X display, not the primary desktop")
    if args.action == "tap" and (args.count < 1 or args.interval < 0.15):
        parser.error("tap needs count >= 1 and interval >= 0.15 s")
    if args.action == "hold" and args.seconds <= 0:
        parser.error("hold needs a positive duration")

    os.environ["DISPLAY"] = args.display
    from Xlib import X, XK, display
    from Xlib.ext import xtest

    conn = display.Display()
    root = conn.screen().root
    viewers = [w for w in root.query_tree().children if "MuJoCo" in (w.get_wm_name() or "")]
    if len(viewers) != 1:
        parser.error(f"expected one MuJoCo window on {args.display}, found {len(viewers)}")
    viewer = viewers[0]

    if args.action == "screenshot":
        from PIL import ImageGrab

        geometry = viewer.get_geometry()
        position = root.translate_coords(viewer, 0, 0)
        args.path.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(
            bbox=(position.x, position.y, position.x + geometry.width, position.y + geometry.height),
            xdisplay=args.display,
        ).save(args.path)
        print(args.path)
        return

    keycode = conn.keysym_to_keycode(XK.string_to_keysym(args.key))
    if keycode == 0:
        parser.error(f"unknown X11 keysym: {args.key}")
    viewer.set_input_focus(X.RevertToParent, X.CurrentTime)
    conn.sync()
    count = args.count if args.action == "tap" else 1
    for _ in range(count):
        xtest.fake_input(conn, X.KeyPress, keycode)
        conn.sync()
        try:
            time.sleep(0.12 if args.action == "tap" else args.seconds)
        finally:
            xtest.fake_input(conn, X.KeyRelease, keycode)
            conn.sync()
        if args.action == "tap":
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
