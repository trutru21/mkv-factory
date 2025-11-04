#!/usr/bin/env python3

"""
MKV Factory - Processing & Execution Module
(Extraction, Conversion, Muxing)
Version 9.0

Changes:
- refactored to use a Strategy pattern for video processing
- introduce keep, drop, convert HDR policies
- remove HDR10 processing logic

"""

import os
import re
import json
from typing import List, Dict, Optional, Any

try:
    from lib.utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, run_command, skasuj_plik, sprzataj_pliki,
        sanitize_filename
    )
    # Import new strategy classes
    from lib.processing_strategies import (
        VideoProcessor, PassthroughStrategy, EncodeStrategy
    )
except ImportError:
    from utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, run_command, skasuj_plik, sprzataj_pliki,
        sanitize_filename
    )
    # Fallback import
    from processing_strategies import (
        VideoProcessor, PassthroughStrategy, EncodeStrategy
    )


# --- Phase 3: Process Execution ---

def run_extraction(
    source_file: str,
    output_dir: str,
    config: Dict[str, Any]
):
    """Performs a simple stream extraction. No cleanup."""
    # (Ta funkcja pozostaje bez zmian)
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

def create_custom_hdr_tags_xml(output_dir: str, file_basename: str, config: Dict[str, Any]) -> Optional[str]:
    """
    Generates a custom XML tag file with HDR info for mediainfo.
    """

    # --- Build the HDR Info String (Logic from previous discussion) ---
    mkvmerge_title_parts = []

    # 1. Check for Dolby Vision
    if config.get('has_dv', False) and config.get('dv_policy') != 'drop':
        source_profile = str(config.get('dv_profile'))
        final_profile = source_profile

        if config.get('dv_policy') == 'convert7_to_8':
            final_profile = "8"
        elif config.get('video_policy') == 'encode' and source_profile == '7':
            # EncodeStrategy forces P7 to P8 [cite: 255-259]
            final_profile = "8"

        mkvmerge_title_parts.append(f"Dolby Vision P{final_profile}")

    # 2. Check for HDR10+
    if config.get('has_hdr10plus', False) and config.get('hdr10plus_policy') != 'drop':
        mkvmerge_title_parts.append("HDR10+")

    # 3. Add base HDR10 tag if any dynamic metadata is present
    if mkvmerge_title_parts:
        mkvmerge_title_parts.append("HDR10")
    # --- End of string logic ---

    # If no parts were added, don't create an XML file
    if not mkvmerge_title_parts:
        print_info("No dynamic HDR info to tag. Skipping custom XML generation.")
        return None

    hdr_info_string = ", ".join(mkvmerge_title_parts)

    custom_tag_name = "HDR-format-info"

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Tags>
  <Tag>
    <Targets />
    <Simple>
      <Name>{custom_tag_name}</Name>
      <String>{hdr_info_string}</String>
    </Simple>
  </Tag>
