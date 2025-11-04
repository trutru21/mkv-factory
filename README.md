# MKV Factory

#### Version 9.0


A smart, profile-driven Python tool for automating GPU-enabled MKV conversion and remuxing built to handle HDR metadata, letting you define granular policies: keep, drop, or convert Dolby Vision / HDR10+ metadata, ensuring compatibility with your media server (Plex, Jellyfin, etc.) and players.

Smart track selection lets you automatically strip MKV's from unwanted languages and subs, while encoding the video to space-saving format in the same time.

Want to process entire folders? Specify all your policies (video, audio/subtitle languages, HDR rules) in a single profile.json, and the script will automate the rest.

Need to fine-tune your MKVs? You can extract the best parts from different MKVs — video, audio, and subtitles — and merge them into one flawless MKV of your design.


---
## Key Features

- **Profile-driven Automation:** Define your preferences in a `profile.json` file – encoding settings, language selections, and cleanup rules.
- **Dual-Mode Operation:**
    - **Interactive Mode:** Process single files step-by-step with full control over tracks selection.
    - **Batch Mode:** Select a source folder, provide a profile, and let it process all video files according to your rules.
- **Efficient HEVC Encoding:** Transcode large Blu-ray rips to space-saving H.265/HEVC using Nvidia or AMD hardware acceleration.
- **Flexible Video Passthrough (Remux):** Copy the video stream 1:1, or perform lossless hybrid operations like converting DV P7->P8 or stripping metadata (DV/HDR10+) while preserving the original video quality.
- **Advanced Dynamic HDR Control**: Full control over dynamic HDR metadata. Independently manage Dolby Vision (keep, drop, convert P7->P8) and HDR10+ (keep, drop) policies.
- **Smart Track Selection:** Define preferred languages, codec priorities (e.g., TrueHD > DTS > AC3), and exclusion keywords (e.g., "commentary") in your profile for automated, intelligent audio and subtitle track selection.
- **Flexible Stream Injection:** Ever wished you could merge the best parts of two rips? Now you can! Easily combine video, audio, and subtitles from any source into your perfect MKV.
- **Plex-Friendly Naming:** Generates clean, organized filenames compliant with media server standards (e.g., `Movie Title (Year) [2160p HEVC CQ16 DV].mkv`).
- **Detailed Logging:** Creates a timestamped log file for each run, making it easy to track progress, verify settings, and troubleshoot issues.

### Static HDR10 and Dolby Vision Profile 5 Limitation Notice

**Static HDR10:** This script attempts to preserve static HDR10 metadata for files without DV/HDR10+ by mapping it during the encode. However, this method's success is not guaranteed and depends on ffmpeg's ability to read the source metadata. For files that have static HDR10 **only**, using Passthrough Mode is the most reliable method to ensure it is preserved. For files with DV/HDR10+ the static tags are included in the respective streams for both Encode and Passthrough modes.

**Dolby Vision Profile 5 :** Encoding DV5 is incompatible. This profile's IPT-PQ-C2 color matrix cannot be correctly processed by the tools used in this script. Attempting would result in corrupted (purple/green) video.
    - The script detects DV P5 and **automatically forces pure Passthrough mode** (1:1 copy) to prevent video corruption during processing.
    - The resulting output file will retain the original Profile 5 stream and will likely appear purple/green on most players due to lack of IPT-PQ-C2 support. Correct playback requires compatible hardware (e.g., Nvidia Shield).

---
## Prerequisites

Before running the script, you must have the following software packages installed. The script will verify the presence of the specific command-line tools they provide.

- **FFmpeg:** Provides the core `ffmpeg` and `ffprobe` commands.
- **MKVToolNix:** Provides the `mkvmerge` and `mkvextract`commands.
- **dovi_tool:** Handles Dolby Vision metadata.
- **hdr10plus_tool:** Handles HDR10+ metadata.

### Optional (but recommended)

