"""Crop the last digit of the big chapter number (e.g. the 8 of "08") from a chapter-select screenshot.

Only the last digit is kept: the leading 0 is shared by every chapter and would make 08 and 09 look alike.

    python tools/make_chapter_template.py shot.png 3            # chapter 3 is centred in shot.png
    python tools/make_chapter_template.py shot.png 9 --box 1126 92 38 58   # last digit of a side card's number

Writes resource/image/nav_chapter_03.png; rebuild the pipeline afterwards:
    python tools/build_nav_pipeline.py
"""

import argparse
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("chapter", type=int)
    ap.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "W", "H"), default=[333, 92, 38, 58],
                    help="region in 1280x720 coordinates (default: the second digit of the centred card, e.g. the 8 in 08)")
    args = ap.parse_args()
    img = cv2.imdecode(__import__("numpy").fromfile(str(args.image), "uint8"), cv2.IMREAD_COLOR)
    img = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_AREA)
    x, y, w, h = args.box
    out = ROOT / "resource" / "image" / f"nav_chapter_{args.chapter:02d}.png"
    cv2.imwrite(str(out), img[y:y + h, x:x + w])
    print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
