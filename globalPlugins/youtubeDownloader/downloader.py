import os
import subprocess
import threading
import urllib.request
import zipfile
import shutil

# Try to import NVDA's ui module for speech
try:
	import ui
	from logHandler import log
except ImportError:
	# Mock for local testing
	class UI:
		def message(self, msg):
			print(f"NVDA SPEECH: {msg}")
	ui = UI()
	import logging
	log = logging.getLogger("youtubeDownloader")

# Translations: uses NVDA's translation system when running inside NVDA.
try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	pass

# Constants
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(ADDON_DIR, "bin")
YT_DLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
# Lightweight static FFmpeg builds. Tried in order: the gyan.dev essentials
# build (the one ffmpeg.org links to) first, then the BtbN GitHub mirror as a
# fallback if the primary host is unreachable.
FFMPEG_SOURCES = [
	"https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
	"https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
]

def ensure_bin_dir():
	if not os.path.exists(BIN_DIR):
		os.makedirs(BIN_DIR)


def _no_console_startupinfo():
	"""Returns a STARTUPINFO that hides the child console window on Windows,
	or ``None`` on other platforms (used for local testing only)."""
	if os.name == "nt":
		startupinfo = subprocess.STARTUPINFO()
		startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		return startupinfo
	return None

def sanitize_filename(name):
	"""
	Sanitizes a string to be safe for use as a filename/directory name.
	Removes or replaces characters that are illegal in Windows filenames.
	"""
	if not name: return "Unknown"
	
	# Invalid chars in Windows: < > : " / \ | ? *
	# We replace them with safe alternatives or remove them
	invalid_chars = '<>:"/\\|?*'
	for char in invalid_chars:
		name = name.replace(char, "_")
		
	# Remove leading/trailing spaces and dots
	name = name.strip(" .")
	
	# Truncate if too long (max 255 usually, but let's be safe with 50 for folders)
	if len(name) > 50:
		name = name[:50]
		
	return name or "Unknown"

def get_yt_dlp_path():
	return os.path.join(BIN_DIR, "yt-dlp.exe")

def get_ffmpeg_path():
	# The ffmpeg.exe will be inside the bin folder after extraction
	return os.path.join(BIN_DIR, "ffmpeg.exe")

def get_ffprobe_path():
	return os.path.join(BIN_DIR, "ffprobe.exe")

def check_dependencies(progress_hook=None):
	"""Ensures all required binaries (yt-dlp, ffmpeg, ffprobe) are present,
	downloading them automatically on first use, then returns their paths."""
	ensure_bin_dir()
	yt_dlp_path = get_yt_dlp_path()
	ffmpeg_path = get_ffmpeg_path()
	ffprobe_path = get_ffprobe_path()

	# Download anything that is missing (serialised to avoid races between
	# concurrent download threads).
	with _BIN_LOCK:
		if not os.path.exists(yt_dlp_path):
			log.info("yt-dlp not found, downloading...")
			if progress_hook:
				progress_hook(_("Downloading yt-dlp..."))
			ui.message(_("Downloading yt-dlp, please wait..."))
			_download_file(YT_DLP_URL, yt_dlp_path)

		if not os.path.exists(ffmpeg_path) or not os.path.exists(ffprobe_path):
			log.info("ffmpeg/ffprobe not found, downloading...")
			if progress_hook:
				progress_hook(_("Downloading FFmpeg..."))
			ui.message(_("Downloading FFmpeg, this may take a moment..."))
			_download_and_extract_ffmpeg_from_any_source()

	# Final verification
	if not os.path.exists(yt_dlp_path):
		raise Exception(_("yt-dlp could not be located or downloaded. Please check your internet connection."))
	if not os.path.exists(ffmpeg_path):
		raise Exception(_("FFmpeg could not be located or downloaded. It is required for conversion and merging."))
	if not os.path.exists(ffprobe_path):
		raise Exception(_("ffprobe could not be located or downloaded. It is required for metadata and format merging."))

	return yt_dlp_path, ffmpeg_path, ffprobe_path


# Serialises binary downloads so concurrent threads do not download twice.
_BIN_LOCK = threading.Lock()


def _download_file(url, dest_path):
	"""Downloads a single file from ``url`` to ``dest_path`` with a temp name."""
	tmp_path = dest_path + ".tmp"
	try:
		with urllib.request.urlopen(url, timeout=120) as response, open(tmp_path, "wb") as out_file:
			shutil.copyfileobj(response, out_file)
		# Move into place atomically once the download is complete.
		os.replace(tmp_path, dest_path)
		log.info(f"Downloaded {url} -> {dest_path}")
	except Exception:
		# Clean up a partial download so it is retried cleanly next time.
		if os.path.exists(tmp_path):
			try:
				os.remove(tmp_path)
			except OSError:
				pass
		raise