By default, the script 's autofilename logic will remove non-ASCII characters (like ś, π, ó, etc.). If you want to transliterate them (e.g., ś -> s), you must install the Unidecode library (see the next chapter for details).

---
## Environment Setup (Linux)

To ensure all dependencies are met without cluttering your host system, it is highly recommended to use a **Distrobox container**. The following steps will create an Ubuntu container and install all necessary tools.

> **Windows Users:** If you are not using a Linux-based OS, please skip to the **Windows Setup Guide** section at the end of this document.

### Step 0: Install Distrobox (If Not Present)

Some Linux distributions come with Distrobox pre-installed. If your system does not have it, you can easily install it.

You need Podman (or, alternatively, Docker) and Distrobox.
For Debian/Ubuntu/Mint:
```bash
sudo apt update
sudo apt install -y podman distrobox
```
For Fedora:
```bash
sudo dnf install -y podman distrobox
```
`Note:` After installing, you may need to log out and log back in for all changes (like user group permissions for Podman) to take effect.

### Step 1: Create the Distrobox Container

Run this command once in your host terminal. It will create a new Ubuntu container named `mkv-factory`, give it GPU access, and mount your media folders.

> **Important:** Replace `/path/to/your/movies` with the actual paths to your media directories. You can add as many `--volume` flags as you need.

**For Nvidia users:**
```bash
distrobox create -n mkv-factory -i ubuntu:latest --nvidia --volume /path/to/your/movies:/path/to/your/movies:rw --volume /path/to/your/downloads:/path/to/your/downloads:rw
```

**For AMD users:**
Simply remove the `--nvidia` flag. Distrobox will typically handle GPU access automatically.
```bash
distrobox create -n mkv-factory -i ubuntu:latest --volume /path/to/your/movies:/path/to/your/movies:rw --volume /path/to/your/downloads:/path/to/your/downloads:rw
```
`Note`: I don't own an AMD GPU, so this feature was **not** tested. If you find it working - let me know!

### Step 2: Enter the Container
```bash
distrobox enter mkv-factory
```

### Step 3: Install Tools Inside the Container
```bash
sudo apt install -y \
  ffmpeg=6.1.1-3ubuntu5 \
  mkvtoolnix=82.0-1build2 \
  wget

wget https://github.com/quietvoid/dovi_tool/releases/download/2.3.1/dovi_tool-2.3.1-x86_64-unknown-linux-musl.tar.gz
tar -xvf dovi_tool-2.3.1-x86_64-unknown-linux-musl.tar.gz
sudo mv dovi_tool /usr/local/bin/
rm dovi_tool-2.3.1-x86_64-unknown-linux-musl.tar.gz

wget https://github.com/quietvoid/hdr10plus_tool/releases/download/1.5.2/hdr10plus_tool-1.5.2-x86_64-unknown-linux-musl.tar.gz
tar -xvf hdr10plus_tool-1.5.2-x86_64-unknown-linux-musl.tar.gz
sudo mv hdr10plus_tool /usr/local/bin/
rm hdr10plus_tool-1.5.2-x86_64-unknown-linux-musl.tar.gz
```
The specific package versions are pinned to ensure script compatibility. These versions were tested with the mkv_factory logic.

### Step 4: Install Unidecode (optional)

```bash
sudo apt install python3-unidecode
```

Your environment is now ready. Copy the `mkv_factory.py` file **and** the entire `lib` directory from the project repository into your working directory (e.g., your mounted media folder).


### Step 5: Running the Script

Make sure the script is executable before running it directly:
``` bash
chmod +x mkv_factory.py
```

Then you can launch it like this:

``` bash
./mkv_factory.py -i "/path/to/your/movie.mkv"
```

Alternatively, you can run it explicitly with Python (no need to make it executable):

``` bash
python3 mkv_factory.py -i "/path/to/your/movie.mkv"
```

---
## How to Use

The script operates in one of two modes, depending on the arguments provided.

