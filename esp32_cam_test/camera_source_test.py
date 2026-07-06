import argparse
import time
from pathlib import Path

import cv2


def parse_source(value: str):
    try:
        return int(value)
    except ValueError:
        return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Test a USB camera, phone IP camera, or ESP32-CAM stream.")
    parser.add_argument("--source", default="0", help="Camera index or stream URL.")
    parser.add_argument("--seconds", type=float, default=10.0, help="Test duration in seconds.")
    parser.add_argument("--out", default="camera_source_snapshot.jpg", help="Output snapshot path.")
    parser.add_argument("--show", action="store_true", help="Show live preview window.")
    args = parser.parse_args()

    source = parse_source(args.source)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"ERROR: cannot open camera source: {args.source}")
        return 1

    start = time.time()
    frames = 0
    last_frame = None

    while time.time() - start < args.seconds:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("WARN: frame read failed")
            time.sleep(0.1)
            continue

        frames += 1
        last_frame = frame

        if args.show:
            cv2.imshow("Camera source test", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    if args.show:
        cv2.destroyAllWindows()

    elapsed = max(time.time() - start, 0.001)
    if last_frame is None:
        print("ERROR: source opened but no frames were received")
        return 2

    out_path = Path(args.out)
    cv2.imwrite(str(out_path), last_frame)
    height, width = last_frame.shape[:2]
    print(f"OK: received {frames} frames in {elapsed:.2f}s")
    print(f"Resolution: {width}x{height}")
    print(f"Approx FPS: {frames / elapsed:.2f}")
    print(f"Snapshot: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
