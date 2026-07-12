import argparse
import json
from pathlib import Path

import cv2

from app import infer_image


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local YOLOv11s-VisDrone + ByteTrack + HyperLPR3 demo on one image.")
    parser.add_argument("image", help="image path")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=960)
    args = parser.parse_args()

    image_path = Path(args.image)
    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"Cannot read image: {image_path}")

    result = infer_image(image, conf=args.conf, imgsz=args.imgsz)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Annotated image: {Path(__file__).resolve().parent}{result['annotated_image']}")


if __name__ == "__main__":
    main()
