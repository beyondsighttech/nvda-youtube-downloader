import globalPluginHandler
import addonHandler
import wx
from . import dialogs
import os
import logging
import api
import controlTypes
from NVDAObjects.IAccessible import IAccessible
import threading
import subprocess
from . import downloader
import config
import gui
from gui import guiHelper, settingsDialogs


# Try to import UIAHandler (only available in NVDA)
try:
	from UIAHandler import handler
	from UIAHandler import UIA
except ImportError:
	handler = None
	UIA = None

addonHandler.initTranslation()

# Setup basic logging to a temp file for debugging
# Setup basic logging (NVDA will handle this, or we can silence it)
# logging.basicConfig(level=logging.INFO)

# Register Configuration
confspec = {
	"youtubeDownloader": {
		"downloadPath": "string(default='')",
		"lastFormat": "string(default='MP3')",
		"lastQuality": "string(default='Best (Default)')",
		"sponsorBlockEnabled": "boolean(default=False)",
		"embedMetadata": "boolean(default=True)",
		"downloadSubtitles": "boolean(default=False)",
		"normalizeAudio": "boolean(default=False)"
	}
}
config.conf.spec.update(confspec)

class YouTubeDownloaderSettingsPanel(settingsDialogs.SettingsPanel):
	title = _("YouTube Downloader")
	
	def makeSettings(self, settingsSizer):
		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		
		# Download Path
		download_path = config.conf["youtubeDownloader"]["downloadPath"]
		if not download_path:
			download_path = os.path.join(os.path.expanduser("~"), "Downloads")
		
		self.pathEntry = sHelper.addLabeledControl(_("Download Folder:"), wx.TextCtrl)
		self.pathEntry.Value = download_path
		b = wx.Button(self, label=_("Browse..."))
		b.Bind(wx.EVT_BUTTON, self.onBrowse)
		sHelper.addItem(b)
		
		# Update Check
		b_update = wx.Button(self, label=_("Check for Updates"))
		b_update.Bind(wx.EVT_BUTTON, self.onCheckUpdates)
		sHelper.addItem(b_update)
		
		# SponsorBlock Setting
		self.chkSponsorBlock = wx.CheckBox(self, label=_("Enable SponsorBlock (Remove Sponsors)"))
		self.chkSponsorBlock.Value = config.conf["youtubeDownloader"]["sponsorBlockEnabled"]
		sHelper.addItem(self.chkSponsorBlock)
		
		# Metadata Setting
		self.chkEmbedMetadata = wx.CheckBox(self, label=_("Embed Metadata (Artist/Title/Chapters)"))
		self.chkEmbedMetadata.Value = config.conf["youtubeDownloader"]["embedMetadata"]
		sHelper.addItem(self.chkEmbedMetadata)

		# Subtitles Setting
		self.chkSubtitles = wx.CheckBox(self, label=_("Download & Embed Subtitles"))
		self.chkSubtitles.Value = config.conf["youtubeDownloader"]["downloadSubtitles"]
		sHelper.addItem(self.chkSubtitles)

		# Audio Normalization Setting
		self.chkNormalize = wx.CheckBox(self, label=_("Normalize Audio (Consistent Volume)"))
		self.chkNormalize.Value = config.conf["youtubeDownloader"]["normalizeAudio"]
		sHelper.addItem(self.chkNormalize)
		
	def onCheckUpdates(self, event):
		# We need to run this in a thread to not block GUI
		threading.Thread(target=self._run_manual_update).start()
		
	def _run_manual_update(self):
		# Get the plugin instance
		plugin = None
		for p in globalPluginHandler.runningPlugins:
			if isinstance(p, GlobalPlugin):
				plugin = p
				break
				
		if plugin:
			result = plugin._silent_update(manual=True)
			wx.CallAfter(wx.MessageBox, result, _("Update Check"), wx.OK | wx.ICON_INFORMATION)
		else:
			wx.CallAfter(wx.MessageBox, "Plugin instance not found.", _("Error"), wx.OK | wx.ICON_ERROR)

	def onBrowse(self, event):
		dlg = wx.DirDialog(self, _("Choose Download Folder"), self.pathEntry.Value)
		if dlg.ShowModal() == wx.ID_OK:
			self.pathEntry.Value = dlg.GetPath()
		dlg.Destroy()
		
	def onSave(self):
		config.conf["youtubeDownloader"]["downloadPath"] = self.pathEntry.Value
		config.conf["youtubeDownloader"]["sponsorBlockEnabled"] = self.chkSponsorBlock.Value
		config.conf["youtubeDownloader"]["embedMetadata"] = self.chkEmbedMetadata.Value
		config.conf["youtubeDownloader"]["downloadSubtitles"] = self.chkSubtitles.Value
		config.conf["youtubeDownloader"]["normalizeAudio"] = self.chkNormalize.Value

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		logging.info("YouTube Downloader Addon Loaded")
		
		# Register settings panel
		settingsDialogs.NVDASettingsDialog.categoryClasses.append(YouTubeDownloaderSettingsPanel)
		
		# Initialize state
		self.dlg = None
		self.downloads = {} # {id: {'title': str, 'status': str, 'process': Popen}}
		self.next_download_id = 0
		self.is_updating = False
		
		# Queue System
		self.download_queue = [] # List of d_ids waiting to start
		self.MAX_CONCURRENT = 3
		
		# Create Menu
		self.createMenu()
		
		# Start silent update check (Always enabled now)
		threading.Thread(target=self._silent_update, daemon=True).start()
			
		# Load saved downloads
		self.load_state()

	def createMenu(self):
		# Add to Tools menu
		self.toolsMenu = gui.mainFrame.sysTrayIcon.toolsMenu
		self.menuItem = self.toolsMenu.Append(wx.ID_ANY, _("YouTube Downloader..."), _("Open YouTube Downloader"))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.script_openDownloader, self.menuItem)

	def terminate(self):
		# Unregister settings panel
		try:
			settingsDialogs.NVDASettingsDialog.categoryClasses.remove(YouTubeDownloaderSettingsPanel)
		except:
			pass
			
		# Remove menu item
		try:
			if self.menuItem:
				self.toolsMenu.Remove(self.menuItem)
		except:
			pass
			
		# Close dialog if open
		if self.dlg:
			self.dlg.Destroy()
			
		# Kill all active downloads
		for d_id, data in self.downloads.items():
			if data.get('process'):
				try:
					data['process'].terminate()
					# Give it a moment to die gracefully
					data['process'].wait(timeout=1)
				except:
					pass
			# Mark as interrupted if it was running
			status = data.get('status', '')
			if "Completed" not in status and "Error" not in status and "Stopped" not in status:
				data['status'] = "Interrupted"
		
		self.save_state()
			
		super(GlobalPlugin, self).terminate()

	def save_state(self):
		"""Saves the current downloads to a JSON file."""
		state_file = os.path.join(os.path.expanduser("~"), "nvda_yt_downloader_state.json")
		data_to_save = {}
		for d_id, data in self.downloads.items():
			# Skip completed items to keep list clean on restart
			if "Completed" in data.get('status', ''):
				continue
				
			# Create serializable copy
			item = data.copy()
			if 'process' in item:
				del item['process']
			data_to_save[d_id] = item
			
		try:
			import json
			with open(state_file, 'w', encoding='utf-8') as f:
				json.dump(data_to_save, f, indent=4)
		except Exception as e:
			logging.error(f"Failed to save state: {e}")

	def load_state(self):
		"""Loads downloads from JSON file."""
		state_file = os.path.join(os.path.expanduser("~"), "nvda_yt_downloader_state.json")
		if not os.path.exists(state_file):
			return
			
		try:
			import json
			with open(state_file, 'r', encoding='utf-8') as f:
				saved_data = json.load(f)
				
			if not saved_data: return
			
			# Restore
			max_id = 0
			for d_id_str, data in saved_data.items():
				d_id = int(d_id_str)
				if d_id > max_id: max_id = d_id
				
				# Reset process and status
				data['process'] = None
				status = data.get('status', '')
				if "Error" not in status and "Stopped" not in status and "Completed" not in status:
					data['status'] = "Interrupted"
				
				self.downloads[d_id] = data
				
			self.next_download_id = max_id + 1
		except Exception as e:
			logging.error(f"Failed to load state: {e}")

	def _silent_update(self, manual=False):
		"""Runs yt-dlp -U to update the binary."""
		self.is_updating = True
		status_msg = "Update check failed."
		try:
			yt_dlp_path = downloader.get_yt_dlp_path()
			if os.path.exists(yt_dlp_path):
				logging.info("Checking for yt-dlp updates...")
				# Hide console
				startupinfo = subprocess.STARTUPINFO()
				startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
				
				# Capture output
				proc = subprocess.run(
					[yt_dlp_path, "-U"], 
					capture_output=True, 
					text=True, 
					startupinfo=startupinfo, 
					check=False,
					encoding='utf-8', 
					errors='replace',
					timeout=120
				)
				
				output = proc.stdout + "\n" + proc.stderr
				logging.info(f"Update Output: {output}")
				
				if "up-to-date" in output or "is up to date" in output:
					status_msg = "yt-dlp is up to date."
				elif "Updating to version" in output:
					# Parse version if possible
					try:
						ver = output.split("Updating to version")[1].split()[0]
						status_msg = f"Updated yt-dlp to version {ver}."
					except:
						status_msg = "Updated yt-dlp to latest version."
				else:
					status_msg = f"Update Info: {output.strip()[:100]}..." # Truncate for msg box
					
		except Exception as e:
			logging.error(f"Auto-update failed: {e}")
			status_msg = f"Update failed: {str(e)}"
		finally:
			self.is_updating = False
			# Process queue in case downloads were added while updating
			wx.CallAfter(self._process_queue)
			
		return status_msg

	scriptCategory = _("YouTube Downloader")

	def script_openDownloader(self, gesture):
		"""Opens the YouTube Downloader dialog."""
		logging.info("Opening Downloader GUI")
		url = self.get_video_url()
		# Ensure we are on the main thread for GUI operations
		wx.CallAfter(self._showGui, url)
	
	def script_openSettings(self, gesture):
		"""Opens the YouTube Downloader settings."""
		wx.CallAfter(gui.mainFrame._popupSettingsDialog, settingsDialogs.NVDASettingsDialog, YouTubeDownloaderSettingsPanel)

	def get_video_url(self):
		url = ""
		
		# Strategy 1: UIA (Robust Browser Detection)
		if handler and UIA:
			try:
				# Get the foreground window
				focus = api.getFocusObject()
				if focus.appModule.appName in ["chrome", "msedge", "firefox", "brave"]:
					# We are in a browser. Try to find the address bar.
					# Helper to check if obj is address bar
					def is_address_bar(obj):
						if obj.role == controlTypes.Role.EDIT:
							name = (obj.name or "").lower()
							if "address" in name or "search" in name or "location" in name:
								# Check value
								val = obj.value or ""
								if "youtube.com" in val or "youtu.be" in val:
									return True
						return False
					# Search up to window
					curr = focus
					while curr and curr.role != controlTypes.Role.WINDOW:
						curr = curr.parent
					
					window = curr
					if window:
						# BFS Search
						queue = [window]
						visited = set()
						# Limit depth/count to avoid freeze
						count = 0
						while queue and count < 500:
							node = queue.pop(0)
							count += 1
							
							if is_address_bar(node):
								url = node.value
								logging.info(f"Found URL via UIA: {url}")
								return url
							
							# Add children
							child = node.firstChild
							while child:
								queue.append(child)
								child = child.next
			except Exception as e:
				logging.error(f"UIA URL fetch failed: {type(e).__name__}: {e}", exc_info=True)

		# Strategy 2: Clipboard (Fallback)
		if not url:
			try:
				if wx.TheClipboard.Open():
					if wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_TEXT)):
						data = wx.TextDataObject()
						wx.TheClipboard.GetData(data)
						text = data.GetText()
						if "youtube.com" in text or "youtu.be" in text:
							url = text
							logging.info(f"Found URL via Clipboard: {url}")
					wx.TheClipboard.Close()
			except:
				pass
			
		return url

	def _showGui(self, url=""):
		if self.dlg:
			self.dlg.Raise()
			self.dlg.SetFocus()
			if url:
				self.dlg.txt_url.Value = url
			return

		# Create and show the dialog
		# We pass self (plugin instance) to the dialog
		self.dlg = dialogs.DownloaderDialog(None, self, url)
		self.dlg.Show()
		self.dlg.Raise()
		self.dlg.SetFocus()

	def is_url_downloading(self, url):
		"""Checks if a URL is currently being downloaded."""
		for data in self.downloads.values():
			if data.get('url') == url and data.get('status') != "Completed" and data.get('status') != "Error":
				return True
		return False

	def start_batch_download(self, playlist_url, is_audio, quality_str, items, playlist_title, audio_format="mp3"):
		"""Starts downloads for multiple items from a playlist."""
		# items is list of {'id':..., 'title':...}
		for item in items:
			video_id = item['id']
			video_title = item['title']
			video_url = f"https://www.youtube.com/watch?v={video_id}"
			
			# We pass playlist_title to ensure they go into the same folder
			# We pass video_title as known_title to avoid "Resolving..."
			self.start_download(video_url, is_audio, quality_str, None, None, playlist_mode=False, playlist_title=playlist_title, known_title=video_title)

	def start_download(self, url, is_audio, quality_str, start_time, end_time, playlist_mode=None, playlist_items=None, playlist_title=None, known_title=None, audio_format="mp3"):
		"""Adds a download to the queue."""
		d_id = self.next_download_id
		self.next_download_id += 1
		
		# Read Global Settings
		remove_sponsors = config.conf["youtubeDownloader"]["sponsorBlockEnabled"]
		embed_metadata = config.conf["youtubeDownloader"]["embedMetadata"]
		download_subs = config.conf["youtubeDownloader"]["downloadSubtitles"]
		normalize_audio = config.conf["youtubeDownloader"]["normalizeAudio"]
		
		initial_title = known_title if known_title else f"Resolving... {url}"
		if playlist_title and not known_title:
			initial_title = f"{playlist_title} - Item"
			
		self.downloads[d_id] = {
			'title': initial_title,
			'status': "Queued",
			'process': None,
			'url': url,
			'params': {
				'url': url,
				'is_audio': is_audio,
				'quality_str': quality_str,
				'start_time': start_time,
				'end_time': end_time,
				'playlist_mode': playlist_mode,
				'playlist_items': playlist_items,
				'playlist_title': playlist_title,
				'known_title': known_title,
				'playlist_title': playlist_title,
				'known_title': known_title,
				'remove_sponsors': remove_sponsors,
				'embed_metadata': embed_metadata,
				'download_subs': download_subs,
				'normalize_audio': normalize_audio,
				'audio_format': audio_format
			}
		}
		
		# Update UI immediately
		if self.dlg:
			self.dlg.add_download_item(d_id, self.downloads[d_id]['title'])
		
		self.download_queue.append(d_id)
		self._process_queue()

	def _process_queue(self):
		"""Checks active downloads and starts new ones from queue."""
		# Prevent starting downloads while updating binary
		if self.is_updating:
			return

		# Count active
		active_count = 0
		for data in self.downloads.values():
			status = data.get('status', '')
			# We consider these states as "taking up a slot"
			if "Downloading" in status or "Starting" in status or "Resolving" in status or "Converting" in status or "Merging" in status or "Resuming" in status:
				active_count += 1
		
		# Start new downloads if slots available
		while active_count < self.MAX_CONCURRENT and self.download_queue:
			d_id = self.download_queue.pop(0)
			if d_id in self.downloads:
				# Double check it wasn't cancelled/removed
				self._start_actual_download(d_id)
				active_count += 1

	def _start_actual_download(self, d_id):
		"""Spawns the thread for a download."""
		data = self.downloads[d_id]
		params = data['params']
		
		# Set status synchronously to avoid race condition where _process_queue runs again before thread starts
		self._update_ui_status(d_id, f"{data['title']} - Starting...")
		
		thread = threading.Thread(
			target=self._run_download_thread, 
			args=(d_id, params['url'], params['is_audio'], params['quality_str'], params['start_time'], params['end_time'], params['playlist_mode'], params['playlist_items'], params['playlist_title'], params.get('known_title'), params.get('remove_sponsors', False), params.get('embed_metadata', True), params.get('download_subs', False), params.get('normalize_audio', False), params.get('audio_format', "mp3"))
		)
		thread.start()

	def start_playlist_download(self, url, is_audio, quality_str, playlist_items, playlist_title):
		"""Legacy helper, now redirects to batch if possible or single."""
		# If we get here with a string of items "1,2,3", it's the old way.
		# But dialogs.py now calls start_batch_download.
		# We keep this just in case, treating it as a single download task (old behavior)
		# or we could try to parse it. 
		# For now, let's just call start_download which queues it.
		self.start_download(url, is_audio, quality_str, None, None, playlist_mode=True, playlist_items=playlist_items, playlist_title=playlist_title)

	def _run_download_thread(self, d_id, url, is_audio, quality_str, start_time, end_time, playlist_mode, playlist_items, playlist_title, known_title=None, remove_sponsors=False, embed_metadata=True, download_subs=False, normalize_audio=False, audio_format="mp3"):
		try:
			# 1. Fetch Title
			title = known_title if known_title else "Unknown Video"
			
			if not known_title:
				if playlist_title and not playlist_mode:
					# It's an item in a playlist, but we don't have the title?
					# We'll let yt-dlp resolve it.
					pass
				elif playlist_mode is not True:
					yt_dlp_path = downloader.get_yt_dlp_path()
					try:
						startupinfo = subprocess.STARTUPINFO()
						startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
						result = subprocess.run(
							[yt_dlp_path, "--get-title", "--skip-download", "--no-warnings", "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", url],
							capture_output=True, text=True, startupinfo=startupinfo, check=False
						)
						if result.returncode == 0:
							title = result.stdout.strip()
						else:
							logging.error(f"Failed to fetch title for {url}. Return code: {result.returncode}. Stderr: {result.stderr}")
							# Fallback title if individual fetch fails (try to proceed with download anyway using URL as pseudo-title)
							title = "Video_" + url.split("v=")[-1].split("&")[0]
					except:
						pass
				else:
					title = playlist_title if playlist_title else "Playlist"

			# Truncate title for status
			display_title = title
			if len(display_title) > 30:
				display_title = display_title[:27] + "..."
				
			self.downloads[d_id]['title'] = title 
			self._update_ui_status(d_id, f"{display_title} - Downloading...")

			# 2. Download
			download_path = config.conf["youtubeDownloader"]["downloadPath"]
			# Ensure download path exists or try to create it
			if download_path:
				try:
					if not os.path.exists(download_path):
						os.makedirs(download_path)
				except Exception as e:
					logging.error(f"Failed to create download directory '{download_path}': {e}")
					# Fallback to defaults if creation fails
					download_path = os.path.join(os.path.expanduser("~"), "Downloads")
			else:
				download_path = os.path.join(os.path.expanduser("~"), "Downloads")
			
			if not os.path.exists(download_path):
				try:
					os.makedirs(download_path)
				except:
					pass
			
			def progress_hook(status):
				self._update_ui_status(d_id, f"{display_title} - {status}")

			process = downloader.download_video_with_process(
				url, download_path, is_audio, quality_str, start_time, end_time, progress_hook, playlist_mode, playlist_items, playlist_title, remove_sponsors, embed_metadata, download_subs, normalize_audio, audio_format
			)
			self.downloads[d_id]['process'] = process
			
			# Read output in real-time
			last_lines = []
			current_video_name = ""
			
			for line in process.stdout:
				line = line.strip()
				if not line: continue
				
				last_lines.append(line)
				if len(last_lines) > 10:
					last_lines.pop(0)
				
				if "[download]" in line:
					if "Destination:" in line:
						parts = line.split("Destination: ")
						if len(parts) > 1:
							self.downloads[d_id]['current_filename'] = parts[1].strip()
							fname = os.path.basename(self.downloads[d_id]['current_filename'])
							current_video_name = os.path.splitext(fname)[0]
							if len(current_video_name) > 20:
								current_video_name = current_video_name[:17] + "..."
						continue
						
					percent = None
					try:
						parts = line.split()
						for part in parts:
							if "%" in part:
								percent = float(part.replace("%", ""))
								break
					except:
						pass
					
					if "Downloading video" in line:
						try:
							progress_part = line.split("Downloading video ")[1].strip()
							self._update_ui_status(d_id, f"{display_title} - Video {progress_part}")
						except:
							self._update_ui_status(d_id, f"{display_title} - {line}")
					elif percent is not None:
						status_msg = f"{display_title} - "
						if current_video_name:
							status_msg += f"{current_video_name} "
						status_msg += f"{percent}%"
						self._update_ui_status(d_id, status_msg, percent)
						
				elif "[ExtractAudio]" in line:
					self._update_ui_status(d_id, f"Converting to {audio_format.upper()}...", None)
				elif "[Merger]" in line:
					self._update_ui_status(d_id, "Merging video/audio...", None)
				elif "Merging formats into" in line:
					parts = line.split('Merging formats into "')
					if len(parts) > 1:
						fname = parts[1].strip()
						if fname.endswith('"'): fname = fname[:-1]
						self.downloads[d_id]['current_filename'] = fname

			process.wait()
			
			if process.returncode == 0:
				self.downloads[d_id]['status'] = "Completed"
				self._update_ui_status(d_id, f"{title} - Completed", 100)
				import ui
				ui.message(f"Download complete: {title}")
				self.save_state()
			else:
				error_details = "\n".join(last_lines)
				raise Exception(f"Process returned non-zero exit code.\nLast output:\n{error_details}")

		except Exception as e:
			# Check if manually stopped to avoid overwriting "Stopped" status with "Error"
			if not self.downloads[d_id].get('manual_stop', False):
				self.downloads[d_id]['status'] = "Error"
				self._update_ui_status(d_id, f"Error: {title}")
				logging.error(f"Download error {d_id}: {e}")
			else:
				logging.info(f"Download {d_id} stopped manually.")
				
			self.save_state()
		
		finally:
			# Trigger queue processing
			wx.CallAfter(self._process_queue)

	def _update_ui_status(self, d_id, status_text, percent=None):
		self.downloads[d_id]['status'] = status_text
		if self.dlg:
			wx.CallAfter(self.dlg.update_status, d_id, status_text, percent)

	def retry_download(self, d_id):
		if d_id in self.downloads:
			data = self.downloads[d_id]
			
			# Reset status
			data['status'] = "Queued"
			self._update_ui_status(d_id, f"{data['title']} - Queued")
			
			# Re-add to queue
			if d_id not in self.download_queue:
				self.download_queue.append(d_id)
			
			self._process_queue()

	def stop_download(self, d_id):
		if d_id in self.downloads:
			data = self.downloads[d_id]
			
			if d_id in self.download_queue:
				self.download_queue.remove(d_id)
			
			# Flag as manual stop to prevent "Error" status race condition in thread
			data['manual_stop'] = True
			
			proc = data.get('process')
			if proc and proc.poll() is None:
				try:
					proc.terminate()
					proc.wait(timeout=2)
				except:
					# Force kill if terminate fails or times out
					try:
						proc.kill()
					except:
						pass
			
			# Cleanup partial files (User requested Stop = Delete)
			download_path = config.conf["youtubeDownloader"]["downloadPath"]
			if not download_path:
				download_path = os.path.join(os.path.expanduser("~"), "Downloads")
			
			# Also check temp path
			temp_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "nvda_yt_downloader")
			
			filename = data.get('current_filename')
			downloader.cleanup_partial_files(download_path, data['title'], filename)
			downloader.cleanup_partial_files(temp_path, data['title'], filename)
			
			# Mark as Stopped (Keep in list so user can Retry or Remove)
			self.downloads[d_id]['status'] = "Stopped"
			self._update_ui_status(d_id, f"{data['title']} - Stopped")
			self.save_state()
			
			# Free up slot
			wx.CallAfter(self._process_queue)

	def remove_download(self, d_id):
		"""Removes a download from the list."""
		if d_id in self.downloads:
			# If it's running, stop it first (safety check)
			proc = self.downloads[d_id].get('process')
			if proc and proc.poll() is None:
				self.stop_download(d_id)
				
			del self.downloads[d_id]
			self.save_state()
			
			# Update UI
			if self.dlg:
				wx.CallAfter(self.dlg.remove_download_item, d_id)

	__gestures = {
		"kb:NVDA+shift+y": "openDownloader",
	}
