# MKV Factory

#### Version 8.3

A smart, profile-driven Python tool for automating MKV conversion and remuxing. Built for high-quality Blu-ray rips to preserve Dolby Vision and HDR10/HDR10+ metadata. It compresses high-bitrate video files into smaller, media-server-ready MKVs with minimal to no perceptible loss in visual quality.

Want to process entire folders? This tool got you covered. Specify the processing policies (e.g., encoding quality, audio/subtitle languages, etc.) in a profile, and the script will take care of the rest.

Need to fine-tune your MKVs? You can easily extract the best parts from different MKVs — video, audio, and subtitles — and merge them into one flawless MKV of your design!

---
## Key Features

- **Profile-driven Automation:** Define your preferences in a `profile.json` file – encoding settings, language selections, cleanup rules – and let the script handle the repetitive work.
- **Dual-Mode Operation:**
    - **Interactive Mode:** Process single files step-by-step with full control over track selection. Ideal for unique cases or testing profiles.
    - **Batch Mode:** Point the script at a source folder, provide a profile, and let it process all video files automatically according to your rules.
- **Efficient HEVC Encoding:** Transcode large Blu-ray rips (H.264 or HEVC) to space-saving H.265/HEVC using hardware acceleration.
- **Full Video Passthrough (Remux):** Don't need to re-encode? Use the `passthrough` mode to copy the video stream untouched while still allowing you to select and remux audio/subtitle tracks.
- **Dolby Vision Profile Conversion:** Automatically converts incompatible Blu-ray Dolby Vision 7 profile to the widely compatible **Profile 8**, ensuring playback on media servers like Plex and modern devices.
- **Hardware Acceleration:** Automatically detects Nvidia (NVENC) or AMD (AMF) hardware encoders for fast conversions.
- **Smart Track Selection:** Define preferred languages, codec priorities (e.g., TrueHD > DTS > AC3), and exclusion keywords (e.g., "commentary") in your profile for automated, intelligent audio and subtitle track selection.
- **Flexible Stream Injection:** Ever wished you could merge the best parts of two rips? Now you can! Easily combine video, audio, and subtitles from any source into your perfect MKV.
- **Reliable Extraction:** Uses mkvextract for demuxing streams, avoiding the corruption issues that can occur with ffmpeg's -c copy on complex HEVC streams.
- **Plex-Friendly Naming:** Generates clean, organized filenames compliant with media server standards (e.g., `Movie Title (Year) [2160p HEVC CQ16 DV].mkv` or `Movie Title (Year) [1080p HEVC REMUX HDR].mkv`).
- **Detailed Logging:** Creates a timestamped log file for each run, making it easy to track progress, verify settings, and troubleshoot issues.

### HDR10+ and Dolby Vision Profile 5 Limitation Notice

Currently, this tool can only preserve (transfer) HDR10+ metadata when using the **Passthrough Mode**.

The **Encode Mode** uses hardware encoders (NVENC/AMF) which **will discard** all HDR10+ metadata, at this time.

**Recommendation:**
- **To preserve HDR10+:** You MUST select **Passthrough Mode** (in interactive mode) or set `"video_policy": "passthrough"` (in your profile.json).
- **To also ensure Dolby Vision compatibility:** Select **Passthrough Mode** and answer **"Yes"** to the DV conversion question (or set `"passthrough_convert_dv_to_p8": true`). This is the *only* way to preserve HDR10+ **and** convert DV P7 to P8 at the same time.

- **Dolby Vision Profile 5 :** Processing is INCOMPATIBLE & BLOCKED. This profile's IPT-PQ-C2 color matrix cannot be correctly processed by the encoding (NVENC/AMF) or conversion (`dovi_tool`) tools used in this script. Attempting either would result in corrupted (purple/green) video.
    - The script detects Profile 5 and **automatically forces Pure Passthrough mode** (1:1 copy) if you select Encode or Hybrid Passthrough, preventing video corruption during processing.
    - **IMPORTANT:** The resulting output file will retain the original Profile 5 stream and **will likely appear purple/green on most players** due to lack of IPT-PQ-C2 support. Correct playback requires specific compatible hardware (e.g., Nvidia Shield).

---
## Prerequisites

Before running the script, you must have the following software packages installed. The script will verify the presence of the specific command-line tools they provide.

- **FFmpeg:** Provides the core `ffmpeg` (for encoding) and `ffprobe` (for analysis) commands. Must be compiled with support for your hardware encoder (`hevc_nvenc` for Nvidia, `hevc_amf` for AMD).
- **MKVToolNix:** Provides the `mkvmerge` (for muxing) and `mkvextract` (for demuxing) commands.
- **dovi_tool:** The essential stand-alone tool for handling Dolby Vision metadata.

### Optional (but recommended)

By default, the script's autofilename logic will remove non-ASCII characters (like ś, π, ó, etc.). If you want to transliterate them (e.g., ś -> s), you must install the Unidecode library (see the next chapter for details).

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

