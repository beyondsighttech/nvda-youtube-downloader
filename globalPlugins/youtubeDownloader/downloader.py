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

# Constants
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(ADDON_DIR, "bin")
YT_DLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
# Using a lightweight static build of ffmpeg (essentials build)
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

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
				progress_hook("Downloading yt-dlp...")
			ui.message("Downloading yt-dlp, please wait...")
			_download_file(YT_DLP_URL, yt_dlp_path)

		if not os.path.exists(ffmpeg_path) or not os.path.exists(ffprobe_path):
			log.info("ffmpeg/ffprobe not found, downloading...")
			if progress_hook:
				progress_hook("Downloading FFmpeg...")
			ui.message("Downloading FFmpeg, this may take a moment...")
			_download_and_extract_ffmpeg()

	# Final verification
	if not os.path.exists(yt_dlp_path):
		raise Exception("yt-dlp.exe could not be located or downloaded. Please check your internet connection.")
	if not os.path.exists(ffmpeg_path):
		raise Exception("ffmpeg.exe could not be located or downloaded. It is required for conversion and merging.")
	if not os.path.exists(ffprobe_path):
		raise Exception("ffprobe.exe could not be located or downloaded. It is required for metadata and format merging.")

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


def _download_and_extract_ffmpeg():
	"""Downloads the FFmpeg essentials build and extracts ffmpeg.exe/ffprobe.exe
	into the bin directory."""
	ensure_bin_dir()
	bin_dir = BIN_DIR
	zip_tmp = os.path.join(bin_dir, "ffmpeg_download.tmp.zip")
	try:
		log.info(f"Downloading FFmpeg from {FFMPEG_ZIP_URL}")
		_download_file(FFMPEG_ZIP_URL, zip_tmp)

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

def download_video_with_process(url, output_path, is_audio, quality_str, start_time, end_time, progress_hook, playlist_mode=None, playlist_items=None, playlist_title=None, remove_sponsors=False, embed_metadata=True, download_subs=False, normalize_audio=False, audio_format="mp3"):
	"""
	Builds and starts a yt-dlp download as a subprocess, returning the Popen
	object so the caller can stream progress and stop it. Supports trimming,
	quality selection, playlists with item selection and folder creation.
	"""
	yt_dlp_path, ffmpeg_path, ffprobe_path = check_dependencies(progress_hook)
	
	if progress_hook:
		progress_hook("Starting download...")
		ui.message("Starting download...")
		
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
	
	# Format selection
	if is_audio:
		cmd.extend(["-x", "--audio-format", audio_format])
		if quality_str and "kbps" in quality_str:
			bitrate = quality_str.split(" ")[0]
			cmd.extend(["--audio-quality", f"{bitrate}K"])
		else:
			cmd.extend(["--audio-quality", "0"])
	else:
		cmd.extend(["--format", "bestvideo+bestaudio/best"])
		cmd.extend(["--merge-output-format", "mp4"])
		if quality_str and "p" in quality_str:
			res = quality_str.replace("p", "")
			cmd.extend(["-S", f"res:{res}"])

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
