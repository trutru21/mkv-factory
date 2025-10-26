#!/usr/bin/env python3

"""
MKV Conversion & Remuxing Factory (Version 8.4)
Copyright (c) 2025 Tomasz Rurarz

Fixes
- Remove "Fast path" for DV8 as it produces corrupted video streams that will casue DV-enabled players to crash.

Features:
- Full batch processing support (-s, -o, -p) with configurable policies.
- Interactive mode for single files and maximum control.
- Smart 'audio_selection' and 'subtitle_selection'.
- Advanced file naming logic (unique names, special chars, media format).
- Profile support via '-p' argument.
- Smart encoder detection (Nvidia NVENC vs. AMD AMF).
- Separate configuration for NVENC (CQ/Preset) and AMF (QP/Quality).
- Dolby Vision (Profile 8) passthrough using dovi_tool, with auto-conversion for 5.x and 7.x profiles.
- HDR10 tags reinjection.
- Video passthrough mode with/without DV profile conversion, while keeping HDR10+ data intact.
- Correct demuxing using 'mkvextract'.
- External audio/subtitle injection (interactive mode only).
- Duration check for external files.
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
try:
    import colorama
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False # colorama is not installed
try:
    from unidecode import unidecode
    UNIDECODE_AVAILABLE = True
except ImportError:
    UNIDECODE_AVAILABLE = False
from typing import List, Dict, Optional, Any

LOG_FILE: Optional[Any] = None
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
UNIDECODE_WARNING_SHOWN = False


# --- Tool Configuration ---
WYMAGANE_NARZEDZIA = ['ffmpeg', 'ffprobe', 'mkvmerge', 'dovi_tool', 'mkvextract']

# --- Helper Classes for Logic ---
class Kolory:
    """Terminal color definitions."""

    if COLORAMA_AVAILABLE or os.name != 'nt':
        NAGLOWEK = '\033[95m'
        OKBLUE = '\033[94m'
        OKCYAN = '\033[96m'
        OKGREEN = '\033[92m'
        WARNING = '\033[93m'
        FAIL = '\033[91m'
        ENDC = '\033[0m'
        BOLD = '\033[1m'
        UNDERLINE = '\033[4m'
    else:
        NAGLOWEK = OKBLUE = OKCYAN = OKGREEN = WARNING = FAIL = ENDC = BOLD = UNDERLINE = ""

def print_k(text: str, color: str = Kolory.OKGREEN, bold: bool = False):
    """
    Prints colored text to console (no timestamp).
    Prints timestamped, clean text to log file (if configured).
    """
    global LOG_FILE

    b = Kolory.BOLD if bold else ""

    # --- 1. Console Output (No Timestamp) ---
    formatted_text = f"{b}{color}{text}{Kolory.ENDC}"
    print(formatted_text)

    # --- 2. Log File Output (With Timestamp) ---
    if LOG_FILE:
        try:
            # Generate timestamp *only* when writing to the log
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Strip colors from the formatted text to get a clean log entry
            # This 'clean_text' does NOT have a timestamp yet
            clean_text = ANSI_ESCAPE.sub('', formatted_text)

            # Prepend timestamp to the *clean* text
            prefixed_clean_text = f"[{ts}] {clean_text}"

            LOG_FILE.write(prefixed_clean_text + '\n')
            LOG_FILE.flush()
        except Exception as e:
            # Fallback in case of write error
            # Print the error *to the console*, but with a timestamp
            # to make it clear it's a logging system error.
            ts_err = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts_err}] ❌ Log write error: {e}")
            LOG_FILE = None

def print_info(text: str):
    print_k(f"INFO: {text}", Kolory.OKCYAN)

def print_warn(text: str):
    print_k(f"WARN: {text}", Kolory.WARNING)

def print_error(text: str):
    print_k(f"ERROR: {text}", Kolory.FAIL, bold=True)

def print_header(text: str):
    print_k(f"\n--- {text} ---", Kolory.NAGLOWEK, bold=True)

def input_k(prompt: str, color: str = Kolory.OKCYAN, bold: bool = True) -> str:
    """
    A wrapper for input() that prints a colored prompt
    and logs BOTH the prompt and the response to the log file.
    """
    global LOG_FILE

    # 1. Format the prompt for the console
    b = Kolory.BOLD if bold else ""
    formatted_prompt = f"{b}{color}{prompt}{Kolory.ENDC}"

    # 2. Get user input using the BUILT-IN 'input()' function
    #    This line MUST be 'input()', NOT 'input_k()'
    response = input(formatted_prompt)

    # 3. Log both prompt and response to file (if logging is enabled)
    if LOG_FILE:
        try:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Clean the prompt (it has color codes)
            clean_prompt = ANSI_ESCAPE.sub('', formatted_prompt)

            # Write "prompt[response]"
            LOG_FILE.write(f"[{ts}] {clean_prompt}{response}\n")
            LOG_FILE.flush()
        except Exception as e:
            ts_err = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts_err}] ERROR: Log write error: {e}")
            LOG_FILE = None

    return response

def sanitize_filename(filename: str) -> str:
    """
    Converts a filename to ASCII, removing special characters to make it
    safe for command-line tools.
    Uses 'unidecode' if available for smart transliteration (ś -> s),
    otherwise falls back to basic ASCII encoding (ś -> [removed]).
    """
    global UNIDECODE_WARNING_SHOWN

    # 1. Separate the base name and extension
    base_name, extension = os.path.splitext(filename)
    safe_base_name = ""

    if UNIDECODE_AVAILABLE:
        # --- Smart Path (unidecode installed) ---
        # "Tèściczek [żółć]" -> "Tesciczek [zolc]"
        safe_base_name = unidecode(base_name)

    else:
        # --- Fallback Path (unidecode NOT installed) ---
        if not UNIDECODE_WARNING_SHOWN:
            print_warn("Library 'unidecode' is not installed (use: pip install unidecode).")
            print_warn("Activating fallback mode: Special characters (e.g., 'ś', 'ó') will be REMOVED, not transliterated (to 's', 'o').")
            UNIDECODE_WARNING_SHOWN = True # Show warning only once

        # "Tèściczek [żółć]" -> "Tsciczek [olc]"
        # This works by encoding to ASCII and just ignoring errors (dropping chars)
        safe_base_name = base_name.encode('ascii', errors='ignore').decode('ascii')

    # 3. (Optional but recommended) Remove any remaining non-safe chars
    # This regex keeps letters, numbers, spaces, dots, underscores, dashes, and brackets
    safe_base_name = re.sub(r'[^\w\s\._\-\[\]\(\)]', '', safe_base_name).strip()

    # 4. Re-assemble the filename
    return f"{safe_base_name}{extension}"

# Progress filtering patterns to prevent flooding console and logfile
PROGRESS_PATTERNS = (
    # ffmpeg
    "frame=", "fps=", "time=", "bitrate=", "speed=", "size=",
    # mkvmerge/mkvextract
    "muxing overhead", "progress="
)

### Progress line detection function
def is_progress_line(original_line: str) -> bool:
    """
    Returns True if the line looks like a progress update
    rather than a normal log message.
    """
    # 1. Carriage Return Check (strongest indicator)
    if original_line.endswith('\r'):
        return True

    l = original_line.lower().strip()

    # 2. Empty or very short lines - ignore
    if not l or len(l) < 5:
        return False

    # 3. Check for specific tokens (ffmpeg, mkvmerge)
    # Also check it's not a header line
    if not l.startswith("ffmpeg") and not l.startswith("mkvmerge"):
        for token in PROGRESS_PATTERNS:
            if token in l:
                return True

    # 4. Check for percentage-based lines (catches dovi_tool, mkvextract)
    if '%' in l and ('eta' in l or l.startswith("processing") or l.startswith("postęp")):
        return True

    return False

def run_command(cmd: List[str], cwd: str = None):
    """
    Runs a system command, captures its output.
    - Uses a "fast path" (communicate()) for silent tools (dovi_tool).
    - Uses a "real-time path" (readline()) for verbose tools (ffmpeg, mkvmerge).
    - Handles non-UTF-8 output from tools by replacing invalid characters.
    """
    # Print the command
    print_k(f"$ {' '.join(cmd)}", Kolory.OKBLUE)

    # Define tools that are fast and/or silent in pipes
    FAST_TOOLS = ['dovi_tool']

    is_fast_tool = cmd[0] in FAST_TOOLS

    last_line_was_progress = False

    try:
        process = subprocess.Popen(
            cmd,
            text=True,
            encoding='utf-8',
            errors='replace', # Prevents crash on non-UTF-8 chars from tools
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )

        return_code = None

        if is_fast_tool:
            # --- FAST PATH (for dovi_tool) ---
            # These tools are silent; readline() would hang.
            # Use communicate() to wait for exit and get all output at once.

            print_info(f"Running '{cmd[0]}'. This tool is silent; waiting for completion...")

            # communicate() waits for the process to terminate
            # The 'errors='replace'' flag ensures decoding won't crash
            stdout_data, _ = process.communicate()
            return_code = process.returncode

            # Print any captured output
            if stdout_data:
                for line in stdout_data.splitlines():
                    if line.strip():
                        print_k(f"  [Tool] {line.strip()}", Kolory.OKBLUE)

        else:
            # --- REAL-TIME PATH (for ffmpeg / mkvmerge) ---
            if process.stdout:
                with process.stdout:
                    # iter(readline, "") also benefits from 'errors='replace''
                    for line in iter(process.stdout.readline, ""):
                        if not line:
                            break # Process finished

                        line_clean = line.strip()

                        is_progress = is_progress_line(line)

                        if is_progress:
                            last_line_was_progress = True
                            # Print progress only to console
                            print(
                                f"{Kolory.OKBLUE}  [Tool] {line_clean}{Kolory.ENDC}",
                                end='\r',
                                flush=True
                            )
                        else:
                            # This is a "non-progress" line.
                            # We must first check if it's spam BEFORE printing a newline.
                            if line_clean:
                                l_clean_low = line_clean.lower()

                                # --- NOWA, POPRAWIONA LOGIKA FILTROWANIA ---
                                is_spam = False
                                if "skipping nal unit" in l_clean_low:
                                    is_spam = True # Spam z DV7 (Path B)
                                elif "last message repeated" in l_clean_low:
                                    is_spam = True # Spam z DV7 (Path B)
                                elif "could not find codec parameters" in l_clean_low:
                                    is_spam = True # Spam o napisach PGS (Path A, C)

                                if is_spam:
                                    pass
                                else:
                                    if last_line_was_progress:
                                        print()
                                        last_line_was_progress = False

                                    print_k(f"  [Tool] {line_clean}", Kolory.OKBLUE)
                            else:
                                if last_line_was_progress:
                                    print()
                                    last_line_was_progress = False

            if last_line_was_progress:
                print() # Clean up the last progress line

            return_code = process.wait()

        # --- Common return code check ---
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, cmd)

        print_k("OK: Command executed successfully.", Kolory.OKGREEN)

    except subprocess.CalledProcessError as e:
        if last_line_was_progress:
            print()
        print_error(f"Error executing command: {e}")
        raise
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}. Is it in PATH?")
        raise
    except Exception as e:
        if last_line_was_progress:
            print()
        print_error(f"An unexpected error occurred in run_command: {e}")
        raise

# --- Phase 0: Environment Check ---

def check_encoder_support(encoder_name: str) -> bool:
    """Checks if ffmpeg supports a specific encoder."""
    try:
        cmd = ['ffmpeg', '-h', f'encoder={encoder_name}']
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def check_tools_and_encoders() -> Optional[str]:
    """
    Checks for all required tools and supported hardware encoders.
    Returns the name of the supported encoder ('nvenc' or 'amf') or None.
    """
    print_header("Phase 0: Checking Environment")
    missing_tools = []
    for tool in WYMAGANE_NARZEDZIA:
        if shutil.which(tool) is None:
            missing_tools.append(tool)

    if missing_tools:
        print_error(f"Missing required tools: {', '.join(missing_tools)}")
        print_warn("Please ensure ffmpeg, mkvtoolnix, and dovi_tool are installed")
        print_warn("and accessible in your container's PATH.")
        return None

    print_info("All required tools (ffmpeg, ffprobe, mkvmerge, mkvextract, dovi_tool) are available.")

    if check_encoder_support('hevc_nvenc'):
        print_info("OK: Nvidia (hevc_nvenc) encoder detected.")
        return 'nvenc'

    if check_encoder_support('hevc_amf'):
        print_info("OK: AMD (hevc_amf) encoder detected.")
        return 'amf'

    print_error("No supported hardware HEVC encoder found.")
    print_warn("This script requires either Nvidia (hevc_nvenc) or AMD (hevc_amf) support in ffmpeg.")
    return None

# --- Phase 1: Source File Analysis ---

def analizuj_plik(source_file: str) -> (Dict[str, Any], Optional[float]):
    """Uses ffprobe to analyze the file and returns streams and duration."""
    print_header(f"Analyzing source file: {os.path.basename(source_file)}")
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_streams', '-show_format', source_file
    ]
    try:
        # --- PASS 1: STREAM-LEVEL PROBE ---
        print_info("Running stream-level probe...")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        data = json.loads(result.stdout)

        streams = {
            'video': [],
            'audio': [],
            'subtitle': [],
            'has_dv': False,
            'dv_profile': None,
            'hdr10_master_display': None,
            'hdr10_cll_fall': None
        }

        source_duration = None
        format_data = data.get('format', {})
        if 'duration' in format_data:
            try:
                source_duration = float(format_data['duration'])
                print_info(f"Source file duration: {source_duration:.2f}s")
            except ValueError:
                print_warn("Could not parse source file duration.")

        main_video_found = False
        main_video_stream_index = "0"

        def parse_rational(r_str):
            if isinstance(r_str, (int, float)): return float(r_str)
            if '/' not in str(r_str): return float(r_str)
            num, den = map(float, str(r_str).split('/'))
            if den == 0: return 0.0
            return num / den

        for stream in data.get('streams', []):
            codec_type = stream.get('codec_type')

            if codec_type == 'video':
                if not main_video_found:
                    streams['video'].append(stream)
                    main_video_found = True
                    main_video_stream_index = str(stream.get('index', '0'))

                    md = stream.get('mastering_display_metadata')
                    cll = stream.get('content_light_level_metadata')

                    side_data = stream.get('side_data_list', [])
                    for data_item in side_data:
                        side_data_type = data_item.get('side_data_type')

                        if side_data_type == "DOVI configuration record":
                            streams['has_dv'] = True
                            streams['dv_profile'] = data_item.get('dv_profile')

                        elif side_data_type == "Mastering display metadata":
                            if not md:
                                md = data_item
                                print_info("Found HDR10 Mastering Display in 'stream side_data'.")
                        elif side_data_type == "Content light level metadata":
                            if not cll:
                                cll = data_item
                                print_info("Found HDR10 Content Light Level in 'stream side_data'.")

                    if md:
                        try:
                            gx = parse_rational(md['green_x'])
                            gy = parse_rational(md['green_y'])
                            bx = parse_rational(md['blue_x'])
                            by = parse_rational(md['blue_y'])
                            rx = parse_rational(md['red_x'])
                            ry = parse_rational(md['red_y'])
                            wpx = parse_rational(md['white_point_x'])
                            wpy = parse_rational(md['white_point_y'])
                            max_lum = parse_rational(md['max_luminance'])
                            min_lum = parse_rational(md['min_luminance'])
                            streams['hdr10_master_display'] = f"G({gx:.4f},{gy:.4f})B({bx:.4f},{by:.4f})R({rx:.4f},{ry:.4f})WP({wpx:.4f},{wpy:.4f})L({max_lum:.4f},{min_lum:.4f})"
                            print_info("Successfully parsed HDR10 Mastering Display metadata.")
                        except Exception as e:
                            print_warn(f"Could not parse mastering display metadata (from stream): {e}")

                    if cll:
                        try:
                            max_cll_val = int(cll.get('max_cll', cll.get('max_content', 0)))
                            max_fall_val = int(cll.get('max_fall', cll.get('max_average', 0)))
                            if max_cll_val > 0 or max_fall_val > 0: # Avoid storing "0,0" if parsing failed
                                streams['hdr10_cll_fall'] = f"{max_cll_val},{max_fall_val}"
                                print_info("Successfully parsed HDR10 Content Light Level metadata.")
                            else:
                                print_warn("Parsed Content Light Level values seem invalid (0,0). Ignoring.")
                        except Exception as e:
                            print_warn(f"Could not parse content light level metadata (from stream): {e}")

                    if not streams['has_dv']:
                        tags = stream.get('tags', {})
                        comment = tags.get('comment', '')
                        if 'Dolby Vision' in comment:
                            streams['has_dv'] = True # Might not have profile info here

                else: # Handle secondary video streams (cover art, EL)
                    idx = stream.get('index')
                    codec_name = stream.get('codec_name', 'unknown')
                    if codec_name == 'mjpeg':
                        print_info(f"Ignoring attached image/cover art (Index: {idx}, Codec: {codec_name}).")
                    elif ('hevc' in codec_name or 'h265' in codec_name) and streams.get('dv_profile') == 7:
                        # Only warn about EL if we detected profile 7 earlier
                        print_warn(f"Found a second HEVC video stream (Index: {idx}). Assuming Dolby Vision Enhancement Layer (EL) for Profile 7.")
                        print_warn("This EL stream will be IGNORED by ffmpeg mapping. RPU will be extracted and injected.")
                    elif ('hevc' in codec_name or 'h265' in codec_name):
                         print_warn(f"Found an unexpected second HEVC video stream (Index: {idx}, Codec: {codec_name}). This stream will be IGNORED.")
                    else:
                         print_warn(f"Found an unexpected second video stream (Index: {idx}, Codec: {codec_name}). This stream will be IGNORED.")


            elif codec_type == 'audio':
                streams['audio'].append(stream)
            elif codec_type == 'subtitle':
                streams['subtitle'].append(stream)

        # --- END OF PASS 1 ---

        if not streams['video']:
             print_warn("No video stream found in file.")
             return streams, source_duration

        # --- START 2ND PASS: FRAME-LEVEL PROBE (if needed for HDR10) ---
        if main_video_found and (streams['hdr10_master_display'] is None or streams['hdr10_cll_fall'] is None):
            print_info("Stream-level probe did not find full HDR10 metadata. Trying frame-level probe...")
            stream_selector = f"v:{main_video_stream_index}"
            cmd_frame = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_frames', '-select_streams', stream_selector,
                '-read_intervals', '%+#1', source_file
            ]
            try:
                result_frame = subprocess.run(cmd_frame, capture_output=True, text=True, check=True, encoding='utf-8')
                data_frame = json.loads(result_frame.stdout)
                frames = data_frame.get('frames', [])
                if frames:
                    frame_side_data = frames[0].get('side_data_list', [])
                    md_frame = None
                    cll_frame = None
                    for data_item in frame_side_data:
                        side_data_type = data_item.get('side_data_type')
                        if side_data_type == "Mastering display metadata": md_frame = data_item
                        elif side_data_type == "Content light level metadata": cll_frame = data_item

                    if md_frame and streams['hdr10_master_display'] is None:
                        print_info("Found HDR10 Mastering Display.")
                        try:
                            gx = parse_rational(md_frame['green_x'])
                            gy = parse_rational(md_frame['green_y'])
                            bx = parse_rational(md_frame['blue_x'])
                            by = parse_rational(md_frame['blue_y'])
                            rx = parse_rational(md_frame['red_x'])
                            ry = parse_rational(md_frame['red_y'])
                            wpx = parse_rational(md_frame['white_point_x'])
                            wpy = parse_rational(md_frame['white_point_y'])
                            max_lum = parse_rational(md_frame['max_luminance'])
                            min_lum = parse_rational(md_frame['min_luminance'])
                            streams['hdr10_master_display'] = f"G({gx:.4f},{gy:.4f})B({bx:.4f},{by:.4f})R({rx:.4f},{ry:.4f})WP({wpx:.4f},{wpy:.4f})L({max_lum:.4f},{min_lum:.4f})"
                            print_info("Successfully parsed HDR10 Mastering Display.")
                        except Exception as e:
                            print_warn(f"Could not parse mastering display metadata (from frame): {e}")

                    if cll_frame and streams['hdr10_cll_fall'] is None:
                        print_info("Found HDR10 Content Light Level.")
                        try:
                            max_cll_val = int(cll_frame.get('max_cll', cll_frame.get('max_content', 0)))
                            max_fall_val = int(cll_frame.get('max_fall', cll_frame.get('max_average', 0)))
                            if max_cll_val > 0 or max_fall_val > 0:
                                streams['hdr10_cll_fall'] = f"{max_cll_val},{max_fall_val}"
                                print_info("Successfully parsed HDR10 Content Light Level.")
                            else:
                                 print_warn("Parsed Content Light Level values (from frame) seem invalid (0,0). Ignoring.")
                        except Exception as e:
                            print_warn(f"Could not parse content light level metadata (from frame): {e}")
            except subprocess.CalledProcessError as e:
                print_warn(f"Frame-level probe failed: {e.stderr}")
            except json.JSONDecodeError:
                print_warn("Failed to parse JSON from frame-level probe.")
            except Exception as e:
                print_warn(f"An unexpected error occurred during frame-level probe: {e}")
        # --- END 2ND PASS ---

        # Final report
        if streams['has_dv']:
            profile_str = f" (Profile {streams['dv_profile']})" if streams['dv_profile'] else ""
            print_info(f"Dolby Vision metadata detected{profile_str}.")

        # Check HDR status separately and report ONLY the final status
        hdr_found = streams['hdr10_master_display'] or streams['hdr10_cll_fall']

        if hdr_found:
            # Parsing messages from probes are sufficient confirmation
            pass
        elif not streams['has_dv']: # If no DV AND no HDR found
            print_warn("No Dolby Vision or HDR10 metadata detected by ffprobe.")
        else: # If DV is present BUT no HDR found
            print_info("No HDR10 metadata detected by ffprobe.")

        return streams, source_duration

    except subprocess.CalledProcessError as e:
        print_error(f"Error during file analysis (ffprobe): {e}")
        if e.stderr: print_error(f"Error output: {e.stderr}")
        raise
    except json.JSONDecodeError:
        print_error("Error parsing JSON output from ffprobe.")
        raise

# --- Phase 2: Interactive Configuration ---

def format_stream_description(stream: Dict[str, Any]) -> str:
    """Creates a human-readable stream description."""
    idx = stream['index']
    codec = stream.get('codec_name', 'n/a')
    profile = stream.get('profile', '')
    lang = stream.get('tags', {}).get('language', 'und')
    title = stream.get('tags', {}).get('title', 'No title')

    if stream.get('codec_type') == 'audio':
        channels = stream.get('channels', '?')
        return f"[Index: {idx}] {lang.upper()} - {codec} {profile} ({channels}ch) - '{title}'"
    elif stream.get('codec_type') == 'subtitle':
        return f"[Index: {idx}] {lang.upper()} - {codec} - '{title}'"
    else:
        return f"[Index: {idx}] {codec} {profile}"

def select_stream(
    stream_list: List[Dict[str, Any]],
    description: str,
    allow_skip: bool = True,
    allow_all: bool = True
) -> List[Dict[str, Any]]:
    """
    Displays a list of streams and asks the user to pick one OR all.
    Returns a LIST of selected streams.
    """

    if not stream_list:
        print_info(f"No streams found for: {description}")
        return []

    print_k(f"\nSelect {description}:", bold=True)
    for i, stream in enumerate(stream_list):
        print_k(f"  {i+1}. {format_stream_description(stream)}", Kolory.ENDC)

    prompt_options = [f"1-{len(stream_list)}"]

    # Show "ALL" option only if allowed ---
    if allow_all:
        print_k(f"  ALL. ALL {len(stream_list)} tracks for this language", Kolory.ENDC)
        prompt_options.append("ALL")

    if allow_skip:
        print_k("  0. Skip / Do not include", Kolory.ENDC)
        prompt_options.insert(0, "0") # Add 0 to the front
        default_choice = "0"
    else:
        default_choice = ""

    prompt = f"Your choice ({', '.join(prompt_options)})"
    prompt += f" [{default_choice}]: " if allow_skip else ": "

    while True:
        choice_str = input_k(prompt, Kolory.OKCYAN) or (default_choice if allow_skip else "")

        if choice_str.lower() == 'all':
            if allow_all: # Check if allowed
                print_info(f"Selecting all {len(stream_list)} tracks for {description}.")
                return stream_list
            else:
                # User typed "ALL" when it wasn't an option
                print_warn(f"Invalid choice. Please enter a number from 1 to {len(stream_list)}.")
                continue

        try:
            choice = int(choice_str)

            if allow_skip and choice == 0:
                return []
            if 1 <= choice <= len(stream_list):
                return [stream_list[choice - 1]]

            print_warn("Invalid choice, please try again.")

        except ValueError:
            print_warn("Please enter a number.")

def skasuj_plik(filepath: str, label: str = "temporary file"):
    """Safely deletes a single file if it exists."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            print_info(f"Immediately deleted {label}: {filepath}")
    except OSError as e:
        print_warn(f"Failed to delete file immediately: {filepath} ({e})")