</Tags>
"""
    # --- Write the XML file ---
    xml_file_path = os.path.join(output_dir, f"{file_basename}_custom_hdr_tags.xml")
    try:
        with open(xml_file_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        print_info(f"Successfully created custom HDR tag file: {xml_file_path}")
        print_info(f"  -> Tag: {custom_tag_name} = {hdr_info_string}")
        return xml_file_path
    except Exception as e:
        print_error(f"Failed to write custom HDR tag file {xml_file_path}: {e}")
        return None

# --- Video Processing Factory ---
def _create_video_processor(
    config: Dict[str, Any],
    source_file: str,
    output_dir: str,
    file_basename: str
) -> VideoProcessor:
    """
    Factory function to create the correct video processing strategy
    based on the configuration.
    """
    video_policy = config.get('video_policy')

    if video_policy == 'passthrough':
        print_info("Selected strategy: PassthroughStrategy")
        return PassthroughStrategy(config, source_file, output_dir, file_basename)

    elif video_policy == 'encode':
        print_info("Selected strategy: EncodeStrategy")
        return EncodeStrategy(config, source_file, output_dir, file_basename)

    else:
        # This should have been caught by validation, but as a fallback:
        raise ValueError(f"Unknown video_policy: '{video_policy}'")


def run_full_conversion(
    source_file: str,
    output_dir: str,
    config: Dict[str, Any],
    file_basename: str
):
    """
    Executes the full conversion and muxing process using a strategy pattern.
    (Updated to use new hdr_policy and robust P5 Sanity Check)
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

    final_file_path = os.path.join(output_dir, config['final_filename'])
    custom_hdr_xml_path: Optional[str] = None

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

        # --- Step 3: Generating Custom HDR Info Tags ---
        print_header("Step 3: Generating Custom HDR Info Tags")
        custom_hdr_xml_path = create_custom_hdr_tags_xml(
            output_dir,
            file_basename,
            config
        )
        if custom_hdr_xml_path:
            files_to_cleanup.append(custom_hdr_xml_path)

        # --- Dolby Vision P5 SANITY CHECK ---
        # This block runs after config is loaded (from interactive or auto)
        # and before the strategy factory is called.
        # It overrides any dangerous user/profile settings for P5.

        dv_profile_str = str(config.get('dv_profile'))

        if dv_profile_str == '5':
            print_warn(f"Dolby Vision Profile 5 detected.")
            print_warn(f"This profile's video stream uses the IPT-PQ-C2 color matrix.")

            override_needed = False

            # Check 1: Is user trying to Encode?
            if config['video_policy'] == 'encode':
                print_warn(f"Encode policy (NVENC/AMF) is INCOMPATIBLE with IPT-PQ-C2.")
                print_warn(f"The encoder **misinterprets** these colors during processing.")
                print_warn(f"This **permanently corrupts** the output video (bakes in purple/green artifacts).")
                override_needed = True

            # Check 2: Is user trying to Convert or Drop? (applies to passthrough)
            if config['dv_policy'] == 'convert7_to_8':
                 print_warn(f"Hybrid Passthrough (convert) policy is INEFFECTIVE for IPT-PQ-C2.")
                 print_warn(f"Tools **fail to convert** the IPT-PQ-C2 colors correctly.")
                 override_needed = True
            elif config['dv_policy'] == 'drop':
                 print_warn(f"Hybrid Passthrough (drop) policy is INEFFECTIVE for IPT-PQ-C2.")
                 # (Future tools might support this, but dovi_tool extract-rpu --remove might fail)
                 override_needed = True

            if override_needed:
                print_warn("OVERRIDE: Forcing 'Pure Passthrough' (Policy: 'passthrough' + 'keep') **to prevent video corruption during processing**.")
                # Force the config to the only safe state
                config['video_policy'] = 'passthrough'
                config['dv_policy'] = 'keep'
                print_warn("WARNING: The final filename may still contain Encode/Convert/Drop tags, but the video stream is an unmodified Pure Passthrough copy.")

            elif config['video_policy'] == 'passthrough' and config['dv_policy'] == 'keep':
                 # This is the only safe path
                 print_info("Profile 5 detected with 'Pure Passthrough' (keep) policy as requested.")

            # This warning appears for P5 regardless of override
            print_warn("--------------------------------------------------------------------")
            print_warn("IMPORTANT: The output file retains the **original, unmodified** Profile 5 video stream (IPT-PQ-C2).")
            print_warn("This stream **WILL APPEAR PURPLE/GREEN on most PC players and TVs** due to lack of IPT-PQ-C2 support.")
            print_warn("--------------------------------------------------------------------")
        # --- END OF P5 SANITY CHECK ---


        # --- Determine Video Path (Passthrough or Encode) ---

        print_header("Step 4: Initializing Video Processing Strategy")

        # 1. Create strategy (factory will read the config, which may
        #    have been overridden by the P5 Sanity Check)
        processor = _create_video_processor(
            config,
            source_file,
            output_dir,
            file_basename
        )

        # 2. Execute strategy
        video_result = processor.process()

        # 3. Gather results
        video_input_for_mux = video_result['video_input']
        map_str_for_mux = video_result['map_str']
        final_mux_step = video_result['final_mux_step']

        # 4. Add temp files from the strategy to the main cleanup list
        files_to_cleanup.extend(processor.get_temp_files())

        # --- END OF STRATEGY BLOCK ---


        # --- Final Step: Muxing ---
        print_header(f"Step {final_mux_step}: Final Muxing (mkvmerge)")
        cmd_mux = ['mkvmerge', '-o', final_file_path]

        # Get data from strategy result
        video_input_for_mux = video_result['video_input']
        map_str_for_mux = video_result['map_str']
        input_type = video_result['input_type']

        # Get FPS info from config
        original_fps = config['video_stream'].get('r_frame_rate')

        if input_type == 'mkv_container':
            # This handles Pure Passthrough (input is source MKV)
            # OR Encode Fallback (input is temp MKV)
            print_info(f"Adding video track {map_str_for_mux} from container (Passthrough or non-HEVC Encode).")
            cmd_mux.extend([
                '--video-tracks', map_str_for_mux,
                '-A', '-S', # Disable Audio and Subtitles from this input
                video_input_for_mux,
                '--no-chapters', '--no-attachments'
            ])

        else: # input_type == 'raw_hevc'
            # This handles Encode, Hybrid Convert, and Hybrid Drop
            print_info(f"Adding raw HEVC video stream (Encode/Hybrid).")
            cmd_mux.extend(['--language', f'{map_str_for_mux}:und'])

            # Keep FPS in sync ---
            if original_fps and original_fps != "0/0":
                fps_with_unit = f"{original_fps}fps"
                print_info(f"Setting default duration for raw HEVC stream: {fps_with_unit}")
                # Use --default-duration 0:FPS to force correct framerate
                cmd_mux.extend(['--default-duration', f'0:{fps_with_unit}'])
            else:
                print_warn("Could not determine original FPS for raw HEVC stream. mkvmerge might default to 25fps.")

            cmd_mux.append(video_input_for_mux)

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

        # --- Add custom global tags from XML (if created) ---
        if custom_hdr_xml_path:
            print_info("Adding custom HDR info tags from XML file.")
            cmd_mux.extend(['--global-tags', custom_hdr_xml_path])

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
            if not files_to_cleanup:
                 files_to_cleanup.extend([
                     os.path.join(output_dir, f"{file_basename}_temp_video_raw.hevc"),
                     os.path.join(output_dir, f"{file_basename}_temp_RPU_original.bin"),
                     os.path.join(output_dir, f"{file_basename}_temp_RPU_P8_converted.bin"),
                     os.path.join(output_dir, f"{file_basename}_temp_editor.json"),
                     os.path.join(output_dir, f"{file_basename}_temp_video_converted.mkv"),
                     os.path.join(output_dir, f"{file_basename}_temp_video_converted.hevc"),
                     os.path.join(output_dir, f"{file_basename}_temp_video_final_dv.hevc"),
                     os.path.join(output_dir, f"{file_basename}_temp_video_no_dv.hevc"),
                     custom_hdr_xml_path if custom_hdr_xml_path else "",
                     *[f['path'] for f in temp_audio_files],
                     *[f['path'] for f in temp_subtitle_files]
                 ])
            sprzataj_pliki(files_to_cleanup)

        raise # Re-raise the exception
