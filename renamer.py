import os
import json
import sys
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("renamer_log.txt", mode='w'),
        logging.StreamHandler()
    ]
)

def index_json_dates(json_dir):
    logging.info(f"Scanning for JSON files in '{json_dir}'...")
    date_index = {}
    for root, _, files in os.walk(json_dir):
        for file in files:
            if file.lower().endswith('.json'):
                json_path = os.path.join(root, file)
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                        title = data.get('title')
                        if not title:
                            continue

                        timestamp = None
                        if 'photoTakenTime' in data:
                            timestamp = data['photoTakenTime'].get('timestamp')
                        elif 'creationTime' in data:
                            timestamp = data['creationTime'].get('timestamp')
                        
                        if timestamp:
                            dt_object = datetime.fromtimestamp(int(timestamp))
                            date_index[title] = dt_object
                except (json.JSONDecodeError, IOError) as e:
                    logging.warning(f"Could not read or parse {json_path}: {e}")
    logging.info(f"Indexing complete. Found date information for {len(date_index)} files.")
    return date_index

def rename_photos_in_place(photo_dir, date_index):
    logging.info(f"Starting to rename photos in '{photo_dir}'...")
    
    # --- THIS IS THE CORRECTED LINE ---
    total_files = sum(1 for _, _, files in os.walk(photo_dir) for f in files if not f.lower().endswith('.json'))
    
    success_count = 0
    unmatched_count = 0
    processed_count = 0

    for root, _, files in os.walk(photo_dir):
        for filename in files:
            if filename.lower().endswith('.json'):
                continue

            processed_count += 1
            original_path = os.path.join(root, filename)
            
            date_info = date_index.get(filename)
            
            if date_info:
                try:
                    date_prefix = date_info.strftime('%Y-%m-%d')
                    new_filename = f"{date_prefix}_{filename}"
                    new_path = os.path.join(root, new_filename)
                    
                    os.rename(original_path, new_path)
                    
                    logging.info(f"[{processed_count}/{total_files}] Renamed: {filename} -> {new_filename}")
                    success_count += 1
                except Exception as e:
                    logging.error(f"[{processed_count}/{total_files}] Error renaming {filename}: {e}")
                    unmatched_count += 1
            else:
                logging.warning(f"[{processed_count}/{total_files}] No match found for: {filename}")
                unmatched_count += 1
    
    logging.info("--- Renaming complete! ---")
    logging.info(f"  Successfully renamed: {success_count} files")
    logging.info(f"  Unmatched or failed: {unmatched_count} files")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python renamer.py <json_dir> <photo_dir>")
        sys.exit(1)

    json_dir, photo_dir = sys.argv[1:3]
        
    date_data = index_json_dates(json_dir)
    if not date_data:
        logging.critical("No JSON date data was indexed. Exiting.")
        sys.exit(1)
        
    rename_photos_in_place(photo_dir, date_data)