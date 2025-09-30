import os
import shutil
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("sorter_log.txt", mode='w'),
        logging.StreamHandler()
    ]
)

def sort_renamed_photos(source_dir, backup_dir):
    logging.info(f"Starting to sort files from '{source_dir}' into '{backup_dir}'...")
    
    unorganized_dir = os.path.join(backup_dir, "_unorganized")
    os.makedirs(unorganized_dir, exist_ok=True)

    success_count = 0
    unorganized_count = 0
    
    files_to_process = [f for f in os.listdir(source_dir) if os.path.isfile(os.path.join(source_dir, f))]
    total_files = len(files_to_process)
    
    for i, filename in enumerate(files_to_process):
        original_path = os.path.join(source_dir, filename)
        
        try:
            date_part = filename.split('_')[0]
            year, month, _ = date_part.split('-')
            
            # Basic validation to ensure year and month are digits
            if not (year.isdigit() and len(year) == 4 and month.isdigit() and len(month) == 2):
                raise ValueError("Filename does not start with a valid YYYY-MM-DD prefix.")

            target_dir = os.path.join(backup_dir, year, month)
            os.makedirs(target_dir, exist_ok=True)
            
            new_path = os.path.join(target_dir, filename)
            
            shutil.move(original_path, new_path)
            logging.info(f"[{i+1}/{total_files}] Moved: {filename} -> {os.path.join(year, month)}")
            success_count += 1
            
        except (ValueError, IndexError) as e:
            logging.warning(f"[{i+1}/{total_files}] Could not parse date from '{filename}'. Moving to _unorganized. Reason: {e}")
            shutil.move(original_path, os.path.join(unorganized_dir, filename))
            unorganized_count += 1
        except Exception as e:
            logging.error(f"[{i+1}/{total_files}] A critical error occurred with '{filename}': {e}")
            unorganized_count += 1
            
    logging.info("--- Sorting complete! ---")
    logging.info(f"  Successfully sorted: {success_count} files")
    logging.info(f"  Could not sort: {unorganized_count} files (see '_unorganized' folder)")

if __name__ == "__main__":
    renamed_photos_dir, backup_dir = r"C:\Users\mitsa\Desktop\RAWTWENTYFIve", r"C:\Users\mitsa\Desktop\PHOTOSDUMP\ALL_PHOTOS"
        
    sort_renamed_photos(renamed_photos_dir, backup_dir)