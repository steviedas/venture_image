import os
import re

# Folder to scan for duplicates
path_to_process = r"C:\Users\stevi\Desktop\Organised Photos"

# Regex pattern to match _dupe(number) before the file extension
dupe_pattern = re.compile(r"_dupe\(\d+\)(\.[a-zA-Z0-9]+)$")

def remove_duplicates(path):
    for root, _, files in os.walk(path):
        for file in files:
            if dupe_pattern.search(file):
                full_path = os.path.join(root, file)
                try:
                    os.remove(full_path)
                    print(f"[DELETED] {full_path}")
                except Exception as e:
                    print(f"[ERROR] Could not delete {full_path}: {e}")

if __name__ == "__main__":
    remove_duplicates(path_to_process)
