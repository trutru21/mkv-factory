#!/usr/bin/env python3

"""
MKV Factory - System & Environment Check Module
Version: 9.0

Changes
- add hdr10plus_tool check
"""

import subprocess
import shutil
from typing import Optional

# Import helper functions from our own library
try:
    from .utils import print_header, print_info, print_error, print_warn
except ImportError:
    from utils import print_header, print_info, print_error, print_warn

# --- Tool Configuration ---
# All tools are required for the script to run
REQUIRED_TOOLS = [
    'ffmpeg',
    'ffprobe',
    'mkvmerge',
    'dovi_tool',
    'mkvextract',
    'hdr10plus_tool'
]

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
    for tool in REQUIRED_TOOLS:
        if shutil.which(tool) is None:
            missing_tools.append(tool)

    if missing_tools:
        print_error(f"Missing required tools: {', '.join(missing_tools)}")
        print_warn("Please ensure ffmpeg, mkvtoolnix, dovi_tool, and hdr10plus_tool are installed and accessible in your container's PATH")
        return None

    print_info(f"All required tools ({', '.join(REQUIRED_TOOLS)}) are available.")

    if check_encoder_support('hevc_nvenc'):
        print_info("OK: Nvidia (hevc_nvenc) encoder detected.")
        return 'nvenc'

    if check_encoder_support('hevc_amf'):
        print_info("OK: AMD (hevc_amf) encoder detected.")
        return 'amf'

    print_error("No supported hardware HEVC encoder found.")
    print_warn("This script requires either Nvidia (hevc_nvenc) or AMD (hevc_amf) support in ffmpeg.")
    return None
