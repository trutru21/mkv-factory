#!/usr/bin/env python3

"""
MKV Factory - Automated Configuration Module
"""

import re
from typing import List, Dict, Optional, Any

try:
    from .utils import (
        print_k, print_info, print_warn, print_error, print_header,
        get_unique_filename, get_unique_languages,
        generate_plex_friendly_name, format_stream_description
    )
except ImportError:
    from utils import (
        print_k, print_info, print_warn, print_error, print_header,
        get_unique_filename, get_unique_languages,
        generate_plex_friendly_name, format_stream_description
    )


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