def sprzataj_pliki(files_to_cleanup: List[str]):
    """Deletes a list of temporary files."""
    print_header("Step 8: Cleaning up temporary files")
    for f in files_to_cleanup:
        try:
            if os.path.exists(f):
                os.remove(f)
                print_info(f"Deleted: {f}")
        except OSError as e:
            print_warn(f"Failed to delete temporary file: {f} ({e})")

def get_file_duration(filepath: str) -> Optional[float]:
    """
    Returns the duration of a file in seconds by scanning packets.
    This method is slower but much more accurate and cross-platform.
    """
    print_info(f"Checking duration of: {filepath}...")
    print_warn("Using slow (but accurate) packet scan. This may take a few seconds...")
    duration = None

    try:
        # Run the command directly and capture all its output.
        cmd_slow = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'packet=pts_time',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            filepath
        ]

        result = subprocess.run(
            cmd_slow,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )

        # Get all lines of output
        output_lines = result.stdout.strip().split('\n')

        if output_lines:
            # Get the last line using Python
            duration_str = output_lines[-1]
            if duration_str:
                duration = float(duration_str)
                print_info(f"Detected duration (slow scan): {duration:.3f}s")
                return duration

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        print_warn(f"Could not determine duration for {filepath}: {e}")
        if isinstance(e, subprocess.CalledProcessError):
             # Log stderr if ffprobe failed
             print_warn(f"FFprobe stderr: {e.stderr}")
        return None
    except IndexError:
        # This can happen if ffprobe returns no output at all
        print_warn(f"FFprobe returned no duration information for {filepath}.")
        return None

    print_warn(f"Could not determine duration for {filepath} using any method.")
    return None

