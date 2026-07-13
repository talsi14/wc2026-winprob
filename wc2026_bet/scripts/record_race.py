"""Record one of the bar-chart-race overlays from the shareable page to an MP4.

Drives the real page in headless Chromium (so Hebrew/RTL + visuals match the
site exactly), records the autoplaying race, then transcodes to H.264 MP4 for
WhatsApp. Usage:  python3 scripts/record_race.py --race p1 --out /path/out.mp4
"""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAGE = "file://" + os.path.join(REPO, "friends_bet", "report", "index.html")

# Flatten the modal so the recording is just the chart on white (no dark backdrop).
FLATTEN_CSS = """
  #raceModal{background:#fff !important; padding:0 !important;}
  .racecard{box-shadow:none !important; border-radius:0 !important; max-height:none !important;
            width:100% !important; height:100vh !important; overflow:hidden !important;
            display:flex !important; flex-direction:column !important; justify-content:center !important;}
  .raceclose{display:none !important;}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", default="p1", choices=["p1", "leaderboard", "title"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="race_")
    size = {"width": args.width, "height": args.height}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=size, device_scale_factor=2,
                                  record_video_dir=tmp, record_video_size=size)
        page = ctx.new_page()
        page.goto(PAGE)
        page.add_style_tag(content=FLATTEN_CSS)
        page.wait_for_timeout(400)
        page.click(f'[data-race="{args.race}"]')
        # Autoplays on open; wait until the scrubber reports the end (clock==total).
        try:
            page.wait_for_function(
                "() => { const s=document.getElementById('raceScrub'); return s && s.value==='1000'; }",
                timeout=120000)
        except Exception:
            print("warning: did not detect clean end; capturing what played")
        page.wait_for_timeout(600)
        video = page.video
        ctx.close()
        webm = video.path()
        browser.close()

    print("captured:", webm)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-i", webm,
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                    "-r", "30", "-movflags", "+faststart", args.out], check=True)
    print("wrote:", args.out)


if __name__ == "__main__":
    main()
