import os

def find_matching_paths(path_to_process: str, pattern_to_match: str):
    """
    Search for files or directories within path_to_process whose names 
    contain the given pattern_to_match.

    Args:
        path_to_process (str): The directory path to search in.
        pattern_to_match (str): Substring to search for in filenames/directories.

    Returns:
        list[str]: List of matching file/directory paths.
    """
    matches = []

    for root, dirs, files in os.walk(path_to_process):
        # Check directories
        for d in dirs:
            if pattern_to_match in d:
                matches.append(os.path.join(root, d))

        # Check files
        for f in files:
            if pattern_to_match in f:
                matches.append(os.path.join(root, f))

    return matches


if __name__ == "__main__":
    # Example usage
    path_to_process = r"C:\Users\stevi\Desktop"
    pattern_to_match = "eil"

    results = find_matching_paths(path_to_process, pattern_to_match)
    print("Matches found:")
    for r in results:
        print(r)
