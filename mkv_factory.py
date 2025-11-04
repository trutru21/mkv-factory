#!/usr/bin/env python3

"""
MKV Conversion & Remuxing Factory (Version 9.0)
Copyright (c) 2025 Tomasz Rurarz

Changes
- introduce processing strategies
- introduce HDR policies (drop, keep, convert)
- introduce HDR10+ handling

Features:
- Full batch processing support (-s, -o, -p) with configurable policies.
- Interactive mode for single files and maximum control.
- Flexible Dynamic HDR Handling: Independent policies for Dolby Vision (keep, drop, convert) and HDR10+ (keep, drop).
- Dual-Mode Video Processing:
  - Passthrough: Copy video stream, respecting DV and HDR10+ policies.
  - Encode: Re-encode video, respecting DV (re-injection) and HDR10+ (re-injection) policies.
- Hardware Acceleration: Smart encoder detection (Nvidia NVENC vs. AMD AMF).
- Smart 'audio_selection' and 'subtitle_selection' with language and codec priorities.
- Advanced file naming logic (unique names, special chars, media format).
- External audio/subtitle injection (interactive mode only) with duration check.
- Smart cleanup of temporary files based on profile policy.
"""

import subprocess
import os
import sys
import json
import shutil
import argparse
import re
import datetime
import string

from typing import List, Dict, Optional, Any

from lib.utils import (
    Kolory,
    print_k,
    print_info,
    print_warn,
    print_error,
    print_header,
    input_k,
    sanitize_filename,
    is_progress_line,
    run_command,
    skasuj_plik,
    sprzataj_pliki,
    get_file_duration,
    get_unique_filename,
    get_unique_languages,
    LOG_FILE,
    COLORAMA_AVAILABLE
)

from lib.validation import (
    validate_encoder_param,
    validate_profile_globally
)

from lib.system import check_tools_and_encoders

from lib.analysis import analizuj_plik

from lib.config_interactive import (
    configure_full_run,
    configure_extraction
)

from lib.config_automated import configure_automated_run

from lib.processing import (
    run_extraction,
    run_full_conversion
)

from lib.batch import run_batch_processing

# --- Phase 0: Environment Check ---
# Moved to system.py

# --- Phase 1: Source File Analysis ---
# Moved to analysis.py

# --- Phase 2: Interactive Configuration ---
# Moved to config_builder.py

# --- Phase 3: Process Execution ---
# Moved to processing.py

# --- Phase 4: Batch Processing Logic ---
# Moved to batch.py

# --- Main script function ---

