import os
import shutil
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import pillow_heif
import time

# Register HEIC/HEIF support
pillow_heif.register_heif_opener()

# Initialize Nominatim geocoder
geolocator = Nominatim(user_agent="photo_organizer")

# Folder to process
path_to_process = r"C:\Users\stevi\Desktop\Testing"

def get_exif_data(image_path):
    """Extract EXIF data from an image."""
    try:
        img = Image.open(image_path)
        exif_data = img.getexif()
        if not exif_data:
            return {}
        exif = {}
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            exif[tag] = value
        return exif
    except Exception:
        return {}

def get_gps_info(exif):
    """Extract GPS info and convert to decimal coordinates."""
    gps_info = exif.get("GPSInfo")
    if not gps_info or not isinstance(gps_info, dict):
        return None

    gps_data = {}
    for key, value in gps_info.items():
        decoded = GPSTAGS.get(key, key)
        gps_data[decoded] = value

    def convert_to_decimal(coord, ref):
        degrees, minutes, seconds = coord
        decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
        if ref in ['S', 'W']:
            decimal = -decimal
        return decimal

    try:
        lat_values = [float(x) / float(y) for x, y in gps_data['GPSLatitude']]
        lon_values = [float(x) / float(y) for x, y in gps_data['GPSLongitude']]
        lat = convert_to_decimal(lat_values, gps_data['GPSLatitudeRef'])
        lon = convert_to_decimal(lon_values, gps_data['GPSLongitudeRef'])
        return (lat, lon)
    except Exception:
        return None

def reverse_geocode(lat, lon):
    """Convert latitude and longitude to a human-readable location (city + country)."""
    try:
        location = geolocator.reverse((lat, lon), language='en', exactly_one=True, timeout=10)
        if location and location.raw.get('address'):
            address = location.raw['address']
            city = address.get('city') or address.get('town') or address.get('village') or ''
            country = address.get('country') or ''
            if city and country:
                return f"{city}_{country}"
            elif country:
                return country
    except GeocoderTimedOut:
        print("[WARNING] Geocoding timed out. Retrying...")
        time.sleep(1)
        return reverse_geocode(lat, lon)
    except Exception as e:
        print(f"[ERROR] Reverse geocoding failed: {e}")
    return None

def move_photos_by_location(path):
    """Traverse folders, find photos with GPS info, and move them to location-named folders."""
    for root, _, files in os.walk(path):
        for file in files:
            if not file.lower().endswith(('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.heic', '.heif')):
                continue

            file_path = os.path.join(root, file)
            exif = get_exif_data(file_path)
            gps_coords = get_gps_info(exif)

            if gps_coords:
                lat, lon = gps_coords
                location_name = reverse_geocode(lat, lon)

                if location_name:
                    dest_dir = os.path.join(root, location_name)
                    os.makedirs(dest_dir, exist_ok=True)
                    try:
                        shutil.move(file_path, os.path.join(dest_dir, file))
                        print(f"[MOVED] {file_path} -> {dest_dir}")
                    except Exception as e:
                        print(f"[ERROR] Could not move {file_path}: {e}")
            else:
                # Optional: print skipped files
                print(f"[SKIPPED] No GPS data: {file_path}")

if __name__ == "__main__":
    move_photos_by_location(path_to_process)
