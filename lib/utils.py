#!/usr/bin/env python3

"""
MKV Factory - Utility Module
Version 8.7

Changes:
- add HDR10plus tag
"""

import subprocess
import os
import sys
import json
import shutil
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
    safe_filename = ""

    if UNIDECODE_AVAILABLE:
        # --- Smart Path (unidecode installed) ---
        safe_filename = unidecode(filename)
    else:
        # --- Fallback Path (unidecode NOT installed) ---
        if not UNIDECODE_WARNING_SHOWN:
            print_warn("Library 'unidecode' is not installed (use: pip install unidecode).")
            print_warn("Activating fallback mode: Special characters (e.g., 'ś', 'ó') will be REMOVED, not transliterated (to 's', 'o').")
            UNIDECODE_WARNING_SHOWN = True # Show warning only once

        safe_filename = filename.encode('ascii', errors='ignore').decode('ascii')

    # 3. Remove any remaining non-safe chars from the WHOLE string
    #    (Keeps dots '.', underscores '_', etc.)
    safe_filename = re.sub(r'[^\w\s\._\-\[\]\(\)]', '', safe_filename)

    # 4. Collapse multiple whitespace characters into a single space
    safe_filename = re.sub(r'\s+', ' ', safe_filename).strip()

    # 5. Return the fully sanitized string
    return safe_filename

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
    FAST_TOOLS = ['dovi_tool', 'hdr10plus_tool']

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

def resolve_final_filename(output_dir: str, desired_filename: str) -> str:
    """
    Sanitizes a desired filename, ensures it has .mkv extension,
    checks for uniqueness, and logs warnings if changes were made.
    Returns the final, safe, and unique filename.
    """

    # 1. Sanitize (using V3 sanitize_filename)
    sane_filename = sanitize_filename(desired_filename)
    if sane_filename != desired_filename:
        print_warn(f"Filename was sanitized for safety:")
        print_info(f"  Original: {desired_filename}")
        print_info(f"  Cleaned:  {sane_filename}")

    # 2. Enforce .mkv extension (Checks the *sanitized* string)
    if not sane_filename.lower().endswith(".mkv"):
        # Rule 1: It does NOT end with .mkv.
        # This handles "wefwef loadasd.dupskol" and "wefwef"
        print_info(f"Filename '{sane_filename}' does not end with .mkv. Appending .mkv extension.")
        sane_filename = f"{sane_filename}.mkv" # -> "wefwef loadasd.dupskol.mkv"
    else:
        # Rule 2: It *does* end with .mkv. Do nothing.
        pass

    # 3. Check uniqueness (using existing helper)
    unique_filename = get_unique_filename(output_dir, sane_filename)

    # 4. Log if uniqueness check changed the name
    if unique_filename != sane_filename:
        print_warn(f"File '{sane_filename}' already exists in output directory.")
        print_info(f"Using new unique name: {unique_filename}")

    return unique_filename

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

    # Check if DV will be present in the final file
    dv_is_present = config['has_dv'] and config.get('dv_policy', 'keep') != 'drop'
    if dv_is_present:
        quality_tags.append("DV")

    # Check if HDR10+ will be present in the final file
    hdr10plus_is_present = config.get('has_hdr10plus', False) and config.get('hdr10plus_policy', 'keep') != 'drop'

    # Only add "HDR10+" tag if DV isn't already present
    # (Plex convention: [DV] implies HDR10+ compatibility for P8)
    if hdr10plus_is_present:
         quality_tags.append("HDR10plus")

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