### Helper function to prevent overwriting files
def get_unique_filename(output_dir: str, desired_filename: str) -> str:
    """
    Checks if a file exists and appends (1), (2), etc. to avoid collision.
    Returns a unique filename (not the full path).
    """
    # Split the filename into base and extension (e.g., "Movie", ".mkv")
    base, ext = os.path.splitext(desired_filename)
    counter = 1
    final_path = os.path.join(output_dir, desired_filename)

    # Loop *while* the proposed path already exists
    while os.path.exists(final_path):
        # Create a new name with a counter
        new_filename = f"{base} ({counter}){ext}"
        final_path = os.path.join(output_dir, new_filename)
        counter += 1

    # Return the filename component only, not the full path
    return os.path.basename(final_path)

def validate_encoder_param(encoder_type: str, param_key: str, param_value: str):
    """
    Validates a single encoder parameter (key-value pair).
    Raises ValueError on failure.

    Uses sane/practical ranges, not ffmpeg's technical limits.
    """

    # Practical quality range to prevent absurd values (like 1000)
    SANE_QUALITY_MIN = 10
    SANE_QUALITY_MAX = 40

    if encoder_type == 'nvenc':
        if param_key == 'preset':
            valid_presets = ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7']
            if param_value not in valid_presets:
                raise ValueError(f"Invalid NVENC preset: '{param_value}'. Must be one of {valid_presets}.")

        elif param_key == 'cq':
            try:
                # Step 1: Validate if it's an integer
                cq = int(param_value)
            except (ValueError, TypeError):
                # This catches non-integer inputs (e.g., "abc")
                raise ValueError(f"Invalid NVENC CQ: '{param_value}'. Must be an integer (e.g., 16).")

            # Step 2: Validate the practical range
            if not (SANE_QUALITY_MIN <= cq <= SANE_QUALITY_MAX):
                 raise ValueError(f"CQ value {cq} is outside the practical range. Please enter a common value (e.g., 16).")

    elif encoder_type == 'amf':
        if param_key == 'quality':
            valid_qualities = ['speed', 'balanced', 'quality']
            if param_value not in valid_qualities:
                raise ValueError(f"Invalid AMF quality: '{param_value}'. Must be one of {valid_qualities}.")

        elif param_key == 'qp':
            try:
                qp = int(param_value)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid AMF QP: '{param_value}'. Must be an integer (e.g., 22).")

            if not (SANE_QUALITY_MIN <= qp <= SANE_QUALITY_MAX):
                raise ValueError(f"QP value {qp} is outside the practical range. Please enter a common value (e.g., 22).")

    else:
        raise ValueError(f"Unknown encoder type '{encoder_type}' for validation.")

### Helper function to get unique languages from a stream list
def get_unique_languages(stream_list: List[Dict[str, Any]]) -> List[str]:
    """Extracts a sorted list of unique language codes from streams."""
    languages = set()
    for stream in stream_list:
        # 'und' is the standard code for 'undefined'
        lang = stream.get('tags', {}).get('language', 'und')
        languages.add(lang)

    # Sort the list, but make sure 'und' (undefined) is always last
    sorted_langs = sorted([lang for lang in languages if lang != 'und'])
    if 'und' in languages:
        sorted_langs.append('und')
    return sorted_langs

### Helper for validate_profile_globally to check audio/sub blocks.
def _validate_selection_block(sel_block: Dict, block_name: str):
    """
    Validates the 'languages', 'policy', and 'preferred_codecs' keys
    within a selection block (audio or subtitle).
    Raises ValueError on failure.
    """

    # Check 'languages'
    langs = sel_block.get('languages')
    if langs is None:
        # 'languages' key is optional (though usually desired)
        pass
    elif isinstance(langs, str) and langs == 'all':
        # This is valid: "languages": "all"
        pass
    elif isinstance(langs, list):
        # This is valid: "languages": ["eng", "pol"]
        # Check if all items in the list are strings
        if not all(isinstance(item, str) for item in langs):
            raise ValueError(f"'{block_name}.languages' must be a list of strings (e.g., ['eng', 'pol']).")
    else:
        # It's not 'all', not a list, and not None. It's invalid.
        raise ValueError(f"'{block_name}.languages' must be a list of strings or the string 'all'.")

    # Check 'policy'
    policy = sel_block.get('policy')

    valid_policies = ['best_per_language', 'all']
    if policy is not None and policy not in valid_policies:
         raise ValueError(f"'{block_name}.policy' must be one of {valid_policies}.")

    # Check 'preferred_codecs'
    codecs = sel_block.get('preferred_codecs')
    if codecs is not None and not isinstance(codecs, list):
        raise ValueError(f"'{block_name}.preferred_codecs' must be a list of strings.")

    # Check 'exclude_titles_containing'
    excludes = sel_block.get('exclude_titles_containing')
    if excludes is not None and not isinstance(excludes, list):
        raise ValueError(f"'{block_name}.exclude_titles_containing' must be a list of strings.")

### Master validation function for the entire profile.json
def validate_profile_globally(profile_data: Dict, detected_encoder: str):
    """
    Validates the entire loaded profile.json structure at script start.
    Re-uses validate_encoder_param for encoder checks.
    Raises ValueError on the first error found.
    """
    print_info("Validating loaded profile.json semantic structure...")

    # --- Check video_policy first ---
    video_policy = profile_data.get('video_policy', 'encode') # Default to encode
    valid_video_policies = ['encode', 'passthrough']
    if video_policy not in valid_video_policies:
        raise ValueError(f"Invalid 'video_policy': '{video_policy}'. Must be one of {valid_video_policies}.")

    print_info(f"Video policy set to: '{video_policy}'")

    # --- Validate the hybrid passthrough flag ---
    # This flag is only relevant if video_policy is 'passthrough', but we validate it
    # globally if it exists, to catch typos early.
    passthrough_convert_dv = profile_data.get('passthrough_convert_dv_to_p8')
    if passthrough_convert_dv is not None and not isinstance(passthrough_convert_dv, bool):
        raise ValueError("'passthrough_convert_dv_to_p8' must be true or false.")

    # 1. Validate Encoder Params (ONLY if policy is 'encode')
    if video_policy == 'encode':
        if detected_encoder in profile_data:
            encoder_params = profile_data[detected_encoder].get('encoder_params')
            if not encoder_params or not isinstance(encoder_params, dict):
                raise ValueError(f"'{detected_encoder}.encoder_params' is missing or not a dictionary (required for 'encode' policy).")

            # Re-use our existing validator for each param
            try:
                for key, value in encoder_params.items():
                    validate_encoder_param(detected_encoder, key, str(value))
            except ValueError as e:
                # Re-raise with more context
                raise ValueError(f"Invalid parameter in '{detected_encoder}.encoder_params': {e}")
        else:
            # This is a critical failure for batch mode if encoding.
            raise ValueError(f"Profile is missing required section for detected encoder: '{detected_encoder}' (required for 'encode' policy).")

    # If policy is 'passthrough', skip encoder validation.

    # 2. Validate Audio Selection
    audio_sel = profile_data.get('audio_selection')
    if audio_sel:
        if not isinstance(audio_sel, dict):
            raise ValueError("'audio_selection' must be a dictionary.")
        _validate_selection_block(audio_sel, "audio_selection")

    # 3. Validate Subtitle Selection
    sub_sel = profile_data.get('subtitle_selection')
    if sub_sel:
        if not isinstance(sub_sel, dict):
            raise ValueError("'subtitle_selection' must be a dictionary.")
        _validate_selection_block(sub_sel, "subtitle_selection")

    # 4. Validate Cleanup Policy
    cleanup = profile_data.get('cleanup_policy')
    if cleanup:
        if not isinstance(cleanup, dict):
            raise ValueError("'cleanup_policy' must be a dictionary.")

        auto_clean = cleanup.get('auto_cleanup_temp_video')
        if auto_clean is not None and not isinstance(auto_clean, bool):
            raise ValueError("'cleanup_policy.auto_cleanup_temp_video' must be true or false.")

        final_clean = cleanup.get('final_cleanup')
        valid_policies = ['on_success', 'always', 'never', 'ask']
        if final_clean is not None and final_clean not in valid_policies:
            raise ValueError(f"'cleanup_policy.final_cleanup' must be one of {valid_policies}.")

    # 5. Validate Logging
    logging = profile_data.get('logging')
    if logging:
        if not isinstance(logging, dict):
            raise ValueError("'logging' must be a dictionary.")
        log_file = logging.get('log_to_file')
        if log_file is not None and not isinstance(log_file, bool):
             raise ValueError("'logging.log_to_file' must be true or false.")

    # If we got here, all checks passed.
    print_info("Profile.json structure and parameters validated successfully.")
    return True

