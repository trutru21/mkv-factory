#!/usr/bin/env python3

"""
MKV Factory - Interactive Configuration Module
Version 9.0

Changes:
- introduce keep, drop, convert HDR policies
- remove HDR10 config
"""

import os
import re
from typing import List, Dict, Optional, Any

try:
    from .utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, get_file_duration, get_unique_filename, get_unique_languages,
        sanitize_filename, generate_plex_friendly_name, format_stream_description, resolve_final_filename
    )
    from .validation import validate_encoder_param
except ImportError:
    from utils import (
        Kolory, print_k, print_info, print_warn, print_error, print_header,
        input_k, get_file_duration, get_unique_filename, get_unique_languages,
        sanitize_filename, generate_plex_friendly_name, format_stream_description, resolve_final_filename
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

def _prompt_for_external_file(
    stream_type: str,
    source_duration: Optional[float]
) -> List[Dict[str, Any]]:
    """
    Generic helper to prompt the user for one or more external files
    (audio or subtitle).
    Validates file existence and duration.
    """

    # Set prompts based on type
    if stream_type == "audio":
        type_label = "audio"
        default_lang = "und"
        default_title = "External Audio"
    else:
        type_label = "subtitle"
        default_lang = "und"
        default_title = "External Subtitle"

    print_info(f"Configuring external {type_label} files.")

    external_files = []

    while True:
        prompt_path = f"Enter path to external {type_label} file (or 'd' for done): "
        path = input_k(prompt_path).strip().strip("'\"")

        if path.lower() == 'd':
            break

        if not os.path.exists(path):
            print_warn("File not found. Please try again.")
            continue

        # --- Duration Check ---
        should_continue = True
        if source_duration:
            ext_duration = get_file_duration(path)
            if ext_duration:
                # Allow 1.0s difference
                if abs(ext_duration - source_duration) > 1.0:
                    print_warn(f"WARNING: Video is {source_duration:.2f}s, but this {type_label} is {ext_duration:.2f}s.")
                    if input_k("Continue anyway? [y/N]: ").lower() != 'y':
                        should_continue = False
            else:
                print_warn(f"WARNING: Could not determine the duration of the external file '{os.path.basename(path)}'.")
                print_warn("It might be out of sync.")
                if input_k(f"Do you want to use it anyway? [y/N]: ").lower() != 'y':
                    should_continue = False

        if not should_continue:
            print_info("File discarded.")
            continue

        # --- Metadata Prompts (using defaults) ---
        lang = input_k(f"Enter language code (e.g., pol, eng) [{default_lang}]: ") or default_lang
        title = input_k(f"Enter track title [{default_title}]: ") or default_title

        external_files.append({'path': path, 'lang': lang, 'title': title})
        print_info(f"Added external {type_label} track.")

    return external_files

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
        'has_dv': streams.get('has_dv', False),
        'has_hdr10plus': streams.get('has_hdr10plus', False),
        'dv_profile': streams.get('dv_profile'),
        'final_filename': "",
        'video_stream': streams['video'][0],
        'default_audio_index': 0,
        'default_subtitle_index': -1,
        'encoder': encoder_type,
        'encoder_params': {},
        'auto_cleanup_temp_video': True, # Default for encode, ignored for passthrough
        'final_cleanup_policy': 'ask',
        'video_policy': 'encode',
        'dv_policy': 'keep', # Default
        'hdr10plus_policy': 'keep' # Default
    }

    print_header("Step 2: Configure Full Conversion (Interactive)")

    dv_profile_str = str(config.get('dv_profile'))
    p5_override_active = False # Flag to track if we forced passthrough

    # --- 1. Ask for video policy (Encode/Passthrough) ---
    while True:
        print_k("\nSelect video processing mode:", bold=True)
        print("  1. Encode (change video size and quality)")
        print("  2. Passthrough (copy video 1:1)")
        mode_choice = input_k("Choice [1]: ", Kolory.OKCYAN) or "1"

        if mode_choice == "1":
            config['video_policy'] = 'encode'
            print_info("Selected mode: Encode")

            # --- P5 SANITY CHECK (PART 1) ---
            # Check for P5 *immediately* after selecting encode
            if dv_profile_str == '5':
                print_warn(f"Dolby Vision Profile 5 detected.")
                print_warn(f"Encode policy (NVENC/AMF) is INCOMPATIBLE with IPT-PQ-C2.")
                print_warn(f"The encoder **misinterprets** these colors during processing.")
                print_warn(f"This **permanently corrupts** the output video (bakes in purple/green artifacts).")
                print_warn("OVERRIDE: Forcing 'Pure Passthrough' mode (1:1 copy) **to prevent video corruption during processing**.")

                # Force override config
                config['video_policy'] = 'passthrough'
                config['dv_policy'] = 'keep'
                config['encoder_params'] = {}
                config['auto_cleanup_temp_video'] = False
                p5_override_active = True # Set flag to skip DV policy question

            break # Exit loop

        elif mode_choice == "2":
            config['video_policy'] = 'passthrough'
            print_info("Selected mode: Passthrough (Remux)")
            config['encoder_params'] = {}
            config['auto_cleanup_temp_video'] = False
            break # Exit loop
        else:
            print_warn("Invalid choice. Please enter 1 or 2.")

    # --- 2. Ask for HDR Metadata Policies ---

    print_k("\n--- HDR Metadata Policy ---", Kolory.OKCYAN)

    # --- 2a. Dolby Vision Policy ---
    has_dv = config['has_dv']

    if not has_dv:
        print_info("No Dolby Vision detected. Skipping DV policy.")
        config['dv_policy'] = 'keep' # Keep default

    elif p5_override_active:
        # P5 Sanity Check was triggered, so we locked the policy
        print_info(f"Dolby Vision policy is locked to 'keep' (Pure Passthrough) due to Profile 5.")
        # We already set config['dv_policy'] = 'keep'

    else:
        # Not P5, so we can ask the user safely
        print_k(f"Dolby Vision detected (Profile {dv_profile_str}).", bold=True)
        print_k("Select Dolby Vision Policy:", bold=True)

        # Base options
        if config['video_policy'] == 'passthrough':
            print("  1. Keep (keeps original DV profile, e.g., P7 stays P7)")
        else: # Encode mode
            print("  1. Keep (keeps DV, and if DV is P7, converts to P8 to assure compatibility)")

        print("  2. Drop (remove all Dolby Vision metadata)")

        options = ["1", "2"]
        default_choice = "1"

        # Show "Convert" option only if it's P7 AND we are in passthrough mode
        if dv_profile_str == '7' and config['video_policy'] == 'passthrough':
            print("  3. Convert P7 to P8 (recommended for compatibility)")
            options.append("3")
        # Note: If profile is P8, "Convert" option is correctly hidden

        prompt = f"Your choice ({', '.join(options)}) [{default_choice}]: "
        choice = input_k(prompt, Kolory.OKCYAN) or default_choice

        if choice == "2":
            config['dv_policy'] = 'drop'
            print_info("OK: Dolby Vision metadata will be dropped.")
        elif choice == "3" and dv_profile_str == '7':
            config['dv_policy'] = 'convert7_to_8'
            print_info("OK: DV Profile 7 will be converted to 8.")
        else: # Default or '1'
            config['dv_policy'] = 'keep'
            print_info("OK: Dolby Vision metadata will be kept (with profile-specific logic).")

    # --- 2b. HDR10+ Policy ---
    has_hdr10plus = streams.get('has_hdr10plus', False)

    if not has_hdr10plus:
        print_info("No HDR10+ detected. Skipping HDR10+ policy.")
        config['hdr10plus_policy'] = 'keep' # Keep default
    else:
        print_k("HDR10+ metadata detected.", bold=True)
        print("  1. Keep (default)")
        print("  2. Drop (remove all HDR10+ metadata)")

        choice_hdr10 = input_k("Select HDR10+ Policy [1]: ", Kolory.OKCYAN) or "1"

        if choice_hdr10 == "2":
            config['hdr10plus_policy'] = 'drop'
            print_info("OK: HDR10+ metadata will be dropped.")
        else:
            config['hdr10plus_policy'] = 'keep'
            print_info("OK: HDR10+ metadata will be kept.")

    # --- 3. Load or Ask for Encoder Params ---
    loaded_from_profile = False
    if profile_data:
        cleanup_profile = profile_data.get('cleanup_policy', {})
        config['auto_cleanup_temp_video'] = cleanup_profile.get('auto_cleanup_temp_video', True)
        if 'final_cleanup' in cleanup_profile:
            config['final_cleanup_policy'] = cleanup_profile['final_cleanup']

        # This check is now safe, it respects the P5 override
        if config['video_policy'] == 'encode':
            config['encoder_params'] = profile_data[encoder_type]['encoder_params']
            params_str = ", ".join(f"{k}={v}" for k, v in config['encoder_params'].items())
            cleanup_str = "Yes" if config['auto_cleanup_temp_video'] else "No"
            final_cleanup_str = config.get('final_cleanup_policy', 'ask')
            print_info(f"Loaded profile settings for '{encoder_type}': {params_str}")
            print_info(f"Loaded cleanup policy: Auto-cleanup temp video={cleanup_str}, Final cleanup={final_cleanup_str}")
            loaded_from_profile = True
        else:
            print_info("Passthrough mode selected, skipping profile encoder settings.")

    # This 'if' block is also now safe thanks to the P5 override
    if config['video_policy'] == 'encode' and not loaded_from_profile:
        params, cleanup = _ask_encoder_params(encoder_type)
        config['encoder_params'] = params
        config['auto_cleanup_temp_video'] = cleanup
    elif config['video_policy'] == 'passthrough':
         print_info("Passthrough mode selected, skipping interactive encoder configuration.")

    # --- 4. Filename Logic ---

    suggested_name = generate_plex_friendly_name(source_file, config)
    prompt = f"Enter the final output filename [{suggested_name}]: "
    user_filename = input_k(prompt)
    chosen_filename = user_filename or suggested_name

    config['final_filename'] = resolve_final_filename(output_dir, chosen_filename)

    # --- 5. Audio & Subtitle Selection ---

    # ### Internal Audio Selection ###
    print_k("\n--- Audio Configuration ---", Kolory.OKCYAN)
    if input_k("Process internal audio tracks from source file? [Y/n]: ").lower() != 'n':
        config['audio_tracks'] = _configure_internal_tracks(
            stream_type="audio",
            available_streams=streams['audio']
        )
    else:
        print_info("Skipping internal audio tracks.")
        config['external_audio_files'] = _prompt_for_external_file(
            stream_type="audio",
            source_duration=source_duration
        )

    # ### Internal Subtitle Selection ###
    print_k("\n--- Subtitle Configuration ---", Kolory.OKCYAN)
    if input_k("Process internal subtitle tracks from source file? [Y/n]: ").lower() != 'n':
        config['subtitle_tracks'] = _configure_internal_tracks(
            stream_type="subtitle",
            available_streams=streams['subtitle']
        )
    else:
        print_info("Skipping internal subtitle tracks.")
        config['external_subtitle_files'] = _prompt_for_external_file(
            stream_type="subtitle",
            source_duration=source_duration
        )

    # --- 6. Default Track Selection ---
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
