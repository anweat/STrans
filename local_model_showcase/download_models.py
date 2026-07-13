from pathlib import Path
import shutil

import requests


ROOT = Path(__file__).resolve().parent
WEIGHTS = ROOT / "weights"
WEIGHTS.mkdir(exist_ok=True)

VISDRONE_URL = "https://huggingface.co/erbayat/yolov11s-visdrone/resolve/main/yolo11s-visdrone.pt"
VISDRONE_TARGET = WEIGHTS / "yolov11s-visdrone.pt"
FALLBACK_TARGET = WEIGHTS / "yolo11s.pt"


def download_file(url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 1_000_000:
        print(f"[ok] existing {target}")
        return

    print(f"[download] {url}")
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        tmp = target.with_suffix(target.suffix + ".tmp")
        with tmp.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(target)
    print(f"[ok] saved {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")


def download_ultralytics_fallback() -> None:
    if FALLBACK_TARGET.exists() and FALLBACK_TARGET.stat().st_size > 1_000_000:
        print(f"[ok] existing {FALLBACK_TARGET}")
        return

    print("[download] official Ultralytics yolo11s.pt fallback")
    from ultralytics import YOLO

    model = YOLO("yolo11s.pt")
    source = Path(getattr(model, "ckpt_path", "yolo11s.pt"))
    if source.exists():
        shutil.copy2(source, FALLBACK_TARGET)
        if source.resolve().parent == ROOT and source.resolve() != FALLBACK_TARGET.resolve():
            source.unlink(missing_ok=True)
    else:
        cache_hit = next(Path.home().rglob("yolo11s.pt"), None)
        if cache_hit is None:
            raise RuntimeError("Ultralytics downloaded yolo11s.pt but the file was not found.")
        shutil.copy2(cache_hit, FALLBACK_TARGET)
    print(f"[ok] saved {FALLBACK_TARGET}")


if __name__ == "__main__":
    try:
        download_file(VISDRONE_URL, VISDRONE_TARGET)
    except Exception as exc:
        print(f"[warn] yolov11s-visdrone download failed: {exc}")
        print("[warn] will keep the demo runnable with the official yolo11s.pt fallback.")
    download_ultralytics_fallback()
