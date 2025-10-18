# src/vi_app/modules/cleanup/strategies/by_location.py
from __future__ import annotations

from pathlib import Path

from geopy.geocoders import Nominatim
from PIL import ExifTags, Image

from vi_app.core.paths import sanitize_filename
from vi_app.core.progress import ProgressReporter

from .base import SortStrategyBase


class SortByLocationStrategy(SortStrategyBase):
    """
    Sort images into dst_root/City_Country/filename (falls back to Country or 'Unknown').
    """

    # Simple in-class cache to avoid decorator complications with methods
    _geocode_cache: dict[tuple[float, float], tuple[str | None, str | None]] = {}

    def run(
        self,
        src_root: Path,
        dst_root: Path | None,
        reporter: ProgressReporter | None = None,
    ) -> list[tuple[Path, Path]]:
        src_root = src_root.resolve()
        dst_root = (dst_root or src_root).resolve()

        moves: list[tuple[Path, Path]] = []
        for src in self.iter_images(src_root, reporter=reporter):
            gps = self._get_exif_gps(src)
            city = country = None
            if gps:
                lat = round(gps[0], 4)
                lon = round(gps[1], 4)
                city, country = self._reverse_geocode(lat, lon)

            if city and country:
                folder = f"{city}_{country}"
            elif country:
                folder = country
            else:
                folder = "Unknown"

            dst = dst_root / sanitize_filename(folder) / sanitize_filename(src.name)
            moves.append((src, dst))

        if reporter:
            reporter.start("select", total=len(moves), text="Planning moves…")
            reporter.end("select")
        return moves

    # ---- helpers ----
    @staticmethod
    def _ratio_to_float(x):
        try:
            return float(x)
        except Exception:
            num, den = x
            return float(num) / float(den)

    @classmethod
    def _get_exif_gps(cls, p: Path) -> tuple[float, float] | None:
        try:
            with Image.open(p) as im:
                exif = im.getexif() or {}
                if not exif:
                    return None
                tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
                gps = tags.get("GPSInfo")
                if not gps:
                    return None
                inv = {v: k for k, v in ExifTags.GPSTAGS.items()}
                lat = gps.get(inv.get("GPSLatitude"))
                lat_ref = gps.get(inv.get("GPSLatitudeRef"))
                lon = gps.get(inv.get("GPSLongitude"))
                lon_ref = gps.get(inv.get("GPSLongitudeRef"))
                if not (lat and lon and lat_ref and lon_ref):
                    return None

                def _dms_to_deg(dms):
                    d, m, s = dms
                    return (
                        cls._ratio_to_float(d)
                        + cls._ratio_to_float(m) / 60.0
                        + cls._ratio_to_float(s) / 3600.0
                    )

                lat_deg = _dms_to_deg(lat)
                lon_deg = _dms_to_deg(lon)
                if isinstance(lat_ref, bytes):
                    lat_ref = lat_ref.decode(errors="ignore")
                if isinstance(lon_ref, bytes):
                    lon_ref = lon_ref.decode(errors="ignore")
                if str(lat_ref).upper().startswith("S"):
                    lat_deg = -lat_deg
                if str(lon_ref).upper().startswith("W"):
                    lon_deg = -lon_deg
                return lat_deg, lon_deg
        except Exception:
            return None
        return None

    @classmethod
    def _reverse_geocode(cls, lat: float, lon: float) -> tuple[str | None, str | None]:
        key = (lat, lon)
        if key in cls._geocode_cache:
            return cls._geocode_cache[key]
        geocoder = Nominatim(user_agent="venture-image", timeout=10)
        try:
            loc = geocoder.reverse((lat, lon), language="en")
            if not loc or not loc.raw:
                result = (None, None)
            else:
                raw = loc.raw.get("address", {})
                city = (
                    raw.get("city")
                    or raw.get("town")
                    or raw.get("village")
                    or raw.get("hamlet")
                    or raw.get("suburb")
                    or raw.get("county")
                )
                country = raw.get("country")
                result = (city, country)
        except Exception:
            result = (None, None)
        cls._geocode_cache[key] = result
        return result
