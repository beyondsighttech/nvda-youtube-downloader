# NVDA YouTube Downloader — Code Review & Update (v1.3.0)

A full review of the add-on against the current **NVDA Add-on Developer Guide**
(tested against the 2026.2 guide), plus bug fixes and modernisation. Bumped
`1.2.1` → `1.3.0`.

---

## 1. Functional bugs fixed

These were breaking real features in normal use.

### 1.1 Browser address-bar detection was completely broken 🔴
**File:** `globalPlugins/youtubeDownloader/__init__.py` (`get_video_url`)

The UIA strategy that auto-grabs the YouTube URL from the focused browser used
`controlTypes.Role.EDIT`. That role **does not exist** in NVDA — the correct
constant is `controlTypes.Role.EDITABLETEXT` (the old `ROLE_*` aliases were
removed in NVDA 2022.1). Accessing `controlTypes.Role.EDIT` raised
`AttributeError`, which was silently swallowed by a bare `except`, so the whole
"URL is filled in automatically" feature was dead and it always fell back to
the clipboard.

**Fix:** `controlTypes.Role.EDIT` → `controlTypes.Role.EDITABLETEXT`, plus the
helper was rewritten with correct indentation and clearer logic (it had also
been incorrectly nested, and the clipboard fallback never guaranteed
`TheClipboard.Close()`).

### 1.2 "Check for Updates" button always said "Plugin instance not found." 🔴
**File:** `__init__.py` (`YouTubeDownloaderSettingsPanel._run_manual_update`)

It iterated `globalPluginHandler.runningPlugins`, but that is a **dict keyed by
file path** — iterating it yields *strings*, never plugin instances. So
`isinstance(p, GlobalPlugin)` was always `False`.

**Fix:** The `GlobalPlugin` now stores itself in a class-level `_instance`
attribute (set in `__init__`, cleared in `terminate`); the settings panel reads
`GlobalPlugin._instance`.

### 1.3 Playlist/batch downloads ignored the chosen format 🔴
**File:** `__init__.py` (`start_batch_download`)

It called `start_download(...)` **without forwarding `audio_format`**, so every
playlist download silently used the `mp3` default — picking M4A/WAV/FLAC/OGG had
no effect for batch downloads.

**Fix:** `start_batch_download` now forwards `audio_format=audio_format`. (The
author left a long TODO comment in `dialogs.py` admitting this was forgotten; it
is now removed.)

### 1.4 Duplicate-download detection was broken 🟠
**File:** `__init__.py` (`is_url_downloading`)

Status strings are stored as the full text (e.g. `"My Song - Completed"`), but
this method compared with exact equality (`status != "Completed"`). Since the
stored value is never exactly `"Completed"`, a finished URL was never recognised
as "not downloading" — so re-downloading a completed URL was wrongly blocked.

**Fix:** switched to substring matching, consistent with how `save_state`,
`load_state`, `terminate`, and the UI read the same field.

### 1.5 Logging never reached the NVDA log 🟠
**File:** `__init__.py`

It used the stdlib root logger (`logging.info/error`). NVDA routes diagnostics
through `logHandler.log`, so all of the add-on's `logging.*` calls were
effectively lost (no handlers on the root logger).

**Fix:** switched to `from logHandler import log` and `log.info/log.error` so
debug output actually appears in the NVDA log.

### 1.6 Retried download wouldn't report a second failure 🟡
**File:** `__init__.py` (`retry_download`)

`stop_download` sets a `manual_stop` flag so the download thread doesn't overwrite
a "Stopped" status with "Error". `retry_download` never cleared that flag, so if a
retried download failed again, the error handler still treated it as
manually-stopped and silently skipped the error status.

**Fix:** `retry_download` now resets `data['manual_stop'] = False`.

---

## 2. Modernisation per the NVDA Add-on Developer Guide

### 2.1 Gesture binding via the `@script` decorator
The guide's current examples bind gestures with
`from scriptHandler import script` + `@script(gesture=..., description=...)`,
not the legacy `__gestures` dict. The `__gestures` dict was removed and
`script_openDownloader` now uses the decorator, including a **translatable
description** (so it shows up properly in *Input Gestures* and input help). A
translators comment was added.

### 2.2 Removed dead / unreachable code
- `script_openSettings` — defined but never bound to a gesture and never called
  (it also relied on a private GUI API). Removed.
- `download_video()` in `downloader.py` — superseded by
  `download_video_with_process()` and never called; it also had a latent bug
  (calling the progress hook with the wrong number of arguments). Removed.
- Unused import `from NVDAObjects.IAccessible import IAccessible`. Removed.
- Duplicate keys in the download `params` dict (`playlist_title` and
  `known_title` each appeared twice). De-duplicated.