### Helper function for interactive, language-based track selection
def _configure_internal_tracks(
    stream_type: str, # "audio" or "subtitle"
    available_streams: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Interactively asks the user which languages to keep for a track type.
    Handles multiple tracks per language by asking for clarification.
    Returns: A list of selected stream objects.
    """

    selected_streams = []

    if not available_streams:
        print_info(f"No internal {stream_type} streams found in the source file.")
        return []

    # 1. Get and display unique languages
    unique_langs = get_unique_languages(available_streams)
    print_k(f"\nFound {stream_type} streams in these languages:", bold=True)
    print_info(f"  {', '.join(lang.upper() for lang in unique_langs)}")

    chosen_langs = [] # This will hold the validated list of languages

    # Loop until a valid choice is made
    while True:
        # 2. Ask user for selection
        prompt = f"Enter {stream_type} languages to keep (e.g., eng,jpn) [ALL]:\n" \
                 f"  (Type 'ALL' for all languages, 'NONE' to skip)\n" \
                 f"  Your choice: "
        choice_str = input_k(prompt).strip().lower() or "all"

        # --- Process the choice ---

        if choice_str == 'none':
            print_info(f"Skipping all internal {stream_type} tracks.")
            return [] # Valid choice: return empty list

        if choice_str == 'all':
            chosen_langs = unique_langs
            break # Valid choice: proceed with all languages

        # User entered a specific list. We must parse and validate it.
        parsed_langs = [
            lang for lang in re.split(r'[,\s]+', choice_str) if lang
        ]

        valid_chosen_langs = []
        for lang in parsed_langs:
            if lang in unique_langs:
                valid_chosen_langs.append(lang)
            else:
                print_warn(f"Language '{lang}' not found in source. Skipping it.")

        if not valid_chosen_langs:
            # No valid languages were found in the user's input.
            print_error(f"No valid languages were selected from your input: '{choice_str}'")
            print_warn("Please try again, or type 'NONE' to skip.")
            # 'continue' will repeat the 'while True' loop
            continue
        else:
            # At least one valid language was found.
            chosen_langs = valid_chosen_langs
            break # Valid choice: proceed with the filtered list

    # If we are here, 'chosen_langs' contains a non-empty list of valid languages.

    print_info(f"Processing selected languages: {', '.join(lang.upper() for lang in chosen_langs)}")

    # 3. Iterate and select streams for each chosen language
    for lang in chosen_langs:

        streams_for_this_lang = [
            s for s in available_streams
            if s.get('tags', {}).get('language', 'und') == lang
        ]

        if not streams_for_this_lang:
            continue # Should not happen, but safe

        elif len(streams_for_this_lang) == 1:
            selected_stream = streams_for_this_lang[0]
            print_info(f"  -> Automatically adding the only {lang.upper()} {stream_type} track.")
            selected_streams.append(selected_stream)

        else:
            # select_stream now returns a LIST (empty, 1 item, or all items)
            selected_streams_for_lang = select_stream(
                stream_list=streams_for_this_lang,
                description=f"{lang.upper()} {stream_type} track",
                allow_skip=True
            )

            # Use .extend() to add all items from the returned list
            if selected_streams_for_lang:
                selected_streams.extend(selected_streams_for_lang)

    return selected_streams

def _ask_encoder_params(encoder_type: str) -> (Dict, bool):
    """
    Helper function: Asks for quality, preset, and cleanup options.
    Uses immediate validation for each parameter.
    Returns (dict_of_params, should_cleanup)
    """
    encoder_params = {}
    auto_cleanup = True

    if encoder_type == 'nvenc':

        # --- CQ Loop ---
        while True:
            try:
                print_info("Configuring for Nvidia (hevc_nvenc)...")
                print_warn("Note: Higher CQ = lower quality, lower file size.")
                cq_input = input_k("Enter NVENC CQ level (e.g., 16 for 4K) [16]: ") or "16"

                validate_encoder_param(encoder_type, 'cq', cq_input)
                encoder_params['cq'] = cq_input
                break # Succeeded, exit CQ loop
            except ValueError as e:
                print_error(f"Parameter error: {e}")
                print_warn("Please try again.")

        # --- Preset Loop ---
        while True:
            try:
                print_warn("Preset Info: p1 (fastest, lowest quality) -> p7 (slowest, best quality)")
                preset_input = input_k("Enter NVENC Preset (p1-p7) [p7]: ") or "p7"

                validate_encoder_param(encoder_type, 'preset', preset_input)
                encoder_params['preset'] = preset_input
                break # Succeeded, exit Preset loop
            except ValueError as e:
                print_error(f"Parameter error: {e}")
                print_warn("Please try again.")

    elif encoder_type == 'amf':

        # --- QP Loop ---
        while True:
            try:
                print_info("Configuring for AMD (hevc_amf)...")
                print_warn("Note: Higher QP = lower quality, lower file size.")
                qp_input = input_k("Enter AMF QP level (e.g., 22 for 4K) [22]: ") or "22"

                validate_encoder_param(encoder_type, 'qp', qp_input)
                encoder_params['qp'] = qp_input
                break
            except ValueError as e:
                print_error(f"Parameter error: {e}")
                print_warn("Please try again.")

        # --- Quality Loop ---
        while True:
            try:
                print_warn("Preset Info: 'speed' (fastest) -> 'balanced' -> 'quality' (slowest)")
                quality_input = input_k("Enter AMF Preset (quality, balanced, speed) [quality]: ") or "quality"

                validate_encoder_param(encoder_type, 'quality', quality_input)
                encoder_params['quality'] = quality_input
                break
            except ValueError as e:
                print_error(f"Parameter error: {e}")
                print_warn("Please try again.")

    # This part is outside the loops, only runs after successful validation
    cleanup_input = input_k("Delete the large 'temp_video' (raw video extract) as soon as it's no longer needed (saves space)? [Y/n]: ")
    auto_cleanup = cleanup_input.lower() != 'n'

    return encoder_params, auto_cleanup

def generate_plex_friendly_name(source_filename: str, config: Dict) -> str:
    """
    Generates a clean filename based on source filename and config.
    """
    # Get filename without path
    base_name_with_ext = os.path.basename(source_filename)
    # Get filename without extension
    base_name, _ = os.path.splitext(base_name_with_ext)

    # First, strip all existing [square bracket] tags
    # This cleans up filenames that are being re-processed *before* parsing.
    # e.g., "Movie (2008) [Old Tag]" -> "Movie (2008)"
    clean_base = re.sub(r'\[.*?\]', '', base_name).strip()

    # Now, parse the *clean* base for title and year
    year_match = re.search(r'(19|20)\d{2}', clean_base)
    title = ""
    year_str = ""

    if year_match:
        year_str = f"({year_match.group(0)})"

        # Get the part before the year
        title_raw = clean_base[:year_match.start()]

        # Strip all trailing punctuation (fixes the "( " bug from punctuation)
        title = title_raw.rstrip(string.punctuation + string.whitespace)

        # If title is empty after stripping (e.g., "(2008).mkv"), fallback
        if not title:
             # Fallback to the original base name (minus extension)
             # and just clean dots/underscores
             title_raw, _ = os.path.splitext(base_name)
             # re-clean, but only dots/spaces, leave year
             title = re.sub(r'[._]', ' ', title_raw).strip()
             # We might get "Movie 2008" here, but year_str will be added later

    else:
        # No year found, just use the (already cleaned) base name
        title = clean_base

    # Clean the title (replace dots, remove extra spaces)
    # This catches "Movie.Name.2023" case
    title = re.sub(r'[._]', ' ', title).strip()
    title = re.sub(r'\s+', ' ', title)

    # --- Build quality tags ---
    quality_tags = []
    height = config['video_stream'].get('height')
    width = config['video_stream'].get('width') # Get width too

    if width and height:
        if width >= 3800 or height >= 2100: # Prioritize width for 4K, fallback to height
             quality_tags.append("2160p")
        elif width >= 1900 or height >= 1000: # Prioritize width for 1080p
             quality_tags.append("1080p")
        elif width >= 1200 or height >= 700: # Prioritize width for 720p
             quality_tags.append("720p")

    if config.get('video_policy') == 'passthrough':
        # Determine source codec for the tag
        source_codec = config['video_stream'].get('codec_name', 'COPY')
        if 'hevc' in source_codec or 'h265' in source_codec:
            quality_tags.append("HEVC")
        elif 'avc' in source_codec or 'h264' in source_codec:
             quality_tags.append("H.264")
        elif 'vp9' in source_codec:
             quality_tags.append("VP9")
        # Add other codecs if needed

        quality_tags.append("REMUX")
    else: # Encode mode
        quality_tags.append("HEVC") # We always encode to HEVC
        if config['encoder'] == 'nvenc' and 'cq' in config['encoder_params']:
            quality_tags.append(f"CQ{config['encoder_params']['cq']}")
        elif config['encoder'] == 'amf' and 'qp' in config['encoder_params']:
            quality_tags.append(f"QP{config['encoder_params']['qp']}")

    if config['has_dv']:
        quality_tags.append("DV")

    quality_str = f"[{' '.join(quality_tags)}]"

    # --- Assemble final name ---

    # Prevent double year if title somehow still contains it
    if year_str and year_str in title:
        final_name_base = f"{title}"
    else:
        final_name_base = f"{title} {year_str}"

    # Clean up excess spaces that might result from assembly
    final_name_base = re.sub(r'\s+', ' ', final_name_base).strip()

    final_name = f"{final_name_base} {quality_str}.mkv".strip()

    # Final cleanup for safety
    final_name = re.sub(r'\s+', ' ', final_name)
    final_name = re.sub(r'[<>:"/\\|?*]', '', final_name)

    return final_name

def configure_full_run(
    streams: Dict[str, Any],
    source_file: str,
    output_dir: str,
    source_duration: Optional[float],
    encoder_type: str,
    profile_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """Gathers settings for a full conversion (INTERACTIVE)."""
    # If profile_data is provided, it was already validated by main()

    config = {
        'audio_tracks': [],
        'subtitle_tracks': [],
        'external_audio_files': [],
        'external_subtitle_files': [],
        'has_dv': streams['has_dv'],
        'dv_profile': streams.get('dv_profile'),
        'final_filename': "",
        'video_stream': streams['video'][0],
        'default_audio_index': 0,
        'default_subtitle_index': -1,
        'encoder': encoder_type,
        'encoder_params': {},
        'auto_cleanup_temp_video': True, # Default for encode, ignored for passthrough
        'final_cleanup_policy': 'ask',
        'hdr10_master_display': streams.get('hdr10_master_display'),
        'hdr10_cll_fall': streams.get('hdr10_cll_fall'),
        'video_policy': 'encode',
        'passthrough_convert_dv_to_p8': False
    }

    print_header("Step 2: Configure Full Conversion (Interactive)")

    # Ask for video policy ---
    while True:
        print_k("\nSelect video processing mode:", bold=True)
        print("  1. Encode (re-encode video, WARNING: this process will lose HDR10+ metadata, if present)")
        print("  2. Passthrough (copy video stream, WARNING: this process will preserve HDR10+ metadata, if present)")
        mode_choice = input_k("Choice [1]: ", Kolory.OKCYAN) or "1"
        if mode_choice == "1":
            config['video_policy'] = 'encode'
            print_info("Selected mode: Encode")
            break
        elif mode_choice == "2":
            config['video_policy'] = 'passthrough'
            print_info("Selected mode: Passthrough (Remux)")
            # In passthrough, encoder params & temp video cleanup are irrelevant
            config['encoder_params'] = {}
            config['auto_cleanup_temp_video'] = False

            # --- DV Profile Conversion Logic ---
            dv_profile = config.get('dv_profile')
            dv_profile_str = str(dv_profile) if dv_profile is not None else "None"

            # --- Case 1: Profile 7 ---
            # Conversion (P7 -> P8.1) is possible and recommended for compatibility.
            if dv_profile_str == '7':
                print_warn(f"Detected Dolby Vision Profile 7, which may not be compatible with all players.")
                print_warn("Selecting 'No' (keeping P7) is only recommended for advanced players (e.g., Nvidia Shield).")
                print_info("If your player *only* supports HDR10+ (and not DV P7), both options should work, but selecting 'No' will be faster.")
                choice = input_k("Do you want to convert this profile to compatible Profile 8? (preserves HDR10+, recommended) [Y/n]: ")

                if choice.lower() != 'n':
                    config['passthrough_convert_dv_to_p8'] = True
                    print_info("OK: DV Profile 7 will be converted to 8 during passthrough.")
                else:
                    config['passthrough_convert_dv_to_p8'] = False
                    print_info(f"OK: DV Profile 7 will be passed through without conversion.")

            # --- Case 2: Profile 5 ---
            # Conversion (P5 -> P8) is technically possible but known to CORRUPT video with current tools.
            elif dv_profile_str == '5':
                print_warn(f"Detected Dolby Vision Profile 5!")
                print_warn(f"This profile uses an incompatible color matrix (IPT-PQ-C2).")
                print_warn(f"Current tools **FAIL** to convert this profile's colors correctly.")
                print_warn(f"Attempting conversion ('Yes') WILL LIKELY CORRUPT the video output (purple/green artifacts).")
                print_info(f"Selecting 'No' (Pure Passthrough) is the ONLY SAFE option to avoid corrupting the video during processing.")
                choice = input_k("Do you still want to attempt conversion to Profile 8 (NOT RECOMMENDED, likely corrupts video)? [y/N]: ")

                if choice.lower() == 'y':
                    # User explicitly chose the dangerous option
                    config['passthrough_convert_dv_to_p8'] = True
                    print_warn("WARNING: Proceeding with Profile 5 conversion despite incompatibility. Output may be corrupted.")
                else:
                    # Default and safe option
                    config['passthrough_convert_dv_to_p8'] = False
                    print_info(f"OK: DV Profile 5 will be passed through without conversion (Pure Passthrough).")
                    print_warn("Output file retains Profile 5 (IPT-PQ-C2) and requires compatible playback hardware (e.g., Shield).")

            # --- Case 3: Profile 8 (Already compatible) ---
            elif dv_profile_str == '8':
                print_info("Detected compatible Dolby Vision Profile 8. No conversion needed.")
                # Ensure flag is off, just in case
                config['passthrough_convert_dv_to_p8'] = False

            # --- Case 4: No DV or Unsupported ---
            else:
                print_info("No DV profile (or unsupported P4) detected. No conversion needed.")
                # Ensure flag is off
                config['passthrough_convert_dv_to_p8'] = False
            # --- END DV Profile Conversion Logic ---

            # Passthrough mode selected, now break the main loop
            break # Exit the 'while True:' loop for video policy selection
        else:
            print_warn("Invalid choice. Please enter 1 or 2.")

    loaded_from_profile = False
    if profile_data:
        # Load cleanup policy (always load this)
        cleanup_profile = profile_data.get('cleanup_policy', {})
        config['auto_cleanup_temp_video'] = cleanup_profile.get('auto_cleanup_temp_video', True)
        if 'final_cleanup' in cleanup_profile:
            config['final_cleanup_policy'] = cleanup_profile['final_cleanup']

        # --- Load encoder settings ONLY if policy is 'encode' ---
        if config['video_policy'] == 'encode':
            # We assume profile is valid due to global validation
            config['encoder_params'] = profile_data[encoder_type]['encoder_params']
            params_str = ", ".join(f"{k}={v}" for k, v in config['encoder_params'].items())
            cleanup_str = "Yes" if config['auto_cleanup_temp_video'] else "No"
            final_cleanup_str = config.get('final_cleanup_policy', 'ask')
            print_info(f"Loaded profile settings for '{encoder_type}': {params_str}")
            print_info(f"Loaded cleanup policy: Auto-cleanup temp video={cleanup_str}, Final cleanup={final_cleanup_str}")
            loaded_from_profile = True # Mark as loaded only if we actually loaded encoder params
        else:
            # Policy is passthrough, even if profile exists, don't load encoder params
            print_info("Passthrough mode selected, skipping profile encoder settings.")

    # --- Ask interactively ONLY if policy is 'encode' AND not loaded from profile ---
    if config['video_policy'] == 'encode' and not loaded_from_profile:
        # Ask for params interactively
        params, cleanup = _ask_encoder_params(encoder_type)
        config['encoder_params'] = params
        config['auto_cleanup_temp_video'] = cleanup
    elif config['video_policy'] == 'passthrough':
         print_info("Passthrough mode selected, skipping interactive encoder configuration.")

    # --- Filename Logic ---
    suggested_name = generate_plex_friendly_name(source_file, config)
    prompt = f"Enter the final output filename [{suggested_name}]: "
    user_filename = input_k(prompt)
    chosen_filename = user_filename or suggested_name

    sane_filename = sanitize_filename(chosen_filename)
    if sane_filename != chosen_filename:
        print_warn(f"Filename was sanitized for safety:")
        print_info(f"  Original: {chosen_filename}")
        print_info(f"  Cleaned:  {sane_filename}")
        chosen_filename = sane_filename

    unique_filename = get_unique_filename(output_dir, chosen_filename)

    if unique_filename != chosen_filename:
        print_warn(f"File '{chosen_filename}' already exists.")
        config['final_filename'] = unique_filename
        print_info(f"Using new unique name: {unique_filename}")
    else:
        config['final_filename'] = chosen_filename

    # ### Internal Audio Selection ###
    print_k("\n--- Audio Configuration ---", Kolory.OKCYAN)
    if input_k("Process internal audio tracks from source file? [Y/n]: ").lower() != 'n':
        config['audio_tracks'] = _configure_internal_tracks(
            stream_type="audio",
            available_streams=streams['audio']
        )

    # ### External Audio Selection ###
    else:
        print_info("Configuring external audio tracks.")
        while True:
            path = input_k("Enter path to external audio file (or 'd' for done): ").strip().strip("'\"")
            if path.lower() == 'd':
                break
            if not os.path.exists(path):
                print_warn("File not found. Please try again.")
                continue
            should_continue = True
            if source_duration:
                ext_duration = get_file_duration(path)
                if ext_duration:
                    if abs(ext_duration - source_duration) > 1.0:
                        print_warn(f"WARNING: Video is {source_duration:.2f}s, but this audio is {ext_duration:.2f}s.")
                        if input_k("Continue anyway? [y/N]: ").lower() != 'y':
                            should_continue = False
                else:
                    print_warn(f"WARNING: Could not determine the duration of the external file '{os.path.basename(path)}'.")
                    print_warn("It might be out of sync.")
                    if input_k("Do you want to use it anyway? [y/N]: ").lower() != 'y':
                        should_continue = False
            if not should_continue:
                print_info("File discarded.")
                continue
            lang = input_k("Enter language code (e.g., pol, eng) [und]: ") or 'und'
            title = input_k("Enter track title [External Audio]: ") or 'External Audio'
            config['external_audio_files'].append({'path': path, 'lang': lang, 'title': title})
            print_info("Added external audio track.")

    # ### Internal Subtitle Selection ###
    print_k("\n--- Subtitle Configuration ---", Kolory.OKCYAN)
    if input_k("Process internal subtitle tracks from source file? [Y/n]: ").lower() != 'n':
        config['subtitle_tracks'] = _configure_internal_tracks(
            stream_type="subtitle",
            available_streams=streams['subtitle']
        )

    # ### External Subtitle Selection ###
    else:
        print_info("Configuring external subtitle files.")
        while True:
            path = input_k("Enter path to external subtitle file (or 'd' for done): ").strip().strip("'\"")
            if path.lower() == 'd':
                break
            if not os.path.exists(path):
                print_warn("File not found. Please try again.")
                continue
            should_continue = True
            if source_duration:
                ext_duration = get_file_duration(path)
                if ext_duration:
                    if abs(ext_duration - source_duration) > 1.0:
                        print_warn(f"WARNING: Video is {source_duration:.2f}s, but this subtitle is {ext_duration:.2f}s.")
                        if input_k("Continue anyway? [y/N]: ").lower() != 'y':
                            should_continue = False
                else:
                    print_warn(f"WARNING: Could not determine the duration of the external file '{os.path.basename(path)}'.")
                    print_warn("It might be out of sync.")
                    if input_k("Do you want to use it anyway? [y/N]: ").lower() != 'y':
                        should_continue = False
            if not should_continue:
                print_info("File discarded.")
                continue
            lang = input_k("Enter language code (e.g., pol) [pol]: ") or 'pol'
            title = input_k("Enter track title [Polish Subtitle]: ") or 'Polish Subtitle'
            config['external_subtitle_files'].append({'path': path, 'lang': lang, 'title': title})
            print_info("Added external subtitle file.")

    # --- Default Track Selection ---
    print_k("\n--- Default Track Selection ---", Kolory.OKCYAN)

    all_audio_tracks = config['audio_tracks'] + config['external_audio_files']
    if len(all_audio_tracks) > 1:
        print_k("Select default AUDIO track:", bold=True)
        for i, track in enumerate(all_audio_tracks):
            if 'codec_name' in track:
                desc = format_stream_description(track)
            else:
                desc = f"[Ext.] {track['lang'].upper()} - {track['title']}"
            print(f"  {i+1}. {desc}")

        while True:
            try:
                choice_str = input_k(f"Your choice (1-{len(all_audio_tracks)}) [1]: ") or "1"
                choice_idx = int(choice_str) - 1
                if 0 <= choice_idx < len(all_audio_tracks):
                    config['default_audio_index'] = choice_idx
                    break
                print_warn("Invalid choice.")
            except ValueError:
                print_warn("Please enter a number.")

    all_subtitle_tracks = config['subtitle_tracks'] + config['external_subtitle_files']
    if len(all_subtitle_tracks) > 0:
        print_k("Select default SUBTITLE track:", bold=True)
        print("  0. None (No default subtitles)")
        for i, track in enumerate(all_subtitle_tracks):
            if 'codec_name' in track:
                desc = format_stream_description(track)
            else:
                desc = f"[Ext.] {track['lang'].upper()} - {track['title']}"
            print(f"  {i+1}. {desc}")

        while True:
            try:
                choice_str = input_k(f"Your choice (0-{len(all_subtitle_tracks)}) [0]: ") or "0"
                choice = int(choice_str)

                if choice == 0:
                    config['default_subtitle_index'] = -1
                    break
                elif 1 <= choice <= len(all_subtitle_tracks):
                    config['default_subtitle_index'] = choice - 1
                    break
                print_warn("Invalid choice.")
            except ValueError:
                print_warn("Please enter a number.")

    return config

def configure_extraction(streams: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Gathers settings for extraction mode."""
    print_header("Step 2: Configure Stream Extraction")

    print_k("What type of stream do you want to extract?", bold=True)
    print("  1. Audio track")
    print("  2. Subtitle track")
    print("  3. Video track (no conversion)")

    while True:
        mode_extract = input_k("Choice (1-3): ")
        if mode_extract == "1":
            list_to_show = streams['audio']
            desc = "audio track"
            break
        elif mode_extract == "2":
            list_to_show = streams['subtitle']
            desc = "subtitle track"
            break
        elif mode_extract == "3":
            list_to_show = streams['video']
            desc = "video track"
            break
        print_warn("Invalid choice.")

    # Call select_stream, explicitly disabling "ALL"
    # select_stream will now return a list, e.g., [stream_object]
    selected_streams = select_stream(
        list_to_show,
        desc,
        allow_skip=False,
        allow_all=False # Explicitly disable "ALL"
    )

    if not selected_streams:
        # This shouldn't happen with allow_skip=False, but it's safe
        return None

    # Unpack the list to get the single stream dictionary
    stream_to_extract = selected_streams[0]

    codec_type = stream_to_extract.get('codec_type')
    codec_name = stream_to_extract.get('codec_name', 'bin')

    if codec_type == 'audio':
        ext = 'mka'
    elif codec_type == 'subtitle':
        if codec_name == 'hdmv_pgs_subtitle': ext = 'sup'
        elif codec_name == 'subrip': ext = 'srt'
        else: ext = 'mks'
    elif codec_type == 'video':
        if 'hevc' in codec_name: ext = 'hevc'
        elif 'h264' in codec_name or 'avc' in codec_name: ext = 'h264'
        else: ext = 'mkv'
    else:
        ext = 'bin'

    default_name = f"extract_idx{stream_to_extract['index']}.{ext}"
    filename = input_k(f"Enter output filename [default: {default_name}]: ") or default_name

    return {
        'stream': stream_to_extract,
        'output_filename': filename
    }

# --- Phase 2b: Automated Configuration (Batch Mode) ---

def find_best_tracks(
    available_streams: List[Dict],
    policy: Dict
) -> (List[Dict], List[int]):
    """
    Selects streams based on a profile policy.
    Handles 'policy: "best_per_language"' and 'policy: "all"'.
    Warns on missing specified languages.
    Returns (list_of_selected_streams, list_of_default_indices)
    """
    selected_streams = []
    default_indices = []

    # Get codec preferences (weights)
    codec_prefs = policy.get('preferred_codecs', [])
    codec_score = {codec: (len(codec_prefs) - i) for i, codec in enumerate(codec_prefs)}

    # Get exclusion rules
    exclusions = policy.get('exclude_titles_containing', [])

    # Get the defined policy type
    policy_type = policy.get('policy', 'best_per_language')
    default_lang = policy.get('default_track_language')

    if policy_type == 'all':
        # --- POLICY "ALL" ---
        print_info(f"Policy is 'all'. Selecting all {len(available_streams)} available tracks.")
        selected_streams = available_streams # Simply select all

        # We still respect the default_track_language
        if default_lang:
            for i, stream in enumerate(selected_streams):
                lang = stream.get('tags', {}).get('language', 'und')
                if lang == default_lang:
                    default_indices.append(i)
                    # Stop at the first match for the default lang
                    # (respecting subtitle 'default_mode: "first"')
                    break

    elif policy_type == 'best_per_language':
        # --- POLICY "BEST_PER_LANGUAGE" ---

        # Get the raw language policy from profile.json
        policy_languages = policy.get('languages', [])

        # Get all languages actually present in the file
        available_langs_list = get_unique_languages(available_streams)
        available_langs_set = set(available_langs_list)

        languages_to_process = []

        if policy_languages == "all":
            print_info("Profile policy is 'best_per_language' for 'all' languages.")
            languages_to_process = available_langs_list # Use the sorted list

        elif isinstance(policy_languages, list):
            print_info(f"Profile requests languages: {', '.join(policy_languages)}")
            for lang in policy_languages:
                if lang in available_langs_set:
                    languages_to_process.append(lang)
                else:
                    print_warn(f"Language '{lang.upper()}' (from profile) was NOT found in this file. Skipping it.")
        else:
            print_error(f"Invalid 'languages' format in profile. Must be a list (e.g., ['eng']) or the string 'all'.")
            return [], []

        if not languages_to_process:
            print_info("No languages left to process after filtering.")
            return [], []

        print_info(f"Will process tracks for: {', '.join(lang.upper() for lang in languages_to_process)}")

        # Loop through our validated list
        for lang in languages_to_process:
            best_stream_for_lang = None
            best_score = -1

            # Find all streams for this language
            streams_for_this_lang = [
                s for s in available_streams
                if s.get('tags', {}).get('language', 'und') == lang
            ]

            for stream in streams_for_this_lang:
                # Check for title exclusions (e.g., "commentary")
                title = stream.get('tags', {}).get('title', '').lower()
                excluded = False
                for exclusion in exclusions:
                    if exclusion.lower() in title:
                        print_info(f"Excluding stream (lang: {lang}, title: '{title}') due to exclusion rule: '{exclusion}'")
                        excluded = True
                        break
                if excluded:
                    continue

                # Score the stream based on codec preferences
                codec_name = stream.get('codec_name', 'unknown')
                current_score = codec_score.get(codec_name, 1)

                if current_score > best_score:
                    best_score = current_score
                    best_stream_for_lang = stream

            if best_stream_for_lang:
                selected_streams.append(best_stream_for_lang)
                # Check if this language should be the default track
                if lang == default_lang:
                    default_indices.append(len(selected_streams) - 1)

    else:
        # --- FALLBACK ---
        print_warn(f"Unknown selection policy: {policy_type}. Cannot process tracks.")
        return [], []

    return selected_streams, default_indices

def configure_automated_run(
    streams: Dict[str, Any],
    source_file: str,
    output_dir: str,
    source_duration: Optional[float],
    encoder_type: str,
    profile_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Gathers settings for an automated conversion from a profile."""
    # Profile has already been validated by validate_profile_globally() in main()

    print_header("Step 2: Configure Automated Conversion")

    config = {
        'audio_tracks': [],
        'subtitle_tracks': [],
        'external_audio_files': [],
        'external_subtitle_files': [],
        'has_dv': streams['has_dv'],
        'dv_profile': streams.get('dv_profile'),
        'final_filename': "",
        'video_stream': streams['video'][0],
        'default_audio_index': 0,
        'default_subtitle_index': -1,
        'encoder': encoder_type,
        'encoder_params': {},
        'auto_cleanup_temp_video': True,
        'final_cleanup_policy': 'on_success',
        'hdr10_master_display': streams.get('hdr10_master_display'),
        'hdr10_cll_fall': streams.get('hdr10_cll_fall'),
        'video_policy': 'encode',
        'passthrough_convert_dv_to_p8': False
    }

    # 0. Video Policy
    config['video_policy'] = profile_data.get('video_policy', 'encode')
    print_info(f"Video policy from profile: '{config['video_policy']}'")

    # --- Read hybrid passthrough flag ---
    if config['video_policy'] == 'passthrough':
        config['passthrough_convert_dv_to_p8'] = profile_data.get('passthrough_convert_dv_to_p8', False)
        if config['passthrough_convert_dv_to_p8']:
            print_info("Hybrid Passthrough enabled: DV P5/P7 will be converted to P8.")

    # 1. Encoder Settings (Conditional)
    if config['video_policy'] == 'encode':
        config['encoder_params'] = profile_data[encoder_type]['encoder_params']
        params_str = ", ".join(f"{k}={v}" for k, v in config['encoder_params'].items())
        print_info(f"Loaded validated profile settings for '{encoder_type}': {params_str}")
    else:
        # Passthrough mode, clear encoder params
        config['encoder_params'] = {}
        print_info("Passthrough mode: Encoder settings ignored.")

    # 2. Cleanup Settings
    cleanup_policy = profile_data.get('cleanup_policy', {})
    config['auto_cleanup_temp_video'] = cleanup_policy.get('auto_cleanup_temp_video', True)
    config['final_cleanup_policy'] = cleanup_policy.get('final_cleanup', 'on_success')
    print_info(f"Cleanup policy: Auto-delete temp video={config['auto_cleanup_temp_video']}, Final cleanup={config['final_cleanup_policy']}")

    # 3. Audio Selection (Automated)
    audio_policy = profile_data.get('audio_selection')
    if audio_policy:
        selected_audio, default_audio_indices = find_best_tracks(streams['audio'], audio_policy)
        config['audio_tracks'] = selected_audio
        if default_audio_indices:
            config['default_audio_index'] = default_audio_indices[0]
        elif selected_audio:
            config['default_audio_index'] = 0

        print_info(f"Selected {len(config['audio_tracks'])} audio track(s) based on profile.")
        for i, track in enumerate(config['audio_tracks']):
             print_k(f"  -> Audio {i}: {format_stream_description(track)}")
    else:
        print_warn("No 'audio_selection' policy in profile. No audio will be included.")

    # 4. Subtitle Selection (Automated)
    subtitle_policy = profile_data.get('subtitle_selection')
    if subtitle_policy:
        selected_subs, default_sub_indices = find_best_tracks(streams['subtitle'], subtitle_policy)
        config['subtitle_tracks'] = selected_subs

        default_sub_mode = subtitle_policy.get('default_mode', 'none')
        if default_sub_indices:
            config['default_subtitle_index'] = default_sub_indices[0]
        elif default_sub_mode == 'first' and selected_subs:
            config['default_subtitle_index'] = 0
        else:
            config['default_subtitle_index'] = -1

        print_info(f"Selected {len(config['subtitle_tracks'])} subtitle track(s) based on profile.")
        for i, track in enumerate(config['subtitle_tracks']):
             print_k(f"  -> Subtitle {i}: {format_stream_description(track)}")
    else:
        print_info("No 'subtitle_selection' policy in profile. No subtitles will be included.")

    # 5. Filename
    generated_name = generate_plex_friendly_name(source_file, config)
    unique_filename = get_unique_filename(output_dir, generated_name)

    if unique_filename != generated_name:
        print_warn(f"File '{generated_name}' already exists in output directory.")
        config['final_filename'] = unique_filename
        print_info(f"Using new unique name: {unique_filename}")
    else:
        config['final_filename'] = generated_name

    print_info(f"Final output filename set to: {config['final_filename']}")

    return config

# --- Phase 3: Process Execution ---

def run_extraction(
    source_file: str,
    output_dir: str,
    config: Dict[str, Any]
):
    """Performs a simple stream extraction. No cleanup."""
    print_header("Starting Stream Extraction")

    stream = config['stream']
    output_path = os.path.join(output_dir, config['output_filename'])
    map_index = stream['index']

    print_info(f"Extracting track {map_index} to {output_path}")
    cmd = [
        'mkvextract', 'tracks', source_file,
        f'{map_index}:{output_path}'
    ]

    try:
        run_command(cmd)
        print_k(f"\nSuccess! Stream saved to: {output_path}", Kolory.OKGREEN, bold=True)
    except Exception as e:
        print_error(f"Extraction failed: {e}")

def create_hdr_tags_xml(output_dir: str, file_basename: str, hdr10_master_display: Optional[str], hdr10_cll_fall: Optional[str]) -> Optional[str]:
    """
    Generates the content for hdr_tags.xml file based on parsed HDR metadata.
    Returns the path to the created XML file or None if no HDR data is available.
    """
    if not hdr10_master_display and not hdr10_cll_fall:
        print_info("No HDR10 metadata found, skipping XML tag file generation.")
        return None

    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<Tags>
  <Tag>
    <Targets /> """
    mastering_meta_string = None
    max_cll_string = None
    max_fall_string = None

    # --- Parse Mastering Display ---
    if hdr10_master_display:
        print_info("Parsing Mastering Display metadata for XML.")
        try:
            # Regex to extract G(gx,gy)B(bx,by)R(rx,ry)WP(wx,wy)L(maxl,minl)
            pattern = re.compile(
                r"G\((\d+\.\d+),(\d+\.\d+)\)"
                r"B\((\d+\.\d+),(\d+\.\d+)\)"
                r"R\((\d+\.\d+),(\d+\.\d+)\)"
                r"WP\((\d+\.\d+),(\d+\.\d+)\)"
                r"L\((\d+\.\d+),(\d+\.\d+)\)"
            )
            match = pattern.search(hdr10_master_display)
            if match:
                gx, gy, bx, by, rx, ry, wpx, wpy, maxl, minl = map(float, match.groups())
                # Scale according to Matroska specification (EBML V4 / libmatroska v1.7.1)
                # Primaries/WhitePoint need x50000, Luminance needs x10000
                gx_i, gy_i = int(gx * 50000), int(gy * 50000)
                bx_i, by_i = int(bx * 50000), int(by * 50000)
                rx_i, ry_i = int(rx * 50000), int(ry * 50000)
                wpx_i, wpy_i = int(wpx * 50000), int(wpy * 50000)
                maxl_i, minl_i = int(maxl * 10000), int(minl * 10000)

                mastering_meta_string = (
                    f"G({gx_i},{gy_i})"
                    f"B({bx_i},{by_i})"
                    f"R({rx_i},{ry_i})"
                    f"WP({wpx_i},{wpy_i})"
                    f"L({maxl_i},{minl_i})"
                )
                xml_content += f"""    <Simple>
      <Name>MASTERING_METADATA</Name>
      <String>{mastering_meta_string}</String>
    </Simple>
"""
            else:
                print_warn("Could not parse mastering display string with regex.")
        except Exception as e:
            print_warn(f"Error parsing mastering display metadata: {e}")

    # --- Parse MaxCLL / MaxFALL ---
    if hdr10_cll_fall:
        print_info("Parsing Content Light Level metadata for XML.")
        try:
            cll, fall = map(int, hdr10_cll_fall.split(','))
            if cll > 0:
                max_cll_string = str(cll)
                xml_content += f"""    <Simple>
      <Name>MAX_CLL</Name>
      <String>{max_cll_string}</String>
    </Simple>
"""
            if fall > 0:
                max_fall_string = str(fall)
                xml_content += f"""    <Simple>
      <Name>MAX_FALL</Name>
      <String>{max_fall_string}</String>
    </Simple>
"""
        except Exception as e:
            print_warn(f"Error parsing content light level metadata: {e}")

    xml_content += """  </Tag>
</Tags>
"""

    if not mastering_meta_string and not max_cll_string and not max_fall_string:
        print_warn("Failed to parse any HDR10 metadata for XML tag file.")
        return None

    # --- Write the XML file ---
    xml_file_path = os.path.join(output_dir, f"{file_basename}_hdr_tags.xml")
    try:
        with open(xml_file_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        print_info(f"Successfully created HDR tag file: {xml_file_path}")
        return xml_file_path
    except Exception as e:
        print_error(f"Failed to write HDR tag file {xml_file_path}: {e}")
        return None

def run_full_conversion(
    source_file: str,
    output_dir: str,
    config: Dict[str, Any],
    file_basename: str
):
    """
    Executes the full conversion and muxing process, choosing the optimal
    pipeline based on the detected Dolby Vision profile.
    """

    print_header(f"Starting Full Conversion for: {file_basename}")

    sane_basename = sanitize_filename(file_basename)
    if sane_basename != file_basename:
        print_warn(f"Temporary file base name was sanitized:")
        print_info(f"  Original: {file_basename}")
        print_info(f"  Cleaned:  {sane_basename}")
        file_basename = sane_basename

    # --- Define common temporary files ---
    temp_audio_files = []
    temp_subtitle_files = []
    files_to_cleanup = [] # Will be populated based on the chosen path

    hdr_tags_xml_path: Optional[str] = None
    final_file_path = os.path.join(output_dir, config['final_filename'])

    if os.path.exists(final_file_path):
        print_warn(f"Output file already exists: {final_file_path}")
        print_warn("Skipping this file to avoid overwriting.")
        return

    try:
        # --- Common Steps: Extract Audio & Subtitles ---
        print_header("Step 1: Extracting internal audio tracks")

        if not config['audio_tracks']:
            print_info("Skipped - no internal audio tracks selected.")
        else:
            for stream in config['audio_tracks']:
                idx = stream['index']
                lang = stream.get('tags', {}).get('language', 'und')
                temp_file = os.path.join(output_dir, f"{file_basename}_temp_audio_{lang}_{idx}.mka")
                cmd_audio = ['mkvextract', 'tracks', source_file, f'{idx}:{temp_file}']
                run_command(cmd_audio)
                temp_audio_files.append({'path': temp_file, 'stream': stream})
                files_to_cleanup.append(temp_file)


        print_header("Step 2: Extracting internal subtitle tracks")

        if not config['subtitle_tracks']:
            print_info("Skipped - no internal subtitles selected.")
        else:
            for stream in config['subtitle_tracks']:
                idx = stream['index']
                lang = stream.get('tags', {}).get('language', 'und')
                codec_name = stream.get('codec_name')
                if codec_name == 'hdmv_pgs_subtitle': ext = 'sup'
                elif codec_name == 'subrip': ext = 'srt'
                else: ext = 'mks'
                temp_file = os.path.join(output_dir, f"{file_basename}_temp_sub_{lang}_{idx}.{ext}")
                cmd_subs = ['mkvextract', 'tracks', source_file, f'{idx}:{temp_file}']
                run_command(cmd_subs)
                temp_subtitle_files.append({'path': temp_file, 'stream': stream})
                files_to_cleanup.append(temp_file)


        # --- Step 3: Generating HDR10 Metadata Tags (Conditional) ---
        hdr_tags_xml_path = None
        use_hdr_tags_xml = False # Initialize flag

        if config.get('video_policy') != 'passthrough':
             # Only generate XML if we are encoding (Paths A, B, C)
             print_header("Step 3: Generating HDR10 Metadata Tags (Encode Mode)")
             hdr_tags_xml_path = create_hdr_tags_xml(
                 output_dir,
                 file_basename,
                 config.get('hdr10_master_display'),
                 config.get('hdr10_cll_fall')
             )
             if hdr_tags_xml_path:
                 files_to_cleanup.append(hdr_tags_xml_path)
             else:
                 print_info("Proceeding without HDR10 tags for final muxing.")
             # Flag will be set to True later inside Path A/C logic
        else:
             print_info("Step 3: Skipping HDR10 Metadata Tag generation (Passthrough Mode).")

        # --- Profile 5 Sanity Check ---
        # We must check for P5 before the main logic paths, as our toolchain
        # (ffmpeg/nvenc/amf and dovi_tool 2.x) cannot correctly process
        # the IPT-PQ-C2 color matrix used by Profile 5.

        original_video_policy = config.get('video_policy')
        original_convert_flag = config.get('passthrough_convert_dv_to_p8') # Store original intent
        dv_profile_str = str(config.get('dv_profile'))

        override_needed = False # Flag to track if we forced a change

        if dv_profile_str == '5':
            # Initial detection message
            print_warn(f"Dolby Vision Profile 5 detected.")
            print_warn(f"This profile's video stream uses the IPT-PQ-C2 color matrix.")

            if original_video_policy == 'encode':
                print_warn(f"Encode policy (NVENC/AMF) is INCOMPATIBLE with IPT-PQ-C2.")
                print_warn(f"The encoder **misinterprets** these colors during processing.")
                print_warn(f"This **permanently corrupts** the output video (bakes in purple/green artifacts).")
                override_needed = True

            elif original_convert_flag == True:
                 print_warn(f"Hybrid Passthrough (convert) policy is INEFFECTIVE for IPT-PQ-C2.")
                 print_warn(f"dovi_tool (v2.x) **fails to convert** the IPT-PQ-C2 colors correctly.")
                 print_warn(f"This produces a misleading Profile 8 file containing the original (misinterpreted as purple/green) video data.")
                 override_needed = True

            if override_needed:
                print_warn("OVERRIDE: Forcing 'Pure Passthrough' mode (1:1 copy) **to prevent video corruption during processing**.")
                # Force the config to use the Pure Passthrough path
                config['video_policy'] = 'passthrough'
                config['passthrough_convert_dv_to_p8'] = False
                use_hdr_tags_xml = False

                print_warn("WARNING: The final filename may still contain Encode/Convert tags, but the video stream is an unmodified Pure Passthrough copy.")

            # Covers the case where the user *already* chose Pure Passthrough for P5
            elif original_video_policy == 'passthrough' and original_convert_flag == False:
                 print_info("Profile 5 detected with 'Pure Passthrough' policy (1:1 copy) as requested.")
                 # No override needed, just proceed to the final warning

            # This warning appears for P5 regardless of override, explaining the playback issue.
            print_warn("--------------------------------------------------------------------")
            print_warn("IMPORTANT: The output file retains the **original, unmodified** Profile 5 video stream (IPT-PQ-C2).")
            print_warn("This stream **WILL APPEAR PURPLE/GREEN on most PC players and TVs** due to lack of IPT-PQ-C2 support.")
            print_warn("Correct playback requires specific compatible hardware (e.g., Nvidia Shield with appropriate player software).")
            print_warn("--------------------------------------------------------------------")

        # --- END SANITY CHECK ---

        # --- Determine Video Path (Passthrough or Encode) ---
        video_input_for_mux = ""
        map_str_for_mux = ""
        final_mux_step = ""

        if config.get('video_policy') == 'passthrough':
            # --- Check if this is a hybrid conversion passthrough ---
            dv_profile = config.get('dv_profile')
            dv_profile_str = str(dv_profile) if dv_profile is not None else "None"
            should_convert_dv = config.get('passthrough_convert_dv_to_p8', False)
            conversion_mode = None

            if should_convert_dv and dv_profile_str == '7':
                conversion_mode = "2" # P7 -> P8
            elif should_convert_dv and dv_profile_str == '5':
                conversion_mode = "3" # P5 -> P8

            if conversion_mode:
                # --- HYBRID PASSTHROUGH PATH (P7 -> P8 + HDR10+) ---
                path_name = f"Hybrid Passthrough (P{dv_profile_str} -> P8)"
                print_header(f"Step 4: ({path_name}) Extracting raw HEVC")

                temp_video_raw = os.path.join(output_dir, f"{file_basename}_temp_video_raw.hevc")
                temp_video_final_dv = os.path.join(output_dir, f"{file_basename}_temp_video_final_dv.hevc")
                files_to_cleanup.extend([temp_video_raw, temp_video_final_dv])

                video_stream_config = config.get('video_stream')
                if not video_stream_config:
                     raise ValueError("Missing video_stream configuration for hybrid passthrough.")
                map_video = video_stream_config.get('index', 0)

                # Step 4a: Extract raw HEVC
                cmd_extract_raw = ['mkvextract', 'tracks', source_file, f'{map_video}:{temp_video_raw}']
                run_command(cmd_extract_raw)

                # Step 4b: Convert DV Profile using dovi_tool convert
                print_header(f"Step 5: ({path_name}) Converting DV Profile (Mode {conversion_mode})")
                cmd_dv_convert = [
                    'dovi_tool',
                    '-m', conversion_mode,
                    'convert',
                    '-i', temp_video_raw,
                    '-o', temp_video_final_dv
                ]
                run_command(cmd_dv_convert)

                if config['auto_cleanup_temp_video']:
                    skasuj_plik(temp_video_raw, label="raw temp video (post-dv-convert)")

                video_input_for_mux = temp_video_final_dv
                map_str_for_mux = "0" # Input is a clean HEVC file
                use_hdr_tags_xml = False # Passthrough, mkvmerge will copy embedded tags
                final_mux_step = "6" # Muxing is the 6th logical step

            else:
                # --- PURE PASSTHROUGH (REMUX) PATH ---
                if should_convert_dv:
                    # This case happens if user selected 'Y' but profile was already P8
                    print_info(f"DV Profile is {dv_profile_str}. Conversion to P8 is not needed.")
                print_header("Step 4: Configuring Passthrough (Remux Mode)")

                video_input_for_mux = source_file # Use original file as input

                # Get video index from analysis
                video_stream_config = config.get('video_stream')
                if not video_stream_config:
                    raise ValueError("Missing video_stream configuration for passthrough.")
                map_str_for_mux = str(video_stream_config.get('index', '0'))

                # We DON'T use XML tags for passthrough
                use_hdr_tags_xml = False

                final_mux_step = "4" # Muxing is the next step
            # --- END OF PASSTHROUGH LOGIC ---

        else:
            # --- ENCODE ---
            print_info("Encode mode selected. Determining DV profile path...")

            # Get video stream info needed for encode paths
            video_stream_config = config.get('video_stream')
            if not video_stream_config:
                raise ValueError("Missing video_stream configuration for encode.")
            dv_profile = config.get('dv_profile')
            map_video = video_stream_config.get('index', 0)

            dv_profile_str = str(dv_profile) if dv_profile is not None else "None"
            print_info(f"Using profile string for logic: '{dv_profile_str}'")

            # -----------------------------------------------------------------
            #  PATH ENCODE: UNIFIED (Profile 7 / Profile 8)
            #  (P5 is blocked by Sanity Check earlier)
            # -----------------------------------------------------------------
            if dv_profile_str == '7' or dv_profile_str == '8':
                path_name = f"Profile {dv_profile_str} Encode"
                use_hdr_tags_xml = True # We still need this for HDR10 fallback tags

                video_codec_name = video_stream_config.get('codec_name', 'hevc')
                if 'hevc' not in video_codec_name:
                    raise ValueError(f"Dolby Vision Profile {dv_profile_str} detected, but the video codec is not HEVC. Cannot proceed.")

                # --- Define files ---
                temp_video_raw = os.path.join(output_dir, f"{file_basename}_temp_video_raw.hevc")
                temp_rpu_original = os.path.join(output_dir, f"{file_basename}_temp_RPU_original.bin")
                temp_video_converted_hevc = os.path.join(output_dir, f"{file_basename}_temp_video_converted.hevc")
                temp_video_final_dv = os.path.join(output_dir, f"{file_basename}_temp_video_final_dv.hevc")

                # Files for 7->8 conversion (optional)
                temp_editor_json = os.path.join(output_dir, f"{file_basename}_temp_editor.json")
                temp_rpu_converted_p8 = os.path.join(output_dir, f"{file_basename}_temp_RPU_P8_converted.bin")

                files_to_cleanup.extend([
                    temp_video_raw, temp_rpu_original, temp_video_converted_hevc,
                    temp_video_final_dv
                ])

                # --- Step 4a: Extract raw video stream ---
                print_header(f"Step 4: ({path_name}): Extracting raw HEVC")
                cmd_extract_raw = ['mkvextract', 'tracks', source_file, f'{map_video}:{temp_video_raw}']
                run_command(cmd_extract_raw)

                # --- Step 4b: Extract ORIGINAL RPU (P7 or P8) ---
                print_header(f"Step 4b: ({path_name}): Extracting original RPU")
                cmd_rpu_extract = ['dovi_tool', 'extract-rpu', '-i', temp_video_raw, '-o', temp_rpu_original]
                run_command(cmd_rpu_extract)

                # --- Step 5: Convert HEVC -> HEVC (The Encode step) ---
                print_header(f"Step 5: ({path_name}) Converting Base Layer to temp HEVC")
                cmd_convert = ['ffmpeg']
                cmd_convert.extend(['-i', temp_video_raw])

                if config['encoder'] == 'nvenc':
                    print_info("Nvidia encoder selected.")
                    cmd_convert.extend(['-c:v', 'hevc_nvenc', '-preset', config['encoder_params']['preset'], '-cq', config['encoder_params']['cq'], '-pix_fmt', 'p010le'])
                elif config['encoder'] == 'amf':
                    print_info("AMD encoder selected.")
                    cmd_convert.extend(['-c:v', 'hevc_amf', '-rc', 'cqp', '-qp_p', config['encoder_params']['qp'], '-qp_i', config['encoder_params']['qp'], '-qp_b', config['encoder_params']['qp'], '-quality', config['encoder_params']['quality'], '-pix_fmt', 'p010le'])

                # ffmpeg strips RPU.
                # We are re-injecting it later, so this encode step is fine.
                cmd_convert.append(temp_video_converted_hevc) # Save to .hevc
                run_command(cmd_convert)

                # --- Step 6: RPU Decision & Injection ---
                # Default: Use the original RPU we extracted
                rpu_to_inject = temp_rpu_original

                # When in 'encode' mode, we MUST convert P7 to P8.1
                # because ffmpeg discards the Enhancement Layer (EL),
                # leaving only a single-layer Base Layer (BL).
                # Injecting P7 RPU (which points to a non-existent EL)
                # would corrupt the file.
                if dv_profile_str == '7':
                    print_header(f"Step 6a: ({path_name}) Forcing RPU P7 -> P8.1 conversion")
                    print_info("Encode mode detected: P7 RPU must be converted to P8.1 to match the single-layer (BL-only) HEVC output.")

                    files_to_cleanup.extend([temp_editor_json, temp_rpu_converted_p8])

                    # Create editor config
                    try:
                        editor_config = {"mode": 2} # P7 -> P8 mode
                        with open(temp_editor_json, 'w', encoding='utf-8') as f:
                            json.dump(editor_config, f)
                    except Exception as e:
                        print_error(f"Failed to write temporary editor config: {e}")
                        raise

                    # Run editor
                    cmd_rpu_convert = [
                        'dovi_tool', 'editor',
                        '-i', temp_rpu_original, # Input is original P7 RPU
                        '-j', temp_editor_json,
                        '-o', temp_rpu_converted_p8 # Output is new P8 RPU
                    ]
                    run_command(cmd_rpu_convert)

                    # Update the variable to point to the NEW RPU file
                    rpu_to_inject = temp_rpu_converted_p8
                    print_info("RPU will be injected from new P8 file.")

                else: # This covers dv_profile_str == '8'
                    print_info("Proceeding with original Profile 8 RPU.")

                # Cleanup the raw video
                if config['auto_cleanup_temp_video']:
                    skasuj_plik(temp_video_raw, label="raw temp video (post-conversion)")
                    if rpu_to_inject != temp_rpu_original: # If we converted
                        skasuj_plik(temp_rpu_original, label="Original P7 RPU (converted)")
                        skasuj_plik(temp_editor_json, label="Temp JSON config")

                # --- STEP 7: Inject RPU ---
                print_header(f"Step 7: ({path_name}) Injecting RPU into encoded HEVC")
                cmd_inject = [
                    'dovi_tool', 'inject-rpu',
                    '-i', temp_video_converted_hevc, # Use the converted .hevc
                    '-r', rpu_to_inject,           # Use the correct RPU file
                    '-o', temp_video_final_dv
                ]
                run_command(cmd_inject)

                video_input_for_mux = temp_video_final_dv
                map_str_for_mux = "0"
                final_mux_step = "8" # Muxing is now the 8th logical step

            # -----------------------------------------------------------------
            #  FALLBACK: UNSUPPORTED or NO DV PROFILE
            #  It forces conversion to HDR10 by stripping all DV metadata.
            # -----------------------------------------------------------------
            else:
                use_hdr_tags_xml = True
                print_warn(f"Unsupported or No Dolby Vision Profile ({dv_profile_str}) detected.")
                print_warn("WARNING: Forcing safe conversion to HDR10 by stripping all DV metadata.")

                path_name = "Fallback Path (Safe HDR10)"
                print_header(f"Step 4: ({path_name}) Converting video to temp MKV (Safe HDR10 only)")

                temp_video_converted_mkv = os.path.join(output_dir, f"{file_basename}_temp_video_converted.mkv")
                files_to_cleanup.append(temp_video_converted_mkv)

                cmd_convert = ['ffmpeg']
                cmd_convert.extend(['-i', source_file]) # Input is the original MKV
                cmd_convert.extend(['-map', f"0:{map_video}"])
                cmd_convert.extend(['-an', '-sn'])

                # This explicitly removes all DV metadata (VUI and RPU) to prevent the 0-byte RPU crash.
                # Check the INPUT codec. Only apply the filter if the input is HEVC.
                video_codec_name = video_stream_config.get('codec_name', 'unknown')

                if 'hevc' in video_codec_name or 'h265' in video_codec_name:
                    # Input is HEVC, so it MIGHT have unsupported DV (like P4).
                    # Apply the filter to be safe.
                    print_info(f"Input is HEVC. Adding bitstream filter to safely remove all DV metadata...")
                    cmd_convert.extend(['-bsf:v', 'hevc_metadata=remove_dv_rpu=1'])
                else:
                    # Input is AVC (H.264) or other. It cannot have DV RPU.
                    # Do NOT apply the filter.
                    print_info(f"Input is {video_codec_name} (not HEVC). Skipping DV-related bitstream filters.")

                if config['encoder'] == 'nvenc':
                    print_info("Nvidia encoder selected.")
                    cmd_convert.extend(['-c:v', 'hevc_nvenc', '-preset', config['encoder_params']['preset'], '-cq', config['encoder_params']['cq'], '-pix_fmt', 'p010le'])
                elif config['encoder'] == 'amf':
                    print_info("AMD encoder selected.")
                    cmd_convert.extend(['-c:v', 'hevc_amf', '-rc', 'cqp', '-qp_p', config['encoder_params']['qp'], '-qp_i', config['encoder_params']['qp'], '-qp_b', config['encoder_params']['qp'], '-quality', config['encoder_params']['quality'], '-pix_fmt', 'p010le'])

                # These metadata flags are fine, they are for HDR10
                if config.get('hdr10_master_display'):
                    print_info("Attempting to pass HDR10 Mastering Display via -metadata flag.")
                    cmd_convert.extend(['-metadata', f"mastering-display={config['hdr10_master_display']}"])
                if config.get('hdr10_cll_fall'):
                    print_info("Attempting to pass HDR10 Content Light Level via -metadata flag.")
                    cmd_convert.extend(['-metadata', f"max-cll={config['hdr10_cll_fall']}"])

                cmd_convert.append(temp_video_converted_mkv)
                run_command(cmd_convert)

                video_input_for_mux = temp_video_converted_mkv
                map_str_for_mux = "0:0"
                final_mux_step = "5"

        # --- Final Step: Muxing ---
        print_header(f"Step {final_mux_step}: Final Muxing (mkvmerge)")
        cmd_mux = ['mkvmerge', '-o', final_file_path]

        # --- Add video input based on policy ---
        if config.get('video_policy') == 'passthrough':
            # Passthrough Mode: Copy only video track from source, plus chapters/attachments
            print_info(f"Adding video track {map_str_for_mux} from source (Passthrough).")
            cmd_mux.extend([
                '--video-tracks', map_str_for_mux,
                '-A', '-S', # Disable Audio and Subtitles from this input
                video_input_for_mux,
                '--no-chapters', '--no-attachments' # Start clean
            ])

        else:
            # Encode Mode: Input is a clean video file, just map it.
            print_info(f"Adding encoded video stream (Encode Mode).")
            if map_str_for_mux == "0:0":
                cmd_mux.extend(['--language', '0:und', video_input_for_mux])
            else:
                cmd_mux.extend(['--language', f'{map_str_for_mux}:und', video_input_for_mux])

                # Add HDR tags from XML (conditionally)
        if use_hdr_tags_xml:
            # This flag is True for Encode Paths A, B, C
            if hdr_tags_xml_path:
                print_info("Adding HDR10 global tags from XML file (Encode Mode).")
                cmd_mux.extend(['--global-tags', hdr_tags_xml_path])
            else:
                # XML file wasn't generated (e.g., source had no HDR)
                print_info("Skipping HDR10 global tags (Encode Mode - no HDR metadata found in source).")
        else:
            # This flag is False only for Passthrough Path D
            print_info("Skipping HDR10 global tags (Passthrough Mode - mkvmerge copies embedded metadata).")

        # Add audio tracks
        current_audio_index = 0
        for audio in temp_audio_files:
            lang = audio['stream'].get('tags', {}).get('language', 'und')
            title = audio['stream'].get('tags', {}).get('title', f'{lang.upper()} {audio["stream"]["codec_name"]}')
            is_default = 'yes' if current_audio_index == config['default_audio_index'] else 'no'
            cmd_mux.extend(['--language', f'0:{lang}', '--track-name', f'0:{title}', '--default-track', f'0:{is_default}', audio['path']])
            current_audio_index += 1
        for audio in config['external_audio_files']:
            is_default = 'yes' if current_audio_index == config['default_audio_index'] else 'no'
            cmd_mux.extend(['--language', f'0:{audio["lang"]}', '--track-name', f'0:{audio["title"]}', '--default-track', f'0:{is_default}', audio['path']])
            current_audio_index += 1

        # Add subtitle tracks
        current_subtitle_index = 0
        for sub in temp_subtitle_files:
            lang = sub['stream'].get('tags', {}).get('language', 'und')
            title = sub['stream'].get('tags', {}).get('title', f'{lang.upper()} {sub["stream"]["codec_name"]}')
            is_default = 'yes' if current_subtitle_index == config['default_subtitle_index'] else 'no'
            cmd_mux.extend(['--language', f'0:{lang}', '--track-name', f'0:{title}', '--default-track', f'0:{is_default}', sub['path']])
            current_subtitle_index += 1
        for sub in config['external_subtitle_files']:
            is_default = 'yes' if current_subtitle_index == config['default_subtitle_index'] else 'no'
            cmd_mux.extend(['--language', f'0:{sub["lang"]}', '--track-name', f'0:{sub["title"]}', '--default-track', f'0:{is_default}', sub['path']])
            current_subtitle_index += 1

        run_command(cmd_mux)

        print_k(f"\nSUCCESS! Final file is ready: {final_file_path}", Kolory.OKGREEN, bold=True)
        # --- Final Cleanup Logic ---
        policy = config.get('final_cleanup_policy', 'ask')
        if policy == 'on_success' or policy == 'always':
            sprzataj_pliki(files_to_cleanup)
        elif policy == 'ask':
            if input_k("\nDo you want to delete the remaining temporary files? [Y/n]: ").lower() != 'n':
                sprzataj_pliki(files_to_cleanup)
            else:
                print_info("Temporary files have been kept.")
        else:
            print_info("Temporary files have been kept based on profile policy.")

    except Exception as e:
        print_error(f"The conversion process failed: {e}")
        print_warn("Check the error logs above.")
        # --- Cleanup on Error ---
        policy = config.get('final_cleanup_policy', 'ask')
        should_cleanup = False
        if policy == 'always':
            should_cleanup = True
            print_info("Cleaning up temporary files based on 'always' policy.")
        elif policy == 'ask':
            if input_k("\nAn error occurred. Delete temporary files anyway? [y/N]: ").lower() == 'y':
                should_cleanup = True
            else:
                 print_info("Temporary files have been kept for debugging.")
        else: # 'never' or 'on_success' (which failed)
             print_info("Temporary files have been kept for debugging.")

        if should_cleanup:
            # Ensure cleanup list is reasonably populated even on early failure
            if not files_to_cleanup:
                 files_to_cleanup.extend([
                     os.path.join(output_dir, f"{file_basename}_temp_video_raw.hevc"),
                     os.path.join(output_dir, f"{file_basename}_temp_RPU.bin"),
                     os.path.join(output_dir, f"{file_basename}_temp_video_converted.mkv"),
                     os.path.join(output_dir, f"{file_basename}_temp_video_extracted_hdr.hevc"),
                     os.path.join(output_dir, f"{file_basename}_temp_video_final_dv.hevc"),
                     hdr_tags_xml_path if hdr_tags_xml_path else "",
                     *[f['path'] for f in temp_audio_files],
                     *[f['path'] for f in temp_subtitle_files]
                 ])
            sprzataj_pliki(files_to_cleanup)

        raise # Re-raise the exception

    except Exception as e:
        print_error(f"The conversion process failed: {e}")
        print_warn("Check the error logs above.")
        policy = config.get('final_cleanup_policy', 'ask')
        if policy == 'always':
            print_info("Cleaning up temporary files based on 'always' policy.")
            sprzataj_pliki(files_to_cleanup)
        elif policy == 'ask':
            if input_k("\nAn error occurred. Delete temporary files anyway? [y/N]: ").lower() == 'y':
                sprzataj_pliki(files_to_cleanup)
            else:
                print_info("Temporary files have been kept for debugging.")
        else:
             print_info("Temporary files have been kept for debugging.")
        # Ensure cleanup list is populated even on early failure for robust cleanup
        if not files_to_cleanup:
             # Populate with potential files if failure happened before paths were chosen
             files_to_cleanup.extend([
                 os.path.join(output_dir, f"{file_basename}_temp_video_raw.hevc"),
                 os.path.join(output_dir, f"{file_basename}_temp_RPU.bin"),
                 os.path.join(output_dir, f"{file_basename}_temp_video_converted.mkv"),
                 os.path.join(output_dir, f"{file_basename}_temp_video_extracted_hdr.hevc"),
                 os.path.join(output_dir, f"{file_basename}_temp_video_final_dv.hevc"),
                 hdr_tags_xml_path if hdr_tags_xml_path else ""
             ])
             files_to_cleanup.extend([f['path'] for f in temp_audio_files])
             files_to_cleanup.extend([f['path'] for f in temp_subtitle_files])

        raise # Re-raise the exception after attempting cleanup logic

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


# --- Main script function ---

def main():
    global LOG_FILE # Use the global log file handle

    if COLORAMA_AVAILABLE and os.name == 'nt':
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
        global LOG_FILE
        logging_enabled_by_profile = log_config.get('log_to_file', False)
        logging_enabled_by_flag = args.log
        if (logging_enabled_by_profile or logging_enabled_by_flag) and LOG_FILE is None:
            log_filename = log_config.get('log_filename', 'mkv_factory.log')
            log_path = os.path.join(output_directory, log_filename)
            try:
                LOG_FILE = open(log_path, 'a', encoding='utf-8')
                import datetime
                now = datetime.datetime.now().isoformat()
                LOG_FILE.write(f"\n--- Log Session Started: {now} ---\n")
                LOG_FILE.flush()
                print_info(f"Logging to file: {log_path}")
            except Exception as e:
                print_error(f"Failed to open log file {log_path}: {e}")
                LOG_FILE = None
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
        if LOG_FILE:
            print_info("Closing log file.")
            LOG_FILE.write("--- Log Session Ended ---\n")
            LOG_FILE.close()

if __name__ == "__main__":
    main()
