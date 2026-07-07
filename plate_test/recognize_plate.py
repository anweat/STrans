import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import cv2
import hyperlpr3 as lpr3
import numpy as np
import requests


PLATE_TYPE_NAMES = {
    lpr3.PLATE_TYPE_BLUE: "blue",
    lpr3.PLATE_TYPE_GREEN: "green",
    lpr3.PLATE_TYPE_YELLOW: "yellow",
    lpr3.UNKNOWN: "unknown",
}


def load_image(src: str):
    parsed = urlparse(src)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(src, timeout=30)
        response.raise_for_status()
        data = np.frombuffer(response.content, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    else:
        image = cv2.imread(src)

    if image is None:
        raise ValueError(f"cannot load image: {src}")
    return image


def normalize_result(raw_result):
    normalized = []
    for idx, item in enumerate(raw_result, start=1):
        plate_no, confidence, plate_type, bbox = item
        normalized.append(
            {
                "index": idx,
                "plate_no": str(plate_no),
                "confidence": round(float(confidence), 4),
                "plate_type": PLATE_TYPE_NAMES.get(int(plate_type), str(plate_type)),
                "bbox": [int(v) for v in bbox],
            }
        )
    return normalized


def annotate(image, plates):
    output = image.copy()
    for plate in plates:
        x1, y1, x2, y2 = plate["bbox"]
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 220, 80), 2)
        label = f"#{plate['index']} {plate['confidence']:.2f}"
        cv2.putText(
            output,
            label,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 220, 80),
            2,
            cv2.LINE_AA,
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Test HyperLPR3 license plate recognition on one image.")
    parser.add_argument("--src", required=True, help="Image path or URL.")
    parser.add_argument("--out", default="plate_test_output.jpg", help="Annotated output image path.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path.")
    parser.add_argument(
        "--det-level",
        choices=["low", "high"],
        default="low",
        help="Detector level. high is slower but can catch smaller plates.",
    )
    args = parser.parse_args()

    image = load_image(args.src)
    detect_level = lpr3.DETECT_LEVEL_HIGH if args.det_level == "high" else lpr3.DETECT_LEVEL_LOW
    catcher = lpr3.LicensePlateCatcher(detect_level=detect_level)

    start = time.perf_counter()
    raw_result = catcher(image)
    elapsed_ms = (time.perf_counter() - start) * 1000

    plates = normalize_result(raw_result)
    result = {
        "source": args.src,
        "image_shape": list(image.shape),
        "elapsed_ms": round(elapsed_ms, 2),
        "plate_count": len(plates),
        "plates": plates,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), annotate(image, plates))

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Annotated image: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
