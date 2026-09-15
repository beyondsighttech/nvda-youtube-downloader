# NVDA YouTube Downloader

An accessible NVDA add-on that allows users to download videos and audio from YouTube directly within the NVDA screen reader environment.

## Features
- **Accessible UI:** specialized dialogs designed for screen reader users.
- **Format Support:** Download as **Audio** (MP3, WAV, FLAC, M4A, OGG) or **Video** (MP4).
- **Quality Options:** Select from various bitrates (320kbps, 128kbps) or resolutions (1080p, 720p).
- **Playlist Support:** Detects playlists and allows batch downloading of selected videos.
- **Trimming:** Download specific sections of a video by specifying start and end times.
- **Auto-Updates:** Automatically keeps the underlying `yt-dlp` downloader up to date for reliability.
- **SponsorBlock:** Option to automatically skip/remove non-music sections like sponsors and intros.
- **Metadata Embedding:** Automatically adds artist, title, and chapter information to your files.
- **Subtitles:** Option to automatically download and embed English subtitles.
- **Audio Normalization:** Normalize audio loudness to a consistent, professional level (perfect for playlists).

## Installation
1. Go to the [Releases](../../releases) page.
2. Download the latest `youtubeDownloader-x.y.nvda-addon` file.
3. Open the file to verify and install it in NVDA.
4. Restart NVDA when prompted.

The required `yt-dlp` and `FFmpeg` binaries are **downloaded automatically** the
first time you start a download, so no manual setup is needed.

## Usage
1. Copy a YouTube URL to your clipboard.
2. Press `NVDA+Shift+Y` (default shortcut) to open the Downloader Dialog.
3. The URL field should automatically be populated.
4. Choose your desired Format (Audio/Video) and Quality.
5. (Optional) Enter Start/End times to download a clip.
6. Press **Download**.

## Development
To run this add-on from source for development:

1. Clone this repository into your NVDA user configuration's `addons` directory (e.g., `%APPDATA%\nvda\addons`).
2. Restart NVDA to load the plugin features. (`yt-dlp.exe`, `ffmpeg.exe`, and
   `ffprobe.exe` are fetched automatically on first use into the add-on's `bin`
   folder; you do not need to add them manually.)

### Building
Run the build script to create an `.nvda-addon` package (in `dist/`):
```bash
python build_addon.py
```

Useful flags:
- `--check` — validate `manifest.ini` and packaging inputs without building (used by CI).
- `--print-version` — print the version from `manifest.ini` (used by CI).

The build is reproducible: the same source always produces a byte-identical
package, and the script prints its SHA-256 so users can verify downloads.

### Continuous Integration
- **CI** (`.github/workflows/ci.yml`): syntax-checks the sources, validates the
  manifest and builds the package on every push to `main` and every pull request.
- **Release** (`.github/workflows/release.yml`): when you push a tag like
  `v1.4.0`, it verifies the tag matches `manifest.ini`, builds the package,
  computes a SHA-256 checksum and publishes a GitHub Release with the
  `.nvda-addon` attached — no binaries ever enter the repository.

## Credits
- Core downloading power provided by [yt-dlp](https://github.com/yt-dlp/yt-dlp).
- powered by [FFmpeg](https://ffmpeg.org).

## License
MIT License.