wget https://github.com/quietvoid/dovi_tool/releases/download/2.1.0/dovi_tool-2.1.0-x86_64-unknown-linux-musl.tar.gz
tar -xvf dovi_tool-2.1.0-x86_64-unknown-linux-musl.tar.gz
sudo mv dovi_tool /usr/local/bin/
rm dovi_tool-2.1.0-x86_64-unknown-linux-musl.tar.gz
```
The specific package versions are pinned to ensure script compatibility. These versions were tested with the mkv_factory logic.

### Step 4: Install Unidecode (optional)

```bash
sudo apt install python3-unidecode
```

Your environment is now ready. Enter your mounted media folder and place the `mkv_factory.py` script inside to begin working.


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
  - **Passthrough:** Copy video stream 1:1, preserving HDR10+.
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

### Video Policy

This is the most important setting, defining the high-level behavior of the script.
```json
{
  "video_policy": "passthrough",
  "passthrough_convert_dv_to_p8": true
}
```
- **video_policy** (String): Defines the main video processing method.
  - **encode** (default): Re-encodes the video stream using the nvenc or amf settings. This is a "lossy" process. WARNING: This mode will lose all HDR10+ metadata.
  - **passthrough**: Copies the original video stream without re-encoding. This is a "lossless" process. This mode preserves HDR10+ metadata. The nvenc and amf sections are ignored.

- **passthrough_convert_dv_to_p8** (Boolean): Optional. Only used when video_policy is "passthrough". Defaults to false.
  - **false** (Pure Passthrough): Copies the video stream 1:1. The original Dolby Vision profile (e.g., P5 or P7) is preserved. This is recommended only for advanced players that can handle all DV profiles (e.g., Nvidia Shield), or if your player does not support DV at all and you just want to keep the HDR10+.
  - **true** (Hybrid Passthrough): Copies the video stream while using dovi_tool to convert Dolby Vision profile P7 to a compatible Profile 8 (e.g., P8.1, P8.2). This is the recommended passthrough mode as it preserves HDR10+ and creates a compatible DV file. Note that converting Profile 5 is currently not possible.

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
  - "all" — processes all detected languages using the defined filters.
  - ["eng", "pol"] — processes only tracks matching those language codes.
- **preferred_codecs** (List) — Used only with "best_per_language". List of codecs ordered from most to least preferred. Note that if the mkv does not contain any of the "preferred" codecs, the script will simply choose another one.
  - Example: ["truehd", "dts-hd ma", "eac3", "dts", "ac3"] - processes all tracks matching the defined filters.
- **exclude_titles_containing** (List) — Used only with "best_per_language". List of case-insensitive phrases that disqualify a track.
  - Example: ["commentary", "director", "description"]
- **default_track_language** (String) — Language code (three letters, e.g., "eng" or "pol") to set as default. If multiple matches are found, the first one is marked as default. Can also be set to "none" for subtitles (if set to "none" ensure the default_mode flag is set to "none as well!).
- **default_mode** (String) (Subtitles only) — Controls default subtitle behavior. 
  - "first" — Sets the first subtitle track as default if default_track_language isn’t found (only if subtitles exist). 
  - "none" — Recommended if you don’t want any default subtitles. Ensures no default track is set.

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
- transcode video stream with high quality settings (losing HDR10+),
- include all of the found audio and subtitles,
- set the default audio to English,
- set the default subtitles to "none",
- perform cleanup of temp video file after encoding, and rest of the temp files on success,
- log all steps to mkv_factory.log file.
```json
{
  "video_policy": "encode",
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
- transcode video stream with high quality settings (losing HDR10+),
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
- transcode the video using high-quality encoder settings (losing HDR10+),
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

These profiles **skip video encoding**, preserving the original video quality and **preserving HDR10+ metadata**. The nvenc and amf sections are omitted as they are not used.

`Example 4a: Pure Passthrough`
(for DV5-DV8 compatible players, e.g., Nvidia Shield, or for when you don't care about DV and just want to keep HDR10+)
This profile will:
- copy (remux) the video stream 1:1, preserving original quality, HDR10+, and the original DV Profile (P5/P7/P8),
- select the best audio track for English and Polish (excluding commentaries),
- select the best subtitle track for Polish (excluding forced/sdh),
- set English as the default audio language, and Polish as the default subs.
- clean up temp files on success,
- log all steps to mkv_factory.log file.
```json
{
  "video_policy": "passthrough",
  "passthrough_convert_dv_to_p8": false,
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
  "passthrough_convert_dv_to_p8": true,
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

### Step 3: Configure the PATH Environment Variable

1. Press the Windows key and type "environment variables". Select "Edit the system environment variables".
2. In the new window, click the "Environment Variables..." button.
3. In the bottom section ("System variables"), find and select the Path variable, then click "Edit...".
4. Click "New" and add:
   ```
   C:\Tools\ffmpeg\bin
   C:\Program Files\MKVToolNix
   C:\Tools\dovi_tool
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

Open PowerShell (press Windows key > type PowerShell > press Enter) or open a Command Prompt.
Make sure you open a new window after editing the PATH variable.

```powershell
ffmpeg -version
mkvmerge -V
dovi_tool --version
pip show unidecode (optional)
pip show colorama (optional)
```

If all commands succeed, your environment is ready.
`Note`: I did not test this tool on a Windows PC. If you find it working - let me know!

## Acknowledgements

This project relies on the outstanding open-source work behind FFmpeg, MKVToolNix, and dovi_tool. All credit goes to their respective developers.

## Future Plans

This may, or may not happen :)
- `hevc_qsv` support for integrated GPU's
- Batch processing results file (detailed summary of processed files)

## Support / Buy Me a Coffee ☕️

If you enjoy using **MKV Factory** and want to support its development, you can buy me a coffee:

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/yellow_img.png)](https://buymeacoffee.com/trutru21)

Every coffee helps keep this project alive and improves future updates. Thank you for your support!
