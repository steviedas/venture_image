import os
from PIL import Image, ImageFile
from pillow_heif import register_heif_opener

def convert_and_remove_images(path_to_process, output_path):
    """
    Converts all supported image files in a given directory to .jpeg format,
    saves them to a specified output directory, and then deletes the original
    files upon successful conversion.

    Args:
        path_to_process (str): The path to the directory containing image files.
        output_path (str): The path to the directory where the converted .jpeg files
                           will be saved.
    """
    # Allow Pillow to load truncated images. This may result in incomplete images.
    ImageFile.LOAD_TRUNCATED_IMAGES = True

    # Register HEIF opener for .heic/.heif files
    register_heif_opener()

    # Create the output directory if it doesn't exist
    if not os.path.exists(output_path):
        os.makedirs(output_path)
        print(f"Created output directory: {output_path}")

    # Check if the input path exists
    if not os.path.exists(path_to_process):
        print(f"Error: The specified input path does not exist: {path_to_process}")
        return

    # Process each item in the input directory
    for filename in os.listdir(path_to_process):
        input_file_path = os.path.join(path_to_process, filename)

        # Skip directories
        if os.path.isdir(input_file_path):
            continue

        try:
            # Open the image file. Pillow will try to identify the format.
            with Image.open(input_file_path) as img:
                print(f"Processing '{filename}' (format: {img.format}, mode: {img.mode})...")

                # Define the output JPEG filename and path
                base_filename = os.path.splitext(filename)[0]
                jpeg_filename = f"{base_filename}.jpeg"
                jpeg_file_path = os.path.join(output_path, jpeg_filename)

                # JPEG does not support transparency. If the original image has an alpha channel
                # (e.g., PNG), convert it to RGB mode.
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                    print(f"  Note: Converted image mode to 'RGB' for JPEG compatibility.")
                
                # Save the image as a JPEG file
                img.save(jpeg_file_path, "JPEG", quality=90)
                print(f"  Successfully converted to: '{jpeg_filename}'")
                
                # --- NEW STEP: Delete the original file ---
                os.remove(input_file_path)
                print(f"  Original file deleted: '{filename}'")

        except Exception as e:
            # Pillow throws an exception if the file is not a supported image type or is unrecoverable
            print(f"  Skipping '{filename}': Could not open or convert. Error: {e}")

# --- Example Usage ---
if __name__ == "__main__":
    # Define your input and output paths
    # WARNING: This program will DELETE the original files after conversion.
    # Make sure you have backups or are working with a copy of your files.
    input_folder = "C:/Users/stevi/Desktop/Unprocessed Photos"
    output_folder = "C:/Users/stevi/Desktop/Converted_JPEGs"

    # Call the conversion function
    convert_and_remove_images(input_folder, output_folder)
