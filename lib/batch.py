#!/usr/bin/env python3

"""
MKV Factory - Batch Processing Module
"""

import os
from typing import Dict

try:
    from .utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header
    )
    from .analysis import analizuj_plik
    from .config_automated import configure_automated_run
    from .processing import run_full_conversion
except ImportError:
    # Fallback
    from utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header
    )
    from analysis import analizuj_plik
    from config_automated import configure_automated_run
    from processing import run_full_conversion


# --- Phase 4: Batch Processing Logic ---

def run_batch_processing(source_dir: str, output_dir: str, profile_data: Dict, encoder_type: str):
    """
    Finds all video files in source_dir and processes them using automated config.
    """
    print_header("Batch Mode Initialized")
    print_info(f"Source: {source_dir}")
    print_info(f"Output: {output_dir}")
    print_info(f"Encoder: {encoder_type}")

    video_files = []
    valid_extensions = ('.mkv', '.mp4', '.m2ts', '.ts', '.mov', '.webm')
    for filename in os.listdir(source_dir):
        if filename.lower().endswith(valid_extensions):
            video_files.append(os.path.join(source_dir, filename))

    if not video_files:
        print_warn("No video files found in source directory.")
        return

    print_info(f"Found {len(video_files)} file(s) to process.")

    success_count = 0
    fail_count = 0

    for i, source_file in enumerate(video_files):
        print_k(f"\n--- Processing File {i+1}/{len(video_files)}: {os.path.basename(source_file)} ---", Kolory.NAGLOWEK, bold=True)

        # Unique ID for temp files
        file_basename = os.path.splitext(os.path.basename(source_file))[0]
        # Add hash to prevent name collisions
        file_basename = f"{file_basename}_{hash(source_file) & 0xffff:04x}"


        try:
            streams, source_duration = analizuj_plik(source_file)

            if not streams['video']:
                print_warn("No video stream found. Skipping file.")
                fail_count += 1
                continue

            config_batch = configure_automated_run(
                streams,
                source_file,
                output_dir,
                source_duration,
                encoder_type,
                profile_data
            )

            run_full_conversion(
                source_file,
                output_dir,
                config_batch,
                file_basename=file_basename
            )
            success_count += 1

        except Exception as e:
            print_error(f"FATAL: Failed to process file {source_file}: {e}")
            print_warn("Continuing to the next file...")
            fail_count += 1

    print_header("Batch Processing Complete")
    print_k(f"Successfully processed: {success_count}", Kolory.OKGREEN)
    if fail_count > 0:
        print_k(f"Failed to process: {fail_count}", Kolory.FAIL)
    else:
        print_info("All files processed without fatal errors.")