### A) Interactive Mode (for a single file)

This mode is ideal for processing a single file or when you need to inject audio and subtitles from external sources (see Advanced Use Case). It guides you through the process step-by-step. Upon launch, choose one of two processing paths: 
- **Full Conversion:** This path processes all streams and asks you to select the **Video Policy**:
  -  **Encode:** Re-encode video quality/size using GPU (NVENC/AMF) settings.
  - **Passthrough:** Copy video stream 1:1.
- **Extraction Only:** (No conversion) Select and demux a single track (audio, video, or subtitle) to a separate file (e.g., `.mka`, `.srt`, `.hevc`).

The script will automatically suggest a clean filename and validate your choices against internal logic (e.g., blocking incompatible Profile 5 encode attempts).

To run:
```bash
./mkv_factory.py -i "/path/to/your/movie.mkv"
```

`Tip`: You can still use a profile in this mode to skip the initial quality-related questions. Note that audio/subtitle selection rules are ignored in this mode (you will be asked interactively), but encoder params and cleanup policy will be loaded.
```bash
./mkv_factory.py -p profile.json -i "/path/to/your/movie.mkv"
```

### B) Batch Mode (for a whole folder)

This mode will process the entire folder (**not** including the subfolders) and convert the supported movie containers according to the profile.json policies. To trigger it, add the following flags to the run command:
- **-p** (profile file path) 
- **-s** (source path)
- **-o** (output path)

```bash
./mkv_factory.py -p profile.json -s "/path/to/your/movies/" -o "/path/to/save/conversions/"
```
Please refer to the "Configuration File Description" chapter for info on how to properly configure the batch run.

> Please note that audio and subtitle tracks are never re-encoded; they are always copied (passthrough).

### Capturing Logs

The script can log its outputs to a file. This can be enabled by adding the following argument.
Note that as this works for the batch mode, it is recommended to configure logging inside the profile.json file.

```bash
./mkv_factory.py -i "/path/to/your/movie.mkv" --log
```

---
## Advanced Use Case: The Custom Remux

Scenario: You have `Movie_A.mkv` with excellent Dolby Vision/HDR video but poor audio (or no subtitles in your language), and `Movie_B.mkv` with the perfect TrueHD Atmos audio track and subtitles you need.

### Step 1: Extract the Audio/Subs Streams 

Extract the Audio:
```bash
1. Run the script pointing to Movie_B.mkv
2. Choose Extraction Only mode
3. Select the desired audio track and confim the file name
The script will extract and save it to your working directory
```

Extract the Subtitles:
```bash
1. Run the script again, pointing to Movie_B.mkv
2. Choose Extraction Only mode
3. Select the desired subtitle track and confirm the file name
The script will extract and save it to your working directory
```

You now have the audio and subtitle streams ready in separate files.

### Step 2: Convert the Main File and Inject the Streams

Now, run the script in Full Conversion mode, using the file with the best video as your base.

Start the Conversion Process:
```bash
1. Run the script, pointing it to Movie_A.mkv (the one with the excellent video you want to keep).
2. Choose Full Convertion mode.
3. Provide your desired output filename and encoder settings.
4. Inject External Audio:
When asked, Use audio tracks from the source file? [Y/n]:, answer n (No).
The script will then prompt you to provide the path to an external file.
Enter the path to best_audio.mka and fill in the language (e.g., eng) and title.
5. Inject External Subtitles:
When asked, Use subtitles from the source file? [Y/n]:, answer n (No).
Provide the path to subtitles and fill in the language (e.g., eng) and title.
```
`Note`: You can add multiple audio and/or subtitle files — just keep adding them, and press "d" when you're done.

The script now converts your movie using the video from Movie_A.mkv and the external audio/subtitles you added — automatically checking their durations and warning you if they’re out of sync.

---
## Configuration File Description (profile.json)

The `profile.json` file defines all rules for Batch Mode and some values for interactive mode.

### Video & HDR Policies