def main():
    import lib.utils

    if COLORAMA_AVAILABLE and os.name == 'nt':
        import colorama
        colorama.init(autoreset=True)

    parser = argparse.ArgumentParser(description="Interactive MKV Conversion Script")
    parser.add_argument('-p', '--profile', metavar="profile.json", type=str, help="Path to a JSON configuration profile.")
    parser.add_argument('-i', '--input', metavar="source.mkv", type=str, help="Path to a single source file (interactive mode).")
    parser.add_argument('-s', '--source', metavar="/path/to/videos", type=str, help="Path to a source directory (batch mode).")
    parser.add_argument('-o', '--output', metavar="/path/to/output", type=str, help="Path to an output directory (batch mode).")
    parser.add_argument('--log', action='store_true', help="Enable logging to a file in the output directory (even without a profile).")

    args = parser.parse_args()

    loaded_profile = None
    log_config = {} # Initialize empty log config

    if args.profile:
        print_info(f"Loading configuration profile from: {args.profile}")
        try:
            with open(args.profile, 'r', encoding='utf-8') as f:
                loaded_profile = json.load(f)

            # Read logging configuration, but don't open the file yet
            log_config = loaded_profile.get('logging', {})

        except FileNotFoundError:
            print_error(f"Profile file not found: {args.profile}"); sys.exit(1)
        except json.JSONDecodeError:
            # This catches SYNTAX errors
            print_error(f"Failed to parse JSON in profile (syntax error): {args.profile}"); sys.exit(1)
        except Exception as e:
            print_error(f"Failed to load profile: {e}"); sys.exit(1)
    else:
        if not args.log:
            print_info("No --profile argument provided. File logging is disabled.")
            print_info("(Use --log to enable it, or set 'log_to_file: true' in a profile)")

    # Helper function to open the log file in the correct location
    def initialize_logging(output_directory: str):
        logging_enabled_by_profile = log_config.get('log_to_file', False)
        logging_enabled_by_flag = args.log

        if (logging_enabled_by_profile or logging_enabled_by_flag) and lib.utils.LOG_FILE is None:
            log_filename = log_config.get('log_filename', 'mkv_factory.log')
            log_path = os.path.join(output_directory, log_filename)
            try:
                lib.utils.LOG_FILE = open(log_path, 'a', encoding='utf-8')
                import datetime
                now = datetime.datetime.now().isoformat()
                lib.utils.LOG_FILE.write(f"\n--- Log Session Started: {now} ---\n")
                lib.utils.LOG_FILE.flush()
                print_info(f"Logging to file: {log_path}")
            except Exception as e:
                print_error(f"Failed to open log file {log_path}: {e}")
                lib.utils.LOG_FILE = None

        else:
            if not logging_enabled_by_profile and not logging_enabled_by_flag:
                 pass
            elif args.profile and not logging_enabled_by_profile and not logging_enabled_by_flag:
                 print_info("Logging to file is disabled in profile and --log flag was not used.")

    try:
        supported_encoder = check_tools_and_encoders()
        if not supported_encoder:
            sys.exit(1)

        # Global validation block
        # Check the profile *globally* right after loading it.
        if loaded_profile:
            try:
                # This function will check all sections (encoder, audio, etc.)
                validate_profile_globally(loaded_profile, supported_encoder)
            except ValueError as e:
                # This catches SEMANTIC errors (e.g., "cq": "qwerty")
                print_error(f"FATAL: Invalid configuration in '{args.profile}':")
                print_error(f"  -> {e}")
                print_warn("Please fix the profile.json file and try again.")
                sys.exit(1)

        # 1. BATCH MODE
        if args.source and args.output:
            if not args.profile or not loaded_profile:
                print_error("Batch mode requires a valid --profile to be specified.")
                sys.exit(1)

            output_dir = args.output

            if not os.path.isdir(args.source):
                print_error(f"Source directory not found: {args.source}")
                sys.exit(1)

            if not os.path.isdir(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    print_info(f"Created output directory: {output_dir}")
                except OSError as e:
                    print_error(f"Could not create output directory: {e}")
                    sys.exit(1)

            initialize_logging(output_dir)

            run_batch_processing(
                args.source,
                output_dir,
                loaded_profile,
                supported_encoder
            )

        # 2. INTERACTIVE MODE (SINGLE FILE)
        elif args.input:
            print_header("Single File (Interactive) Mode")
            source_file = args.input
            if not os.path.exists(source_file):
                print_error(f"Source file not found: {source_file}")
                sys.exit(1)

            output_dir = os.getcwd()
            print_info(f"Working (output) directory: {output_dir}")

            initialize_logging(output_dir)

            mode = ""
            while mode not in ['1', '2']:
                print_k("\nSelect operating mode:", bold=True)
                print("  1. Full Conversion")
                print("  2. Extraction Only")
                mode = input_k("Choice [1]: ") or "1"

            streams, source_duration = analizuj_plik(source_file)

            if not streams['video'] and mode == '1':
                 print_error("No video stream found. Cannot run full conversion.")
                 sys.exit(1)

            if mode == '1':
                config_full = configure_full_run(
                    streams,
                    source_file,
                    output_dir,
                    source_duration,
                    supported_encoder,
                    profile_data=loaded_profile
                )

                file_basename = os.path.splitext(os.path.basename(source_file))[0]

                run_full_conversion(
                    source_file,
                    output_dir,
                    config_full,
                    file_basename=file_basename
                )
            else:
                config_extract = configure_extraction(streams)
                if config_extract:
                    run_extraction(source_file, output_dir, config_extract)
                else:
                    print_info("Extraction cancelled as no streams were selected.")

        # 3. NO ARGUMENTS
        else:
            print_warn("No input specified.")
            print_info("Usage for batch mode:   python3 mkv_factory.py -s /source/dir -o /output/dir -p profile.json")
            print_info("Usage for single file:  python3 mkv_factory.py -i /path/to/file.mkv [-p profile.json] [--log]")
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        print_error("\nProcess interrupted by user.")
        if LOG_FILE: LOG_FILE.write("--- Interrupted by user ---\n")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nAn unexpected error occurred in main: {e}")
        if LOG_FILE: LOG_FILE.write(f"--- FATAL ERROR: {e} ---\n")
        import traceback
        traceback.print_exc(file=LOG_FILE if LOG_FILE else sys.stderr)
        sys.exit(1)
    finally:
        if lib.utils.LOG_FILE:
            print_info("Closing log file.")
            lib.utils.LOG_FILE.write("--- Log Session Ended ---\n")
            lib.utils.LOG_FILE.close()

if __name__ == "__main__":
    main()
