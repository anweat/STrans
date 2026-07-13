"""Continuously retain a bounded local recording ring for one sandtable RTSP camera."""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.camera_hub import CameraHub


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "data" / "recordings"


def build_ffmpeg_command(
    ffmpeg: str,
    source: str,
    output_pattern: Path,
    segment_seconds: int,
    max_segments: int,
) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-segment_wrap",
        str(max_segments),
        "-reset_timestamps",
        "1",
        "-y",
        str(output_pattern),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record one sandtable RTSP stream into a bounded MKV segment ring.")
    parser.add_argument("--camera-id", default="live1", help="Configured sandtable camera ID (default: live1).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--segment-seconds", type=int, default=300, help="Length of each segment (default: 300 seconds).")
    parser.add_argument("--max-segments", type=int, default=24, help="Maximum retained segments (default: 24, about two hours).")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.segment_seconds < 30 or args.max_segments < 2:
        raise SystemExit("segment-seconds must be at least 30 and max-segments at least 2.")
    if not shutil.which(args.ffmpeg) and not Path(args.ffmpeg).exists():
        raise SystemExit("ffmpeg was not found. Install it or pass --ffmpeg with its executable path.")

    hub = CameraHub()
    try:
        camera = hub.get_source(args.camera_id)
    except KeyError as error:
        raise SystemExit(f"Unknown camera ID: {args.camera_id}") from error
    if camera.type != "sandtable":
        raise SystemExit(f"Camera {args.camera_id} is not a sandtable RTSP source.")

    output_dir = args.output_dir / args.camera_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / f"{args.camera_id}_%03d.mkv"
    keep_running = True

    def stop(_signal: int, _frame: object) -> None:
        nonlocal keep_running
        keep_running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"Recording {args.camera_id} into {output_dir}; retaining {args.max_segments} segments.", flush=True)

    while keep_running:
        command = build_ffmpeg_command(args.ffmpeg, camera.stream_url, output_pattern, args.segment_seconds, args.max_segments)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while keep_running and process.poll() is None:
            time.sleep(1)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if keep_running:
            print(f"Recorder for {args.camera_id} reconnecting in 5 seconds.", flush=True)
            time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