These are the most important settings, defining the high-level behavior of the script.
```json
{
  "video_policy": "passthrough",
  "hdr_policy": {
    "dv_policy": "convert7_to_8",
    "hdr10plus_policy": "keep"
  }
}
```
- **video_policy** (String): Defines the main video processing method.
  - **encode** (default): Re-encodes the video stream using the nvenc or amf settings to reduce the file size. This is a "lossy" process.
  - **"passthrough"**: Copies the original video stream without re-encoding. This is a "lossless" process. The nvenc and amf sections are ignored.

- **hdr_policy** (Object): This (optional) object gives you granular control over Dolby Vision and HDR10+ metadata.
  - **dv_policy** (String): Defines how to handle Dolby Vision. Defaults to `keep`.
    - **keep**: Keeps the Dolby Vision metadata.
      - In `passthrough` mode, this preserves the original DV profile (P7 stays P7).
      - In `encode` mode, this preserves the metadata but forces a DV P7->P8 conversion to ensure compatibility.
    - **drop** Removes all Dolby Vision (RPU) metadata from the file.
    - **convert7_to_8**: Ensures the output is Dolby Vision Profile 8.
      - In `passthrough` mode, this runs dovi_tool convert to convert P7 to P8.
      - In `encode` mode, this behaves identically to "keep".
      - If the file is already P8, this behaves identically to `keep`.
      
      `Note:` Converting Dolby Vision Profile 5 is currently not supported. If DV P5 is detected, and override is enabled, forcing the `video_policy` to `passthrough` and `hdr_policy` to `keep`.
  - **hdr10plus_policy** (String): Defines how to handle HDR10+ metadata. Defaults to `keep`.
    - **keep**: Preserves the HDR10+ metadata.
    - **drop**: Removes all HDR10+ metadata.

### Encoder Params (nvenc, amf)

`Note:` This section is ignored if "video_policy" is set to `"passthrough"'.

Defines parameters for specific encoders. The script automatically uses the section matching the detected GPU.

```json
  "nvenc": {
      "encoder_params": {
      "cq": "16",
      "preset": "p7"
    }
  },
    "amf": {
    "encoder_params": {
      "qp": "16",
      "quality": "quality"
    }
  }
```

- **cq** (String) (for nvenc, Nvidia): Constant Quality level, validated in the range 10–40. 16 is recommended for 4K.
- **preset** (String) (for nvenc, Nvidia): Speed/quality preset, validated: p1 (fastest) to p7 (best quality).
- **qp** (String) (for amf, AMD): Quantization Parameter, validated in the range 10–40. 16 is recommended for 4K.
- **quality** (String) (for amf, AMD): Speed/quality setting. Valid values: speed, balanced, quality.

### Audio and Subtitles Selection

Defines automatic stream selection rules.

```json
  "audio_selection": {
    "policy": "best_per_language",
    "languages": ["eng", "pol"],
    "preferred_codecs": ["truehd", "dts-hd ma", "eac3", "dts","ac3"],
    "exclude_titles_containing": ["commentary", "director", "description"],
    "default_track_language": "eng"
  },
  "subtitle_selection": {
    "policy": "best_per_language",
    "languages": ["eng","pol"],
    "preferred_codecs": ["subrip", "hdmv_pgs_subtitle"],
    "exclude_titles_containing": ["forced", "sdh"],
    "default_track_language": "eng",
    "default_mode": "first"
  }
