# src/vi_app/modules/sort/strategies/by_location.py
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from geopy.geocoders import Nominatim
from PIL import ExifTags, Image

from vi_app.core.paths import sanitize_filename

IMG_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".heic",
    ".heif",
}


def _iter_images(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            yield p


def _get_exif_gps(p: Path) -> tuple[float, float] | None:
    try:
        with Image.open(p) as im:
            exif = im.getexif() or {}
            if not exif:
                return None
            # Build tag-name map
            tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            gps = tags.get("GPSInfo")
            if not gps:
                return None
            # Decode GPS tags (GPSTAGS index -> name)
            inv = {v: k for k, v in ExifTags.GPSTAGS.items()}
            lat = gps.get(inv.get("GPSLatitude"))
            lat_ref = gps.get(inv.get("GPSLatitudeRef"))
            lon = gps.get(inv.get("GPSLongitude"))
            lon_ref = gps.get(inv.get("GPSLongitudeRef"))
            if not (lat and lon and lat_ref and lon_ref):
                return None

            def _ratio_to_float(x):
                # Pillow may return IFDRational or (num, den) tuples
                try:
                    return float(x)
                except Exception:
                    num, den = x
                    return float(num) / float(den)

            def _dms_to_deg(dms):
                d, m, s = dms
                return (
                    _ratio_to_float(d)
                    + _ratio_to_float(m) / 60.0
                    + _ratio_to_float(s) / 3600.0
                )

            lat_deg = _dms_to_deg(lat)
            lon_deg = _dms_to_deg(lon)
            if isinstance(lat_ref, bytes):
                lat_ref = lat_ref.decode(errors="ignore")
            if isinstance(lon_ref, bytes):
                lon_ref = lon_ref.decode(errors="ignore")
            if lat_ref.upper().startswith("S"):
                lat_deg = -lat_deg
            if lon_ref.upper().startswith("W"):
                lon_deg = -lon_deg
            return lat_deg, lon_deg
    except Exception:
        return None
    return None


@lru_cache(maxsize=4096)
def _reverse_geocode(lat: float, lon: float) -> tuple[str | None, str | None]:
    geocoder = Nominatim(user_agent="venture-image", timeout=10)
    try:
        loc = geocoder.reverse((lat, lon), language="en")
        if not loc or not loc.raw:
            return None, None
        raw = loc.raw.get("address", {})
        # Nominatim uses keys like city/town/village/hamlet; pick first present
        city = (
            raw.get("city")
            or raw.get("town")
            or raw.get("village")
            or raw.get("hamlet")
            or raw.get("suburb")
            or raw.get("county")
        )
        country = raw.get("country")
        return city, country
    except Exception:
        return None, None


def plan(src_root: Path, dst_root: Path | None) -> list[tuple[Path, Path]]:
    """
    Returns list of (src, dst) moves like:
    dst_root/City_Country/filename
    Falls back to Country or 'Unknown' when metadata is incomplete.
    """
    src_root = src_root.resolve()
    dst_root = (dst_root or src_root).resolve()

    moves: list[tuple[Path, Path]] = []
    for src in _iter_images(src_root):
        gps = _get_exif_gps(src)
        city = country = None
        if gps:
            # round to ~11m precision to improve cache hits & privacy
            lat = round(gps[0], 4)
            lon = round(gps[1], 4)
            city, country = _reverse_geocode(lat, lon)

        if city and country:
            folder = f"{city}_{country}"
        elif country:
            folder = country
        else:
            folder = "Unknown"

        dst = dst_root / sanitize_filename(folder) / sanitize_filename(src.name)
        moves.append((src, dst))

    return moves
