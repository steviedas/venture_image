import os

# Folder to calculate size for
path_to_process = r"C:\Users\stevi\Desktop\Organised Photos\2019"

def get_folder_size_and_count(path):
    total_size = 0
    file_count = 0  # Initialize a counter for the files
    for root, _, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                total_size += os.path.getsize(file_path)
                file_count += 1  # Increment the counter for each file
            except Exception as e:
                print(f"[ERROR] Could not get size for {file_path}: {e}")
    return total_size, file_count

def format_sizes(size_bytes):
    size_mb = size_bytes / (1024**2)
    size_gb = size_bytes / (1024**3)
    return size_bytes, size_mb, size_gb

if __name__ == "__main__":
    total_bytes, num_files = get_folder_size_and_count(path_to_process)
    bytes_, mb, gb = format_sizes(total_bytes)
    print(f"Folder: {path_to_process}")
    print(f"Number of Files: {num_files}")
    print(f"Total Size: {bytes_} bytes")
    print(f"Total Size: {mb:.2f} MB")
    print(f"Total Size: {gb:.2f} GB")