### 2.3 Manifest brought up to date
```ini
version = 1.3.0                 # was 1.2.1
minimumNVDAVersion = 2022.1     # was 2019.3 (code now requires 2021.2+ APIs)
lastTestedNVDAVersion = 2026.1  # was 2025.3.2
```
The previous `minimumNVDAVersion = 2019.3` was inaccurate: the code uses
`controlTypes.Role.EDITABLETEXT` (2021.2+) and the `@script` decorator, which
were never available in 2019.3. 2022.1 is the clean modern floor (the release
that completed the `controlTypes` refactor).

### 2.4 Replaced bare `except:` with `except Exception:`
All bare `except:` clauses (there were ~19 across the three modules) now catch
`Exception`, so they no longer swallow `KeyboardInterrupt` / `SystemExit`.

### 2.5 Cross-platform console-hiding helper
`subprocess.STARTUPINFO()` / `STARTF_USESHOWWINDOW` are Windows-only. Added
`downloader._no_console_startupinfo()` (returns the STARTUPINFO on Windows,
`None` elsewhere) and use it everywhere a child process is spawned. Keeps the
"local testing" mock path honest.

---

## 3. New feature: automatic tool setup (zero-config install)

Previously the add-on shipped with `YT_DLP_URL` / `FFMPEG_ZIP_URL` constants but
**no code that ever used them** — `check_dependencies()` simply raised
"not found" unless the user had manually dropped `yt-dlp.exe`, `ffmpeg.exe` and
`ffprobe.exe` into the `bin` folder. A fresh install could not work.

`check_dependencies()` now **downloads what's missing on first use**:

- `yt-dlp.exe` from the official latest GitHub release.
- `ffmpeg.exe` + `ffprobe.exe` extracted from the gyan.dev
  `ffmpeg-release-essentials.zip` (the source ffmpeg.org links to; verified
  current as of 2026-08-20).

Implementation notes (`downloader.py`):
- A module-level `threading.Lock` (`_BIN_LOCK`) serialises downloads so several
  concurrent download threads don't each fetch ~100 MB.
- Downloads go to a `.tmp` file and are moved into place with `os.replace`
  (atomic), so a killed download can't leave a half-written executable.
- The FFmpeg archive is deleted after extraction so it never bloats the bin
  folder.
- Progress is reported both via the `progress_hook` and `ui.message`, so the
  user hears "Downloading FFmpeg, this may take a moment…" on first use.
- On any failure a clear exception is raised (which the download thread already
  surfaces as an error item).

`build_addon.py` was updated so the **distributed package never bundles the
binaries** (excludes the `bin/` dir and any `.exe/.dll/.zip`) — they're fetched
at runtime, keeping the add-on ~24 KB.

---

## 4. Reliability / yt-dlp correctness

- **Removed a 4-year-old hardcoded user-agent** (`Chrome/91` from 2021) that was
  sent on every download, title fetch and playlist lookup. Forcing an outdated
  UA risks triggering YouTube bot detection. yt-dlp now uses its own
  regularly-updated default UA (and it self-updates on every NVDA start).
- **Removed the hardcoded `--extractor-args youtube:player_client=default`
  override** for the same reason — it pins behaviour that yt-dlp's own defaults
  handle better version-to-version.
- Kept `--referer https://www.youtube.com/` (harmless, occasionally helpful).
- `get_playlist_info` no longer forces the old UA / `--no-geo-bypass`.

---

## 5. Build / packaging
- `build_addon.py` excludes `bin/`, `__pycache__/`, and `.pyc/.exe/.dll/.zip`.
- Verified: `python build_addon.py` produces a 24 KB `youtubeDownloader-1.3.0.nvda-addon`
  containing only the source + docs.

---

## 6. Documentation
- `doc/en/readme.html` and `doc/hi/readme.html`: the "Format Selection" line
  now lists all supported formats (MP3/M4A/WAV/FLAC/OGG + MP4) instead of just
  MP3/MP4; the Configuration section now documents Subtitles, Audio
  Normalisation and the Check-for-Updates button; a note explains the automatic
  tool download.
- `README.md`: install/development notes no longer tell users to populate
  `bin/` manually.

---

## 7. Known behaviour / future work (not changed, by design)
- **Startup update check blocks the queue briefly.** On every NVDA start a
  background thread runs `yt-dlp -U` (up to 120 s) and `_process_queue` skips
  while `is_updating` is set, because you cannot overwrite a running `yt-dlp.exe`
  on Windows. This is intentional; if a download is queued it starts as soon as
  the check finishes. A "don't check more than once per N hours" policy would be
  a nice future enhancement.
- **`self.downloads` is accessed from multiple threads** without a lock. Python's
  GIL keeps individual dict operations safe, and all UI mutation goes through
  `wx.CallAfter`, so it works in practice, but a proper lock would be cleaner.
- **Translatability:** many user-facing strings in `dialogs.py` (button labels,
  message boxes, list headers) are not wrapped in `_()`. They should be for
  proper localisation (a prerequisite for the NV Access add-on store).
- The FFmpeg source is a single host (gyan.dev). It is the canonical, ffmpeg.org
 -linked source and the add-on fails loudly if it's unreachable; a GitHub-mirror
  fallback could be added later.
