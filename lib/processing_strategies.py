#!/usr/bin/env python3

"""
MKV Factory - Video Processing Strategies Module
Version 9.0

Changes:
- introduce keep, drop, convert HDR policies
- remove HDR10 logic
"""

import os
import re
import json
from typing import List, Dict, Optional, Any

try:
    from .utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        run_command, skasuj_plik
    )
except ImportError:
    from utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        run_command, skasuj_plik
    )

class VideoProcessor:
    """
    Base class for video processing strategies.
    """
    def __init__(self, config: Dict[str, Any], source_file: str, output_dir: str, file_basename: str):
        self.config = config
        self.source_file = source_file
        self.output_dir = output_dir
        self.file_basename = file_basename
        self.temp_files: List[str] = [] # To track generated temp files

    def process(self) -> Dict[str, Any]:
        """
        Executes the video processing strategy.
        Must return a dictionary containing:
        {
            'video_input': str,    # Path to the final video file for muxing
            'map_str': str,        # Stream mapper for mkvmerge (e.g., "0:0" or "0")
            'final_mux_step': str, # Step number for logging
            'input_type': str      # 'mkv_container' or 'raw_hevc'
        }
        """
        raise NotImplementedError("Subclass must implement process method")

    def get_temp_files(self) -> List[str]:
        """Returns a list of temporary files created by this processor."""
        return self.temp_files

#
# --- Strategy 1: PASSTHROUGH (REMUX) ---
#
class PassthroughStrategy(VideoProcessor):
    """
    Handles video passthrough (remux).
    Reads dv_policy and hdr10plus_policy to decide on the processing chain.
    """
    def process(self) -> Dict[str, Any]:

        # Read policies and file state
        dv_policy = self.config.get('dv_policy', 'keep')
        hdr10plus_policy = self.config.get('hdr10plus_policy', 'keep')
        dv_profile_str = str(self.config.get('dv_profile'))
        has_dv = self.config['has_dv']
        has_hdr10plus = self.config.get('has_hdr10plus', False)

        video_stream_config = self.config.get('video_stream')
        if not video_stream_config:
            raise ValueError("Missing video_stream configuration for passthrough.")
        map_video = video_stream_config.get('index', 0)

        # --- Check if any hybrid operation is NEEDED and POSSIBLE ---

        # Check DV operation
        dv_op_needed = (
            (dv_policy == 'convert7_to_8' and dv_profile_str == '7') or
            (dv_policy == 'drop' and has_dv)
        )

        # Check HDR10+ operation
        hdr10plus_op_needed = (hdr10plus_policy == 'drop' and has_hdr10plus)

        # --- Decision ---

        if not dv_op_needed and not hdr10plus_op_needed:
            # --- Case 1: Pure Passthrough ---
            # No operations are needed. This correctly handles all scenarios:
            # 1. DV=keep, HDR10+=keep
            # 2. DV=keep, HDR10+=drop (but file has no HDR10+)
            # 3. DV=drop (but file has no DV), HDR10+=keep
            # 4. DV=convert (but file is P8), HDR10+=keep

            print_header("Step 4: Configuring Passthrough (Remux Mode - Pure Keep)")
            map_str_for_mux = str(video_stream_config.get('index', '0'))
            return {
                'video_input': self.source_file,
                'map_str': map_str_for_mux,
                'final_mux_step': "4",
                'input_type': 'mkv_container'
            }

        else:
            # --- Case 2: Hybrid Passthrough (Convert or Strip) ---
            # At least one operation is needed.
            print_header(f"Step 4: Configuring Hybrid Passthrough (Extracting raw HEVC)")

            temp_video_raw = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_raw.hevc")
            self.temp_files.append(temp_video_raw)

            cmd_extract_raw = ['mkvextract', 'tracks', self.source_file, f'{map_video}:{temp_video_raw}']
            run_command(cmd_extract_raw)

            current_file_in = temp_video_raw

            # --- Chain Step 2a: Dolby Vision Policy ---
            if dv_policy == 'convert7_to_8' and dv_profile_str == '7':
                print_header(f"Step 5a: (Hybrid) Converting DV Profile (P7 -> P8)")
                temp_video_p8 = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_p8.hevc")
                self.temp_files.append(temp_video_p8)
                cmd_dv_convert = ['dovi_tool', '-m', '2', 'convert', '-i', current_file_in, '-o', temp_video_p8]
                run_command(cmd_dv_convert)
                current_file_in = temp_video_p8

            elif dv_policy == 'drop' and has_dv:
                print_header(f"Step 5a: (Hybrid) Stripping DV metadata")
                temp_video_no_dv = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_no_dv.hevc")
                self.temp_files.append(temp_video_no_dv)
                cmd_dv_strip = ['dovi_tool', 'remove', '-i', current_file_in, '-o', temp_video_no_dv]
                run_command(cmd_dv_strip)
                current_file_in = temp_video_no_dv

            # --- Chain Step 2b: HDR10+ Policy ---
            if hdr10plus_policy == 'drop' and has_hdr10plus:
                print_header(f"Step 5b: (Hybrid) Stripping HDR10+ metadata")
                temp_video_no_hdr10plus = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_no_hdr10plus.hevc")
                self.temp_files.append(temp_video_no_hdr10plus)

                cmd_hdr_strip = ['hdr10plus_tool', 'remove', '-i', current_file_in, '-o', temp_video_no_hdr10plus]
                run_command(cmd_hdr_strip)
                current_file_in = temp_video_no_hdr10plus

            # --- Final cleanup of raw stream ---
            if self.config['auto_cleanup_temp_video'] and current_file_in != temp_video_raw:
                 skasuj_plik(temp_video_raw, label="raw temp video (post-hybrid-convert/strip)")

            # Return the final file in the chain
            return {
                'video_input': current_file_in,
                'map_str': "0",
                'final_mux_step': "6",
                'input_type': 'raw_hevc'
            }

