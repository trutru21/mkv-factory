#!/usr/bin/env python3

"""
MKV Factory - Interactive Configuration Module
"""

import os
import re
from typing import List, Dict, Optional, Any

try:
    from .utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, get_file_duration, get_unique_filename, get_unique_languages,
        sanitize_filename, generate_plex_friendly_name, format_stream_description
    )
    from .validation import validate_encoder_param
except ImportError:
    from utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, get_file_duration, get_unique_filename, get_unique_languages,
        sanitize_filename, generate_plex_friendly_name, format_stream_description
    )
    from validation import validate_encoder_param


# --- Phase 2: Interactive Configuration ---

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
