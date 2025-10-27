#!/usr/bin/env python3

"""
MKV Factory - Processing & Execution Module
(Extraction, Conversion, Muxing)
"""

import os
import re
import json
from typing import List, Dict, Optional, Any

try:
    from .utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, run_command, skasuj_plik, sprzataj_pliki,
        sanitize_filename
    )
except ImportError:
    from utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, run_command, skasuj_plik, sprzataj_pliki,
        sanitize_filename
    )


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

                # --- Force original FPS for raw HEVC input ---
                video_stream_config = config.get('video_stream', {})
                original_fps = video_stream_config.get('r_frame_rate') # e.g., "24000/1001"

                if not original_fps or original_fps == "0/0":
                    print_warn("Could not find 'r_frame_rate' in config, falling back to 'avg_frame_rate'.")
                    original_fps = video_stream_config.get('avg_frame_rate')

                if original_fps and original_fps != "0/0":
                    print_info(f"Forcing input framerate to {original_fps} for ffmpeg.")
                    # Add framerate flag BEFORE the input
                    cmd_convert.extend(['-framerate', original_fps])
                else:
                    print_warn("Could not determine original FPS. FFmpeg will guess, which may cause desync!")

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
