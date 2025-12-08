import os
import subprocess
import urllib.request
import sys
import time
import zipfile
import shutil

# Try to import NVDA's ui module for speech
try:
	import ui
except ImportError:
	# Mock for local testing
	class UI:
		def message(self, msg):
			print(f"NVDA SPEECH: {msg}")
	ui = UI()

# Constants
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(ADDON_DIR, "bin")
YT_DLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
# Using a lightweight static build of ffmpeg (essentials build)
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

def ensure_bin_dir():
	if not os.path.exists(BIN_DIR):
		os.makedirs(BIN_DIR)

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

def check_dependencies(progress_hook=None):
	ensure_bin_dir()
	yt_dlp_path = get_yt_dlp_path()
	ffmpeg_path = get_ffmpeg_path()
	
	# Check yt-dlp
	if not os.path.exists(yt_dlp_path):
		raise Exception("yt-dlp.exe not found in bin directory. Please ensure the addon was installed correctly.")
		
	# Check ffmpeg
	if not os.path.exists(ffmpeg_path):
		raise Exception("ffmpeg.exe not found in bin directory. Please ensure the addon was installed correctly.")
			
	return yt_dlp_path, ffmpeg_path

def download_video(url, output_path, is_audio, quality_str, start_time, end_time, progress_hook, playlist_mode=None):
	"""
	Downloads video/audio using yt-dlp with trimming and quality options.
	"""
	yt_dlp_path, ffmpeg_path = check_dependencies(progress_hook)
	
	if progress_hook:
		progress_hook("Starting download...")
		ui.message("Starting download...")
		
	# Build command
	cmd = [
		yt_dlp_path,
		"--ffmpeg-location", os.path.dirname(ffmpeg_path),
		"--output", os.path.join(output_path, "%(title)s.%(ext)s"),
		"--no-progress", # We parse output manually
		"--extractor-args", "youtube:player_client=default", # Fix for JS warning
		"--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
		"--referer", "https://www.youtube.com/",
	]
	
	# Playlist mode
	if playlist_mode is True:
		cmd.append("--yes-playlist")
	elif playlist_mode is False:
		cmd.append("--no-playlist")
	
	# Format selection
	if is_audio:
		cmd.extend(["-x", "--audio-format", "mp3"])
		# Quality (Bitrate)
		if quality_str and "kbps" in quality_str:
			bitrate = quality_str.split(" ")[0] # e.g. "320"
			cmd.extend(["--audio-quality", f"{bitrate}K"])
		else:
			# Best (Default) - usually 0 (best)
			cmd.extend(["--audio-quality", "0"])
	else:
		cmd.extend(["--format", "bestvideo+bestaudio/best"])
		cmd.extend(["--merge-output-format", "mp4"])
		# Quality (Resolution)
		if quality_str and "p" in quality_str:
			res = quality_str.replace("p", "") # e.g. "1080"
			# yt-dlp format selector for resolution
			cmd.extend(["-S", f"res:{res}"])

	# Trimming
	if start_time and end_time:
		cmd.extend(["--download-sections", f"*{start_time}-{end_time}"])

	cmd.append(url)
	
	# Run command
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	
	process = subprocess.Popen(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		startupinfo=startupinfo,
		encoding='utf-8',
		errors='replace'
	)
	
	for line in process.stdout:
		line = line.strip()
		if not line: continue
		
		# Parse progress
		if progress_hook:
			if "[download]" in line:
				# Extract percentage
				# Example: [download]  45.6% of 10.00MiB at 2.00MiB/s ETA 00:05
				percent = None
				try:
					parts = line.split()
					for part in parts:
						if "%" in part:
							percent = float(part.replace("%", ""))
							break
				except:
					pass
				
				progress_hook(line, percent)
			elif "[ExtractAudio]" in line:
				progress_hook("Converting to MP3...")
			elif "[Merger]" in line:
				progress_hook("Merging video/audio...")
				
	process.wait()
	
	if process.returncode != 0:
		raise Exception("Download failed. Check logs or URL.")
		
	if progress_hook:
		progress_hook("Download finished!")
		ui.message("Download finished!")


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
					except:
						pass
		except:
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
					except:
						pass
				# Also check for .webm / .m4a that might be left over from merge
				# Be careful not to delete finished files if we are not sure
				# But if this is called on STOP, we assume we want to kill everything for this title
				elif file.endswith(".webm") or file.endswith(".m4a"):
					# Only delete if it looks like a stream (often has .fXXX format)
					if ".f" in file: 
						try:
							os.remove(os.path.join(output_path, file))
						except:
							pass
	except:
		pass

def get_playlist_info(url):
	"""
	Fetches playlist metadata (title and entries) without downloading.
	Returns a dict: {'title': str, 'entries': [{'id': str, 'title': str}, ...]}
	"""
	yt_dlp_path, _ = check_dependencies()
	
	# Command to dump single json
	cmd = [
		yt_dlp_path,
		"--flat-playlist",
		"--dump-single-json",
		"--no-warnings",
		"--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
		url
	]
	
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	
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

def download_video_with_process(url, output_path, is_audio, quality_str, start_time, end_time, progress_hook, playlist_mode=None, playlist_items=None, playlist_title=None):
	"""
	Same as download_video but returns the process object for pause/stop control.
	Supports advanced playlist downloading with item selection and folder creation.
	"""
	yt_dlp_path, ffmpeg_path = check_dependencies(progress_hook)
	
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
		except:
			pass # Should handle permission errors gracefully

	# Temp path for intermediate files
	temp_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "nvda_yt_downloader")
	if not os.path.exists(temp_path):
		try:
			os.makedirs(temp_path)
		except:
			pass
	
	# Build command
	cmd = [
		yt_dlp_path,
		"--ffmpeg-location", os.path.dirname(ffmpeg_path),
		"--output", out_tmpl, # Output template (relative to paths)
		"--paths", f"home:{output_path}", # Final destination
		"--paths", f"temp:{temp_path}", # Temp destination
		"--newline", # Ensure progress is printed on new lines for parsing
		"--extractor-args", "youtube:player_client=default",
		"--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
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
		cmd.extend(["-x", "--audio-format", "mp3"])
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

	cmd.append(url)
	
	# Run command
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	
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
