#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from typing import Iterable, Tuple

from PIL import Image, ImageOps

# ====== EDIT THESE ======
PATH_TO_PROCESS = r"C:\Users\stevi\Desktop\webp"
OUTPUT_PATH     = r"C:\Users\stevi\Desktop\jpeg"
RECURSIVE       = True
QUALITY         = 100      # we'll clamp to Pillow's practical max (95)
OVERWRITE       = False
BG_COLOR_HEX    = "#FFFFFF"
# ========================


def find_webps(root: Path, recursive: bool) -> Iterable[Path]:
    """Yield .webp files once (case-insensitive, no duplicates)."""
    pattern = "**/*.webp" if recursive else "*.webp"
    # Collect into a set of normalized lowercase paths to avoid duplicates on Windows
    seen: set[str] = set()
    for p in root.glob(pattern) if not recursive else root.rglob("*.webp"):
        if p.is_file():
            key = str(p.resolve()).lower()
            if key not in seen:
                seen.add(key)
                yield p
    # Also catch uppercase .WEBP files not matched by *.webp on some filesystems
    upper_iter = (root.glob("*.WEBP") if not recursive else root.rglob("*.WEBP"))
    for p in upper_iter:
        if p.is_file():
            key = str(p.resolve()).lower()
            if key not in seen:
                seen.add(key)
                yield p


def parse_hex_color(s: str) -> Tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError("BG_COLOR_HEX must be '#RRGGBB' or '#RGB'.")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def to_jpeg(img: Image.Image, bg_rgb: Tuple[int, int, int]) -> Image.Image:
    """Ensure an RGB, non-alpha image ready for JPEG; flatten transparency."""
    # Respect EXIF orientation via exif_transpose() on the *final* image
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, bg_rgb)
        bg.paste(rgba, mask=rgba.split()[3])  # alpha channel
        return ImageOps.exif_transpose(bg)
    return ImageOps.exif_transpose(img.convert("RGB"))


def main() -> None:
    in_root = Path(PATH_TO_PROCESS).expanduser().resolve()
    out_root = Path(OUTPUT_PATH).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    if not in_root.exists() or not in_root.is_dir():
        raise SystemExit(f"Input directory not found: {in_root}")

    bg_rgb = parse_hex_color(BG_COLOR_HEX)
    q = max(1, min(int(QUALITY), 95))  # Pillow sweet spot

    count = 0
    for src in find_webps(in_root, RECURSIVE):
        rel = src.relative_to(in_root)
        dest = (out_root / rel).with_suffix(".jpg")
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not OVERWRITE and dest.exists():
            print(f"[skip] Exists: {dest}")
            continue

        try:
            with Image.open(src) as im:
                # If animated WEBP, take first frame
                if getattr(im, "is_animated", False):
                    im.seek(0)

                # Grab metadata safely
                exif = getattr(im, "info", {}).get("exif")
                icc  = getattr(im, "info", {}).get("icc_profile")

                rgb = to_jpeg(im, bg_rgb)

                save_kwargs = dict(
                    format="JPEG",
                    quality=q,
                    subsampling=0,     # 4:4:4 chroma (best quality)
                    optimize=True,
                    progressive=True,
                )
                if exif:  # only include if bytes present
                    save_kwargs["exif"] = exif
                if icc:   # only include if bytes present
                    save_kwargs["icc_profile"] = icc

                rgb.save(dest, **save_kwargs)

            count += 1
            print(f"[ok] {src} -> {dest}")
        except Exception as e:
            print(f"[error] {src}: {e}")

    print(f"\nDone. Converted {count} files to JPEG in: {out_root}")


if __name__ == "__main__":
    main()