```

- **policy:** (String) - Defines the main behavior of automatic track selection.
  - **all** — Selects all found tracks of the given type (audio or subtitles). If policy is set to "all", it ignores languages, preferred_codecs, and exclude_titles_containing flags.
  - **best_per_language** (default) — Selects one best track per language defined in languages.
- **languages** (String or List) — Used only when policy = "best_per_language".
  - Accepts language codes in ISO 639-2 (three-letter, e.g. "eng", "pol", "spa").
  - **all** — processes all detected languages using the defined filters.
  - ["eng", "pol"] — processes only tracks matching those language codes.
- **preferred_codecs** (List) — Used only with "best_per_language". List of codecs ordered from most to least preferred. Note that if the mkv does not contain any of the "preferred" codecs, the script will simply choose another one.
  - `Example:` ["truehd", "dts-hd ma", "eac3", "dts", "ac3"] - processes all tracks matching the defined filters.
- **exclude_titles_containing** (List) — Used only with "best_per_language". List of case-insensitive phrases that disqualify a track.
  - `Example:` ["commentary", "director", "description"]
- **default_track_language** (String) — Language code (three letters, e.g., "eng" or "pol") to set as default. If multiple matches are found, the first one is marked as default. Can also be set to "none" for subtitles (if set to "none" ensure the default_mode flag is set to "none as well!).
- **default_mode** (String) (Subtitles only) — Controls default subtitle behavior. 
  - **first** — Sets the first subtitle track as default if default_track_language isn’t found (only if subtitles exist). 
  - **none** — Recommended if you don’t want any default subtitles. Ensures no default track is set.

### Cleanup Policy

Defines rules for handling temporary files (_temp_video.hevc, _temp_RPU.bin, etc.).

```json
"cleanup_policy": {
  "auto_cleanup_temp_video": true,
  "final_cleanup": "on_success"
}
```
- **auto_cleanup_temp_video** (Boolean) (Encode mode only)
  - true: Deletes the largest temp file (_temp_video) immediately after GPU transcoding to free up the disk space as soon as possible.
  - false: Keeps it until final cleanup.
- **final_cleanup** (String) Determines when to remove all remaining temp files:
 - "on_success" — Only if the full conversion succeeded.
 - "always" — Always clean up, even after errors (recommended for batch mode).
 - "never" — Never delete temp files (useful for debugging).
 - "ask" — Ask the user (interactive mode only).

### Logging

Controls file-based logging.

```json
"logging": {
  "log_to_file": true,
  "log_filename": "mkv_factory.log"
}
```
- **log_to_file** (Boolean) — true enables logging, false disables it. Can be overridden with --log.
- **log_filename** (String) — Name of the log file to be created in the output directory.

### profile.json Examples

Here are a few profile examples for typical usecases.

`Example 1: Encode (High Quality, All Tracks)` 
This profile will:
- transcode video stream with high quality settings,
- keep Dolby Vision (forcing P7->P8 conversion if needed),
- include all of the found audio and subtitles,
- set the default audio to English,
- set the default subtitles to "none",
- perform cleanup of temp video file after encoding, and rest of the temp files on success,
- log all steps to mkv_factory.log file.
```json
{
  "video_policy": "encode",
  "hdr_policy": {
    "dv_policy": "keep",
    "hdr10plus_policy": "keep"
  },
  "nvenc": {
    "encoder_params": {
      "cq": "16",
      "preset": "p7"
    }
  },
  "amf": {
    "encoder_params": {
      "qp": "16",
      "quality": "quality"
    }
  },
  "audio_selection": {
    "policy": "all",
    "default_track_language": "eng"
  },
  "subtitle_selection": {
    "policy": "all",
    "default_track_language": "eng",
    "default_mode": "none"
  },
  "cleanup_policy": {
    "auto_cleanup_temp_video": true,
    "final_cleanup": "on_success"
  },
  "logging": {
    "log_to_file": true,
    "log_filename": "mkv_factory.log"
  }
}
```

`Example 2: Encode (Filtered Tracks)`
This profile will:
- transcode video stream with high quality settings,
- keep Dolby Vision (forcing P7->P8 conversion if needed),
- exclude commentaries audio tracks,
- include one best English, and one best Polish audio track (TrueHD is most preferred),
- set the default audio track to English,
- exlude any forced or sdh-type subtitles,
- include one best polish subtitle track (.srt is most preffered),
- set the only Polish subtitles track as default,
- perform cleanup of temp video file after encoding, and rest of the temp files on success,
- log all steps to mkv_factory.log file.

```json
{
  "video_policy": "encode",
  "hdr_policy": {
    "dv_policy": "keep",
    "hdr10plus_policy": "keep"
  },
  "nvenc": {
    "encoder_params": {
      "cq": "16",
      "preset": "p7"
    }
  },
  "amf": {
    "encoder_params": {
      "qp": "16",
      "quality": "quality"
    }
  },
  "audio_selection": {
    "policy": "best_per_language",
    "languages": ["eng", "pol"],
    "preferred_codecs": [
      "truehd",
      "dts-hd ma",
      "eac3",
      "dts",
      "ac3"
    ],
    "exclude_titles_containing": ["commentary", "director", "description"],
    "default_track_language": "eng"
  },
  "subtitle_selection": {
    "policy": "best_per_language",
    "languages": ["pol"],
    "preferred_codecs": ["subrip", "hdmv_pgs_subtitle"],
    "exclude_titles_containing": ["forced", "sdh"],
    "default_track_language": "pol",
    "default_mode": "first"
  },
  "cleanup_policy": {
    "auto_cleanup_temp_video": true,
    "final_cleanup": "on_success"
  },
  "logging": {
    "log_to_file": true,
    "log_filename": "mkv_factory.log"
  }
}
```
`Example 3: Encode (All Languages, Best Track)`
This profile will:
- transcode the video using high-quality encoder settings,
- keep Dolby Vision (forcing P7->P8 conversion if needed),
- scan all detected audio languages (languages: "all"),
- for each detected language, select only one best audio track (policy: "best_per_language") that is not a commentary track,
- set English as the default audio language,
- scan all detected subtitle languages (languages: "all"),
- for each detected language, select only one best subtitle track that is not marked as “forced” or “SDH”, preferring the .srt format,
- set Polish as the default subtitle language,
- clean up all temporary files after a successful conversion.
- log all steps to mkv_factory.log file.
```json
{
  "video_policy": "encode",
  "hdr_policy": {
    "dv_policy": "keep",
    "hdr10plus_policy": "keep"
  },
  "nvenc": {
    "encoder_params": {
      "cq": "16",
      "preset": "p7"
    }
  },
  "amf": {
    "encoder_params": {
      "qp": "16",
      "quality": "quality"
    }
  },
  "audio_selection": {
    "policy": "best_per_language",
    "languages": "all",
    "preferred_codecs": [
      "truehd",
      "dts-hd ma",
      "eac3",
      "dts",
      "ac3"
    ],
    "exclude_titles_containing": ["commentary", "director", "description"],
    "default_track_language": "eng"
  },
  "subtitle_selection": {
    "policy": "best_per_language",
    "languages": "all",
    "preferred_codecs": ["subrip", "hdmv_pgs_subtitle"],
    "exclude_titles_containing": ["forced", "sdh"],
    "default_track_language": "pol",
    "default_mode": "first"
  },
  "cleanup_policy": {
    "auto_cleanup_temp_video": true,
    "final_cleanup": "on_success"
  },
  "logging": {
    "log_to_file": true,
    "log_filename": "mkv_factory.log"
  }
}
```

`Example 4: Passthrough (Remux) Profiles`

These profiles **skip video encoding**, preserving the original video quality. The nvenc and amf sections are omitted as they are not used.

`Example 4a: Pure Passthrough`
(for DV5-DV7 compatible players, e.g., Nvidia Shield)
This profile will:
- copy (remux) the video stream 1:1, preserving original quality, 
- keep the original DV Profile (P5/P7/P8) and HDR10+,
- select the best audio track for English and Polish (excluding commentaries),
- select the best subtitle track for Polish (excluding forced/sdh),
- set English as the default audio language, and Polish as the default subs.
- clean up temp files on success,
- log all steps to mkv_factory.log file.
```json
{
  "video_policy": "passthrough",
  "hdr_policy": {
    "dv_policy": "keep",
    "hdr10plus_policy": "keep"
  },
  "audio_selection": {
    "policy": "best_per_language",
    "languages": ["eng", "pol"],
    "preferred_codecs": ["truehd", "dts-hd ma"],
    "exclude_titles_containing": ["commentary", "director", "description"],
    "default_track_language": "eng"
  },
  "subtitle_selection": {
    "policy": "best_per_language",
    "languages": ["pol"],
    "preferred_codecs": ["subrip", "hdmv_pgs_subtitle"],
    "exclude_titles_containing": ["forced", "sdh", "deaf"],
    "default_track_language": "pol",
    "default_mode": "first"
  },
  "cleanup_policy": {
    "final_cleanup": "on_success"
  },
  "logging": {
    "log_to_file": true,
    "log_filename": "mkv_factory.log"
  }
}
```
`Example 4b: Hybrid Passthrough (Best Compatibility)`

This profile will:
- copy (remux) the video stream, preserving original quality and HDR10+,
- convert incompatible DV Profile P7 to a compatible Profile 8,
- select the best audio track for English and Polish (excluding commentaries),
- select the best subtitle track for Polish (excluding forced/sdh),
- set English as the default audio language, and Polish as the default subs.
- clean up temp files on success.

```json
{
  "video_policy": "passthrough",
  "hdr_policy": {
    "dv_policy": "convert7_to_8",
    "hdr10plus_policy": "keep"
  },
  "audio_selection": {
    "policy": "best_per_language",
    "languages": ["eng", "pol"],
    "preferred_codecs": ["truehd", "dts-hd ma"],
    "exclude_titles_containing": ["commentary", "director", "description"],
    "default_track_language": "eng"
  },
  "subtitle_selection": {
    "policy": "best_per_language",
    "languages": ["pol"],
    "preferred_codecs": ["subrip", "hdmv_pgs_subtitle"],
    "exclude_titles_containing": ["forced", "sdh", "deaf"],
    "default_track_language": "pol",
    "default_mode": "first"
  },
  "cleanup_policy": {
    "final_cleanup": "on_success"
  },
  "logging": {
    "log_to_file": true,
    "log_filename": "mkv_factory.log"
  }
}
```
`Example 4c: Hybrid Passthrough (Drop DV)`
(For players that support HDR10+ but not Dolby Vision, or servers like Plex that struggle with DV transcoding)
This profile will:
- copy (remux) the video stream, preserving original quality and HDR10+,
- remove (drop) all Dolby Vision metadata,
- select the best audio track for English and Polish (excluding commentaries),
- select the best subtitle track for Polish (excluding forced/sdh),
- set English as the default audio language, and Polish as the default subs.
- clean up temp files on success.

```json
{
  "video_policy": "passthrough",
  "hdr_policy": {
    "dv_policy": "drop",
    "hdr10plus_policy": "keep"
  },
  "audio_selection": {
    "policy": "best_per_language",
    "languages": ["eng", "pol"],
    "preferred_codecs": ["truehd", "dts-hd ma"],
    "exclude_titles_containing": ["commentary"],
    "default_track_language": "eng"
  },
  "subtitle_selection": {
    "policy": "best_per_language",
    "languages": ["pol"],
    "preferred_codecs": ["subrip", "hdmv_pgs_subtitle"],
    "exclude_titles_containing": ["forced", "sdh"],
    "default_track_language": "pol",
    "default_mode": "first"
  },
  "cleanup_policy": {
    "final_cleanup": "on_success"
  },
  "logging": {
    "log_to_file": true,
    "log_filename": "mkv_factory.log"
  }
}
```
---
## Validating Your MKV

Want to be 100% sure your new MKV is in a good shape? Run these commands after conversion.

```bash
mkvmerge -o /dev/null "YOUR-FILE-NAME.mkv"
ffmpeg -i "YOUR-FILE-NAME.mkv" -f null -
```
If both commands go through without errors, you're good to go.

---
## But my movie is not in an MKV container!

No worries, you're not out of luck. Simply repack your container into MKV without any conversion:

```bash
ffmpeg -i "YOUR-FILE-NAME.mp4" -c copy "YOUR-FILE-NAME.mkv"
```
---
## Windows Setup Guide

Linux OS is preferred, but Windows is supported with some additional hassle:

### Step 1: Install Python

Download the latest Python installer from python.org.  
Run the installer.  
**CRITICAL:** On the first screen of the installer, you must check the box that says *"Add Python to PATH"*.  

### Step 2: Download & Organize Tools

Create a central folder for your tools, for example: `C:\Tools`.

**FFmpeg:**
- Download the `full_build` .7z or .zip from [gyan.dev](https://ffmpeg.org/download.html).
- Extract the archive. Copy the contents of the `bin` folder inside to `C:\Tools\ffmpeg\bin`.

**MKVToolNix:**
- Download the installer from the [official website](https://mkvtoolnix.download/downloads.html).
- Install it to the default location (`C:\Program Files\MKVToolNix`).

**dovi_tool:**
- Download the Windows archive `...pc-windows-msvc.zip` from [GitHub Releases](https://github.com/quietvoid/dovi_tool/releases).
- Extract the `dovi_tool.exe` file and place it in `C:\Tools\dovi_tool`.

**hdr10plus_tool**

- Download the latest ...pc-windows-msvc.zip release from [GitHub Releases](https://github.com/quietvoid/hdr10plus_tool/releases)
- Extract hdr10plus_tool.exe and place it in `C:\Tools\hdr10plus_tool`

### Step 3: Configure the PATH Environment Variable

1. Press the Windows key and type "environment variables". Select "Edit the system environment variables".
2. In the new window, click the "Environment Variables..." button.
3. In the bottom section ("System variables"), find and select the Path variable, then click "Edit...".
4. Click "New" and add:
   ```
   C:\Tools\ffmpeg\bin
   C:\Program Files\MKVToolNix
   C:\Tools\dovi_tool
   C:\Tools\hdr10plus_tool
   ```
5. Click "OK" on all windows to save the changes.

### Step 4 Install Unidecode and Colorama (optional)

For non-ASCII characters transliteration, install Unidecode.
For nicely colored console logs, install Colorama.

1.  Open **Command Prompt** or **PowerShell**.
2.  Run the following command:

```powershell
pip install unidecode
pip install colorama
```
*(If you have multiple Python versions installed, you may need to use `pip3` instead):*

```powershell
pip3 install unidecode
pip3 install colorama
```

### Step 5: Verify the Installation

1. **Copy Script Files:** Copy the `mkv_factory.py` file **and** the entire `lib` directory from the project repository into the folder where you want to run the conversions (e.g., `C:\MyMovies`).

2. Open PowerShell (press Windows key > type PowerShell > press Enter) or open a Command Prompt.
Make sure you open a new window after editing the PATH variable.

```powershell
ffmpeg -version
mkvmerge -V
dovi_tool --version
hdr10plus_tool --version
pip show unidecode (optional)
pip show colorama (optional)
```

If all commands succeed, your environment is ready.


`Note`: I did not test this tool on a Windows PC. If you find it working - let me know!

## Acknowledgements

This project relies on the outstanding open-source work behind FFmpeg, MKVToolNix, and dovi_tool. All credit goes to their respective developers.

## Future Plans

This may, or may not happen :)
- `hevc_qsv` support for integrated Intel GPU's
- Batch processing results file (detailed summary of processed files)

## Support / Buy Me a Coffee ☕️

If you enjoy using **MKV Factory** and want to support its development, you can buy me a coffee:

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/yellow_img.png)](https://buymeacoffee.com/trutru21)

Every coffee helps keep this project alive and improves future updates. Thank you for your support!
