#!/usr/bin/env python3

"""
MKV Factory - Source File Analysis Module (ffprobe)
Version 9.0

Changes
- remove HDR10 detection logic
"""

import subprocess
import os
import json
from typing import Dict, Optional, Any

try:
    from .utils import print_header, print_info, print_warn, print_error
except ImportError:
    from utils import print_header, print_info, print_warn, print_error

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
            'has_hdr10plus': False,
            'dv_profile': None,
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

                    side_data = stream.get('side_data_list', [])
                    for data_item in side_data:
                        side_data_type = data_item.get('side_data_type', '').lower()

                        if "dovi" in side_data_type:
                            streams['has_dv'] = True
                            streams['dv_profile'] = data_item.get('dv_profile')

                        elif "hdr10+" in side_data_type:
                            streams['has_hdr10plus'] = True
                            print_info("Found HDR10+ metadata in 'stream side_data'.")

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

        # --- START 2ND PASS: FRAME-LEVEL PROBE (if needed for HDR10+) ---
        needs_frame_probe = not streams['has_hdr10plus'] # Check if we still need to find HDR10+

        if main_video_found and needs_frame_probe:
            print_info("Stream-level probe did not find HDR10+ metadata. Trying frame-level probe...")
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

                    for data_item in frame_side_data:
                        side_data_type = data_item.get('side_data_type', '').lower()

                        if "hdr10+" in side_data_type and not streams['has_hdr10plus']:
                            streams['has_hdr10plus'] = True
                            print_info("Found HDR10+ metadata in 'frame side_data'.")

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

        if streams['has_hdr10plus']:
            print_info("HDR10+ metadata detected.")

        if not streams['has_dv'] and not streams['has_hdr10plus']: # No DV, No HDR10+
            print_warn("No Dolby Vision or HDR10+ metadata detected by ffprobe.")

        return streams, source_duration

    except subprocess.CalledProcessError as e:
        print_error(f"Error during file analysis (ffprobe): {e}")
        if e.stderr: print_error(f"Error output: {e.stderr}")
        raise
    except json.JSONDecodeError:
        print_error("Error parsing JSON output from ffprobe.")
        raise
