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
2. Ensure you have the `bin` folder populated with `yt-dlp.exe`, `ffmpeg.exe`, AND `ffprobe.exe`. (These are excluded from the repo to save space).
3. Restart NVDA to load the plugin features.

### Building
Run the build script to create an `.nvda-addon` package:
```bash
python build_addon.py
```

## Credits
- Core downloading power provided by [yt-dlp](https://github.com/yt-dlp/yt-dlp).
- powered by [FFmpeg](https://ffmpeg.org).

## License
MIT License.
