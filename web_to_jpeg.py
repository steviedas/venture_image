#!/usr/bin/env python3
"""
Render a page (Playwright), extract image URLs (lazy-load friendly),
download them, convert to high-quality JPEG, and save to OUTPUT_PATH/<last-url-segment>.

Edit ADDRESS_PATH and OUTPUT_PATH below, then run this file.
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
from pathlib import Path
from typing import Tuple
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ====== EDIT THESE ======
ADDRESS_PATH = "https://www.behance.net/gallery/22460269/Emily"
OUTPUT_PATH  = r"C:\Users\stevi\Desktop\jpeg_downloads"
MAX_IMAGES   = None     # e.g. 50 or None for all
SCROLL_STEPS = 18       # how many times to scroll to load lazy content
SCROLL_PAUSE = 1.0      # seconds between scrolls
# ========================


# ----- lightweight coloured logger -----
# Set NO_COLOR=1 to disable colours
_ENABLE_COLOR = os.environ.get("NO_COLOR", "").lower() not in ("1", "true", "yes")
try:
    if os.name == "nt" and _ENABLE_COLOR:
        import colorama  # type: ignore
        colorama.just_fix_windows_console()
except Exception:
    pass

def _c(code: str) -> str:
    return code if _ENABLE_COLOR else ""

RESET = _c("\033[0m")
RED   = _c("\033[31m")
GREEN = _c("\033[32m")
YELLOW= _c("\033[33m")

def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")

def log_ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}" if _ENABLE_COLOR else f"[OK] {msg}")

def log_warn(msg: str) -> None:
    text = f"{YELLOW}[WARN]{RESET} {msg}" if _ENABLE_COLOR else f"[WARN] {msg}"
    print(text, file=sys.stderr)

def log_error(msg: str) -> None:
    text = f"{RED}[ERROR]{RESET} {msg}" if _ENABLE_COLOR else f"[ERROR] {msg}"
    print(text, file=sys.stderr)
# ---------------------------------------


# Browser-y headers for image fetches
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": ADDRESS_PATH,
}


def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3, connect=3, read=3, backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": HEADERS["User-Agent"]})
    return s


def to_jpeg(img: Image.Image, bg_rgb: Tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Flatten transparency + ensure EXIF orientation is respected."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, bg_rgb)
        bg.paste(rgba, mask=rgba.split()[3])  # alpha
        return ImageOps.exif_transpose(bg)
    return ImageOps.exif_transpose(img.convert("RGB"))


def sanitize_stem(name: str) -> str:
    stem = Path(name).stem or "image"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:200]


def pick_filename_from_url(url: str) -> str:
    name = Path(urlparse(url).path).name or "image"
    return f"{sanitize_stem(name)}.jpg"


def extract_image_urls(html: str, base_url: str) -> list[str]:
    """
    Grab image URLs from many places:
      - <img src>, <img data-src>, <img data-original>, etc.
      - <source srcset> and data-* variants
      - link[rel=preload][as=image]
      - inline CSS background-image: url(...)
      - regex sweep for common image URLs (png/jpg/jpeg/webp)
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    def add(u: str | None):
        if u:
            urls.append(urljoin(base_url, u))

    # <img ...>
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-hires", "data-zoom", "data-srcset"):
            val = img.get(attr)
            if not val:
                continue
            if attr.endswith("srcset"):
                for item in [i.strip() for i in val.split(",") if i.strip()]:
                    add(item.split()[0])
            else:
                add(val)

    # <source ...>
    for src in soup.find_all("source"):
        for attr in ("srcset", "data-srcset"):
            val = src.get(attr)
            if not val:
                continue
            for item in [i.strip() for i in val.split(",") if i.strip()]:
                add(item.split()[0])

    # <link rel="preload" as="image" href="...">
    for ln in soup.find_all("link", rel=lambda v: v and "preload" in v):
        if (ln.get("as") or "").lower() == "image":
            add(ln.get("href"))

    # inline CSS url(...) patterns
    for el in soup.find_all(style=True):
        style = el["style"]
        for m in re.finditer(r'url\((["\']?)(.+?)\1\)', style):
            add(m.group(2))

    # Final regex sweep (e.g., inside scripts)
    for m in re.finditer(r'https?://[^\s"\'()]+?\.(?:png|jpg|jpeg|webp)(?:\?[^\s"\'()]*)?', html, flags=re.I):
        add(m.group(0))

    # Dedup while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        key = u.split("#", 1)[0]
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def render_html(url: str, scroll_steps: int, scroll_pause: float) -> str:
    """
    Render with Playwright and scroll to trigger lazy load.
    Uses safe scrollingElement/documentElement fallbacks and waits for <body>.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="en-GB",
            java_script_enabled=True,
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        page.set_extra_http_headers({"Accept-Language": "en-GB,en;q=0.9"})
        page.goto(url, wait_until="load", timeout=60000)

        # Ensure body exists
        page.wait_for_function("() => !!document.body", timeout=15000)
        # First image often triggers further lazy loads
        try:
            page.wait_for_selector("img", state="attached", timeout=5000)
        except Exception:
            pass

        # Helpers
        def page_height() -> int:
            return page.evaluate(
                """() => {
                    const el = document.scrollingElement || document.documentElement || document.body;
                    return el ? el.scrollHeight : 0;
                }"""
            )

        def scroll_once() -> None:
            page.evaluate(
                """() => {
                    const el = document.scrollingElement || document.documentElement || document.body;
                    if (!el) return;
                    const y = (window.innerHeight || 800);
                    el.scrollBy(0, y);
                }"""
            )

        last_h = 0
        steps = max(1, int(scroll_steps))
        for _ in range(steps):
            h1 = page_height()
            if h1 == 0:
                page.keyboard.press("PageDown")
            else:
                scroll_once()
            page.wait_for_timeout(int(scroll_pause * 1000))
            h2 = page_height()
            if h2 <= h1 and h1 == last_h:
                break
            last_h = h1

        page.wait_for_timeout(1000)
        html = page.content()
        browser.close()
        return html


def download_image(session: requests.Session, url: str) -> bytes:
    r = session.get(url, headers=HEADERS, timeout=30, stream=True)
    r.raise_for_status()
    return r.content


def last_segment_of_url(u: str) -> str:
    """
    Get the last path segment of the URL, URL-decoded, safe for a folder name.
    e.g., https://.../gallery/197402805/Paulina-Pt-01 -> "Paulina-Pt-01"
    """
    path = urlparse(u).path.rstrip("/")
    segment = path.split("/")[-1] or "download"
    segment = unquote(segment)  # decode %20, etc.
    # Clean it for filesystem safety
    segment = re.sub(r"[\\/:*?\"<>|]+", "_", segment).strip()
    return segment or "download"


def main() -> None:
    # Build destination as OUTPUT_PATH / <last-url-segment>
    base_out = Path(OUTPUT_PATH).expanduser().resolve()
    subdir = last_segment_of_url(ADDRESS_PATH)
    out_root = (base_out / subdir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    log_info(f"Rendering page: {ADDRESS_PATH}")
    try:
        html = render_html(ADDRESS_PATH, SCROLL_STEPS, SCROLL_PAUSE)
    except Exception as e:
        log_error(f"Playwright render failed: {e}")
        sys.exit(1)

    urls = extract_image_urls(html, ADDRESS_PATH)
    if MAX_IMAGES is not None:
        urls = urls[: int(MAX_IMAGES)]
    if not urls:
        log_warn("No images found after rendering.")
        return

    log_info(f"Saving into: {out_root}")
    log_info(f"Found {len(urls)} image(s). Downloading + converting to JPEG...")

    session = build_session()
    converted = 0

    for url in urls:
        try:
            raw = download_image(session, url)
            with Image.open(io.BytesIO(raw)) as im:
                if getattr(im, "is_animated", False):
                    im.seek(0)

                exif = getattr(im, "info", {}).get("exif")
                icc  = getattr(im, "info", {}).get("icc_profile")

                rgb = to_jpeg(im, (255, 255, 255))

                dest_name = pick_filename_from_url(url)
                dest = out_root / dest_name
                suffix = 1
                while dest.exists():
                    dest = out_root / f"{Path(dest_name).stem}_{suffix}.jpg"
                    suffix += 1

                save_kwargs = dict(
                    format="JPEG",
                    quality=95,
                    subsampling=0,   # 4:4:4
                    optimize=True,
                    progressive=True,
                )
                if exif:
                    save_kwargs["exif"] = exif
                if icc:
                    save_kwargs["icc_profile"] = icc

                rgb.save(dest, **save_kwargs)

            converted += 1
            log_ok(f"{url} -> {dest}")
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            log_warn(f"{url}: HTTP {status}")
        except Exception as e:
            log_error(f"{url}: {e}")

    log_info(f"Done. Converted {converted} image(s) to JPEG in: {out_root}")


if __name__ == "__main__":
    main()
