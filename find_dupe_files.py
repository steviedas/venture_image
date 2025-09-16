# find_dupe_files.py

import os

def find_duplicate_files(path_to_process):
    """
    This function searches for files with "_dupe" in their name within a given directory
    and its subdirectories.

    Args:
        path_to_process (str): The path to the directory to be searched.

    Returns:
        list: A list of full paths to the files that contain "_dupe" in their name.
              Returns an empty list if the path is not a valid directory or if no such files are found.
    """
    duplicate_files = []

    if not os.path.isdir(path_to_process):
        print(f"Error: The provided path '{path_to_process}' is not a valid directory.")
        return duplicate_files

    for root, _, files in os.walk(path_to_process):
        for file in files:
            if "_dupe" in file.lower():
                full_path = os.path.join(root, file)
                duplicate_files.append(full_path)

    return duplicate_files

path_to_process = r"C:\Users\stevi\Desktop\Organised Photos" 

if __name__ == "__main__":
    print(f"Scanning directory: {path_to_process}")
    
    found_files = find_duplicate_files(path_to_process)

    if found_files:
        print("\nFound the following files with '_dupe' in the name:")
        for file_path in found_files:
            print(file_path)
    else:
        print("\nNo files with '_dupe' in the name were found.")
