#!/usr/bin/env python3

"""
MKV Factory - Profile Validation Module
"""

from typing import Dict, Any

# Import helper functions from lib
try:
    from .utils import print_info, print_warn, print_error
except ImportError:
    from utils import print_info, print_warn, print_error


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