def _download_and_extract_ffmpeg(url, bin_dir):
	"""Downloads an FFmpeg zip archive from ``url`` and extracts ffmpeg.exe and
	ffprobe.exe into ``bin_dir``. Raises on any failure."""
	zip_tmp = os.path.join(bin_dir, "ffmpeg_download.tmp.zip")
	try:
		log.info(f"Downloading FFmpeg from {url}")
		_download_file(url, zip_tmp)

		extracted = set()
		with zipfile.ZipFile(zip_tmp) as zf:
			for member in zf.namelist():
				base = member.lower().split("/")[-1]
				if base in ("ffmpeg.exe", "ffprobe.exe") and base not in extracted:
					target = os.path.join(bin_dir, base)
					with zf.open(member) as src, open(target, "wb") as dst:
						shutil.copyfileobj(src, dst)
					extracted.add(base)
					log.info(f"Extracted {base}")

		if "ffmpeg.exe" not in extracted or "ffprobe.exe" not in extracted:
			raise Exception("FFmpeg archive did not contain the expected executables.")
	finally:
		# Always remove the downloaded archive to keep the bin folder small.
		if os.path.exists(zip_tmp):
			try:
				os.remove(zip_tmp)
			except OSError:
				pass


def _download_and_extract_ffmpeg_from_any_source():
	"""Ensures ffmpeg.exe/ffprobe.exe exist, trying every mirror in
	FFMPEG_SOURCES until one succeeds."""
	ensure_bin_dir()
	bin_dir = BIN_DIR
	last_error = None
	for url in FFMPEG_SOURCES:
		try:
			_download_and_extract_ffmpeg(url, bin_dir)
			return
		except Exception as e:
			log.error(f"FFmpeg download from {url} failed: {e}")
			last_error = e
	raise Exception(
		_("Could not download FFmpeg from any known source. Please check your internet connection.")
	) from last_error

def cleanup_partial_files(output_path, title, filename=None):
	"""
	Cleans up partial/temp files for a given video title or specific filename.
	"""
	if not output_path: return
	
	# If we have a specific filename, try to clean that up first
	if filename:
		try:
			# Filename might be absolute path
			if os.path.isabs(filename):
				base_name = os.path.basename(filename)
				dir_name = os.path.dirname(filename)
				if dir_name and os.path.exists(dir_name):
					output_path = dir_name
				filename = base_name
			
			# Try to remove the exact file and related temp files
			# Common temp patterns: filename.part, filename.ytdl
			candidates = [
				filename,
				filename + ".part",
				filename + ".ytdl",
				filename + ".temp"
			]
			
			for cand in candidates:
				full_path = os.path.join(output_path, cand)
				if os.path.exists(full_path):
					try:
						os.remove(full_path)
					except Exception:
						pass
		except Exception:
			pass
			
	if not title: return

	# Sanitize title for filename matching (basic)
	# yt-dlp sanitization is complex, but we can try to match loosely
	safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c in " ._-"]).strip()
	
	try:
		for file in os.listdir(output_path):
			# Check if file starts with the title (or close to it) and has temp extension
			if file.startswith(safe_title) or (title in file):
				if file.endswith(".part") or file.endswith(".ytdl") or file.endswith(".f137.webm") or file.endswith(".f140.m4a") or file.endswith(".temp"):
					try:
						os.remove(os.path.join(output_path, file))
					except Exception:
						pass
				# Also check for .webm / .m4a that might be left over from merge
				# Be careful not to delete finished files if we are not sure
				# But if this is called on STOP, we assume we want to kill everything for this title
				elif file.endswith(".webm") or file.endswith(".m4a"):
					# Only delete if it looks like a stream (often has .fXXX format)
					if ".f" in file: 
						try:
							os.remove(os.path.join(output_path, file))
						except Exception:
							pass
	except Exception:
		pass

def get_playlist_info(url):
	"""
	Fetches playlist metadata (title and entries) without downloading.
	Returns a dict: {'title': str, 'entries': [{'id': str, 'title': str}, ...]}
	"""
	yt_dlp_path, _, _ = check_dependencies()
	
	# Command to dump single json
	cmd = [
		yt_dlp_path,
		"--flat-playlist",
		"--dump-single-json",
		"--no-warnings",
		"--no-mark-watched", # Save API call
		url
	]
	
	startupinfo = _no_console_startupinfo()

	try:
		result = subprocess.run(
			cmd,
			capture_output=True,
			text=True,
			startupinfo=startupinfo,
			encoding='utf-8',
			errors='replace',
			check=True
		)
		
		import json
		data = json.loads(result.stdout)
		
		# Extract relevant info
		info = {
			'title': data.get('title', 'Unknown Playlist'),
			'entries': []
		}
		
		for entry in data.get('entries', []):
			info['entries'].append({
				'id': entry.get('id'),
				'title': entry.get('title', 'Unknown Video')
			})
			
		return info
	except Exception as e:
		raise Exception(f"Failed to fetch playlist info: {str(e)}")