#
# --- Strategy 2: ENCODE ---
#
class EncodeStrategy(VideoProcessor):
    """
    Handles video encoding (re-compression).
    Uses a unified path for HEVC inputs to preserve metadata (DV, HDR10+)
    and a fallback path for non-HEVC inputs or HDR10-only.
    """
    def process(self) -> Dict[str, Any]:

        video_stream_config = self.config.get('video_stream')
        if not video_stream_config:
            raise ValueError("Missing video_stream configuration for encode.")

        video_codec_name = video_stream_config.get('codec_name', 'unknown')
        map_video = video_stream_config.get('index', 0)

        # Read policies
        dv_policy = self.config.get('dv_policy', 'keep')
        hdr10plus_policy = self.config.get('hdr10plus_policy', 'keep')

        # --- Check if we need the complex injection path (Scenario A) ---
        # This is TRUE only if it's an HEVC file AND has dynamic metadata to preserve
        is_hevc = 'hevc' in video_codec_name or 'h265' in video_codec_name
        has_dynamic_hdr = self.config['has_dv'] or self.config['has_hdr10plus']

        needs_injection_path = is_hevc and has_dynamic_hdr

        # --- PATH A (Scenario A): HEVC with DV/HDR10+ (Complex Injection Path) ---
        if needs_injection_path:

            print_info("HEVC codec with dynamic HDR detected. Running complex injection path.")
            path_name = "Dynamic HEVC Encode"

            # --- Define files ---
            temp_video_raw = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_raw.hevc")
            temp_video_converted_hevc = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_converted.hevc")
            self.temp_files.extend([temp_video_raw, temp_video_converted_hevc])

            # --- Step 1: Extract raw HEVC ---
            print_header(f"Step 4: ({path_name}): Extracting raw HEVC")
            cmd_extract_raw = ['mkvextract', 'tracks', self.source_file, f'{map_video}:{temp_video_raw}']
            run_command(cmd_extract_raw)

            # --- Step 2: Encode raw HEVC ---
            print_header(f"Step 5: ({path_name}) Converting Base Layer to temp HEVC")
            cmd_convert = ['ffmpeg']
            original_fps = video_stream_config.get('r_frame_rate')
            if not original_fps or original_fps == "0/0":
                original_fps = video_stream_config.get('avg_frame_rate')
            if original_fps and original_fps != "0/0":
                cmd_convert.extend(['-framerate', original_fps])
            else:
                print_warn("Could not determine original FPS. FFmpeg will guess!")

            cmd_convert.extend(['-i', temp_video_raw])
            # No -map_metadata here, as it would conflict with injection tools

            if self.config['encoder'] == 'nvenc':
                cmd_convert.extend(['-c:v', 'hevc_nvenc', '-preset', self.config['encoder_params']['preset'], '-cq', self.config['encoder_params']['cq'], '-pix_fmt', 'p010le'])
            elif self.config['encoder'] == 'amf':
                cmd_convert.extend(['-c:v', 'hevc_amf', '-rc', 'cqp', '-qp_p', self.config['encoder_params']['qp'], '-qp_i', self.config['encoder_params']['qp'], '-qp_b', self.config['encoder_params']['qp'], '-quality', self.config['encoder_params']['quality'], '-pix_fmt', 'p010le'])

            cmd_convert.append(temp_video_converted_hevc)
            run_command(cmd_convert)

            # This is the starting point for the metadata injection chain
            current_file_to_inject = temp_video_converted_hevc

            # --- Step 3: Metadata Re-injection Chain ---

            # --- Step 3a: Dolby Vision RPU ---
            dv_profile_str = str(self.config.get('dv_profile'))

            if self.config['has_dv'] and dv_policy != 'drop':
                if dv_profile_str == '7' or dv_profile_str == '8':
                    print_info(f"DV Profile {dv_profile_str} detected. Re-injecting RPU.")

                    temp_rpu_original = os.path.join(self.output_dir, f"{self.file_basename}_temp_RPU_original.bin")
                    temp_video_final_dv = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_final_dv.hevc")
                    self.temp_files.extend([temp_rpu_original, temp_video_final_dv])

                    rpu_to_inject = temp_rpu_original

                    print_header(f"Step 6: ({path_name}): Extracting original RPU")
                    cmd_rpu_extract = ['dovi_tool', 'extract-rpu', '-i', temp_video_raw, '-o', temp_rpu_original]
                    run_command(cmd_rpu_extract)

                    if dv_profile_str == '7':
                        print_header(f"Step 6a: ({path_name}) Forcing RPU P7 -> P8.1 conversion")
                        print_info("Encode mode detected: P7 RPU must be converted to P8.1 to match the single-layer (BL-only) HEVC output.")
                        temp_editor_json = os.path.join(self.output_dir, f"{self.file_basename}_temp_editor.json")
                        temp_rpu_converted_p8 = os.path.join(self.output_dir, f"{self.file_basename}_temp_RPU_P8_converted.bin")
                        self.temp_files.extend([temp_editor_json, temp_rpu_converted_p8])

                        try:
                            editor_config = {"mode": 2} # P7 -> P8 mode
                            with open(temp_editor_json, 'w', encoding='utf-8') as f:
                                json.dump(editor_config, f)
                        except Exception as e:
                            print_error(f"Failed to write temporary editor config: {e}")
                            raise

                        cmd_rpu_convert = [
                            'dovi_tool', 'editor',
                            '-i', temp_rpu_original,
                            '-j', temp_editor_json,
                            '-o', temp_rpu_converted_p8
                        ]
                        run_command(cmd_rpu_convert)
                        rpu_to_inject = temp_rpu_converted_p8

                        if self.config['auto_cleanup_temp_video']:
                            skasuj_plik(temp_rpu_original, label="Original P7 RPU (converted)")
                            skasuj_plik(temp_editor_json, label="Temp JSON config")

                    print_header(f"Step 7: ({path_name}) Injecting RPU into encoded HEVC")
                    cmd_inject = [
                        'dovi_tool', 'inject-rpu',
                        '-i', current_file_to_inject,
                        '-r', rpu_to_inject,
                        '-o', temp_video_final_dv
                    ]
                    run_command(cmd_inject)
                    current_file_to_inject = temp_video_final_dv

                else:
                    print_info(f"Unsupported DV Profile ({dv_profile_str}) detected. Skipping RPU injection.")

            elif self.config['has_dv'] and dv_policy == 'drop':
                print_info("DV policy is 'drop'. Skipping RPU injection.")
            else:
                print_info("No DV metadata detected. Skipping RPU steps.")

            # --- Step 3b: HDR10+ ---
            if self.config['has_hdr10plus'] and hdr10plus_policy == 'keep':
                print_header(f"Step 7b: ({path_name}) Extracting and Injecting HDR10+ metadata")

                temp_hdr10plus_json = os.path.join(self.output_dir, f"{self.file_basename}_temp_hdr10plus.json")
                temp_video_with_hdr10plus = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_with_hdr10plus.hevc")
                self.temp_files.extend([temp_hdr10plus_json, temp_video_with_hdr10plus])

                # 1. Extract HDR10+ metadata from the *original* raw file
                cmd_hdr_extract = ['hdr10plus_tool', 'extract', '-i', temp_video_raw, '-o', temp_hdr10plus_json]
                run_command(cmd_hdr_extract)

                # 2. Inject metadata into the *current* file in the chain
                # (which might already contain DV metadata)
                cmd_hdr_inject = ['hdr10plus_tool', 'inject', '-i', current_file_to_inject, '-j', temp_hdr10plus_json, '-o', temp_video_with_hdr10plus]
                run_command(cmd_hdr_inject)

                # Update the chain
                current_file_to_inject = temp_video_with_hdr10plus

                if self.config['auto_cleanup_temp_video']:
                    skasuj_plik(temp_hdr10plus_json, label="Temp HDR10+ JSON")

            elif self.config['has_hdr10plus'] and hdr10plus_policy == 'drop':
                print_info("HDR10+ metadata detected. Policy is 'drop'. Skipping injection.")
                # ffmpeg encode already stripped it, so we do nothing.

            else:
                print_info("No HDR10+ metadata detected. Skipping HDR10+ steps.")

            # --- Cleanup ---
            if self.config['auto_cleanup_temp_video']:
                skasuj_plik(temp_video_raw, label="raw temp video (post-metadata-extraction)")

            final_video_file = current_file_to_inject

            return {
                'video_input': final_video_file,
                'map_str': "0",
                'final_mux_step': "8",
                'input_type': 'raw_hevc'
            }

        # --- PATH B (Scenario B): Non-HEVC or HEVC without DV/HDR10+ (Simple Path) ---
        else:
            if is_hevc:
                print_info("HEVC file detected, but no dynamic HDR. Running simple encode path.")
            else:
                print_warn(f"Input codec is {video_codec_name} (not HEVC). Running simple encode path.")

            path_name = "Simple Encode Path"

            # Encode to raw .hevc
            temp_video_converted_hevc = os.path.join(self.output_dir, f"{self.file_basename}_temp_video_converted.hevc")
            self.temp_files.append(temp_video_converted_hevc)

            print_header(f"Step 4: ({path_name}) Encoding from source MKV")
            cmd_convert = ['ffmpeg']

            # Source is the original MKV file
            cmd_convert.extend(['-i', self.source_file])
            cmd_convert.extend(['-map', f"0:{map_video}"])

            # Logic to map static metadata (this is why we read from the MKV)
            # This 'if' is redundant since 'has_dynamic_hdr' is false, but keep for clarity
            if not has_dynamic_hdr:
                print_info("File has no DV or HDR10+. Attempting to map static HDR metadata...")
                cmd_convert.extend(['-map_metadata:s:v', f'0:s:{map_video}'])

            cmd_convert.extend(['-an', '-sn'])

            if self.config['encoder'] == 'nvenc':
                cmd_convert.extend(['-c:v', 'hevc_nvenc', '-preset', self.config['encoder_params']['preset'], '-cq', self.config['encoder_params']['cq'], '-pix_fmt', 'p010le'])
            elif self.config['encoder'] == 'amf':
                cmd_convert.extend(['-c:v', 'hevc_amf', '-rc', 'cqp', '-qp_p', self.config['encoder_params']['qp'], '-qp_i', self.config['encoder_params']['qp'], '-qp_b', self.config['encoder_params']['qp'], '-quality', self.config['encoder_params']['quality'], '-pix_fmt', 'p010le'])

            cmd_convert.append(temp_video_converted_hevc)
            run_command(cmd_convert)

            return {
                'video_input': temp_video_converted_hevc,
                'map_str': "0", # Output is raw HEVC, so map is '0'
                'final_mux_step': "5",
                'input_type': 'raw_hevc' # Output is raw_hevc
            }
