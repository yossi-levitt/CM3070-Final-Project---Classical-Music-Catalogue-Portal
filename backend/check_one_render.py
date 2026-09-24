"""Render a single MEI file with verovio and exit 0/1. Run as its own process
so a native crash on one file cannot take down a batch sweep of many files.
"""
import sys

import verovio


def main() -> int:
    path = sys.argv[1]
    tk = verovio.toolkit()
    try:
        if not tk.loadFile(path):
            return 1
        svg = tk.renderToSVG(1)
        if svg and "<svg" in svg and len(svg) > 200:
            return 0
        return 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