def normalise_quality_value(quality_str):
	"""Normalises a quality selection to a machine value: "best", or a digit
	string (kbps for audio, vertical resolution for video). Accepts both the
	current machine values ("320", "1080") and legacy 1.3.0 display labels
	("320 kbps", "1080p", "Best (Default)", "Lossless (Default)")."""
	if not quality_str:
		return "best"
	value = str(quality_str).strip().lower()
	if "kbps" in value:
		value = value.split()[0]
	if value.endswith("p"):
		value = value[:-1]
	if value.isdigit():
		return value
	return "best"


def download_video_with_process(url, output_path, is_audio, quality_str, start_time, end_time, progress_hook, playlist_mode=None, playlist_items=None, playlist_title=None, remove_sponsors=False, embed_metadata=True, download_subs=False, normalize_audio=False, audio_format="mp3"):
	"""
	Builds and starts a yt-dlp download as a subprocess, returning the Popen
	object so the caller can stream progress and stop it. Supports trimming,
	quality selection, playlists with item selection and folder creation.
	"""
	yt_dlp_path, ffmpeg_path, ffprobe_path = check_dependencies(progress_hook)
	
	if progress_hook:
		progress_hook(_("Starting download..."))
		ui.message(_("Starting download..."))
		
	# Determine final output path template
	# Truncate filename to 100 chars to avoid MAX_PATH issues
	out_tmpl = "%(title).100s.%(ext)s"
	if playlist_title:
		# Create subfolder for playlist
		safe_title = sanitize_filename(playlist_title)
		output_path = os.path.join(output_path, safe_title)
	
	if not os.path.exists(output_path):
		try:
			os.makedirs(output_path)
		except Exception:
			pass # Should handle permission errors gracefully

	# Temp path for intermediate files
	temp_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "nvda_yt_downloader")
	if not os.path.exists(temp_path):
		try:
			os.makedirs(temp_path)
		except Exception:
			pass
	
	# Build command.
	# Note: a hardcoded user-agent / player_client override is intentionally
	# omitted. yt-dlp ships sensible, regularly updated defaults, and forcing an
	# old Chrome 91 user-agent (as previous versions did) risks triggering
	# YouTube's bot detection.
	cmd = [
		yt_dlp_path,
		"--ffmpeg-location", os.path.dirname(ffmpeg_path),
		"--output", out_tmpl, # Output template (relative to paths)
		"--paths", f"home:{output_path}", # Final destination
		"--paths", f"temp:{temp_path}", # Temp destination
		"--newline", # Ensure progress is printed on new lines for parsing
		"--referer", "https://www.youtube.com/",
	]
	
	# Playlist mode
	if playlist_mode is True:
		cmd.append("--yes-playlist")
		if playlist_items:
			cmd.extend(["--playlist-items", playlist_items])
	elif playlist_mode is False:
		cmd.append("--no-playlist")
	
	# Format selection. Quality values are machine-readable ("best" or digits);
	# legacy display labels are normalised for users upgrading from 1.3.0.
	quality_value = normalise_quality_value(quality_str)
	if is_audio:
		cmd.extend(["-x", "--audio-format", audio_format])
		if quality_value != "best":
			cmd.extend(["--audio-quality", f"{quality_value}K"])
		else:
			cmd.extend(["--audio-quality", "0"])
	else:
		cmd.extend(["--format", "bestvideo+bestaudio/best"])
		cmd.extend(["--merge-output-format", "mp4"])
		if quality_value != "best":
			cmd.extend(["-S", f"res:{quality_value}"])

	# Trimming (Only valid for single video or if applied to all, usually disabled for playlist)
	if start_time and end_time and not playlist_mode:
		cmd.extend(["--download-sections", f"*{start_time}-{end_time}"])

	# SponsorBlock
	if remove_sponsors:
		cmd.extend(["--sponsorblock-remove", "default"])

	# Metadata
	if embed_metadata:
		cmd.append("--add-metadata")

	# Subtitles
	if download_subs:
		cmd.extend(["--write-subs", "--embed-subs", "--sub-langs", "en.*,auto"])

	# Audio Normalization
	if normalize_audio and is_audio:
		cmd.extend(["--postprocessor-args", "ffmpeg:-af loudnorm=I=-16:TP=-1.5:LRA=11"])

	cmd.append(url)
	
	# Run command
	startupinfo = _no_console_startupinfo()
	
	process = subprocess.Popen(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		startupinfo=startupinfo,
		encoding='utf-8',
		errors='replace'
	)
	
	return process
