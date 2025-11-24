import globalPluginHandler
import wx
import gui
import scriptHandler
import addonHandler
import ui
import config
import os
import sys
import subprocess
import threading
import time

# Add current directory to path to import local modules
sys.path.append(os.path.dirname(__file__))
from . import dialogs
from . import downloader

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		self.dlg = None
		self.downloads = {} # {d_id: {'title': str, 'status': str, 'process': Popen, 'url': str, 'params': dict}}
		self.download_queue = [] # [d_id, d_id, ...]
		self.next_download_id = 1
		self.MAX_CONCURRENT = 3
		self.is_updating = False
		
		# Ensure dependencies exist (async to not block NVDA start)
		threading.Thread(target=self._init_dependencies).start()
		
	def _init_dependencies(self):
		try:
			downloader.check_dependencies()
		except:
			# If check fails (e.g. first run), try to download? 
			# For now, we assume user/installer handles it or we can add auto-download logic here.
			# But to be safe, we just log/ignore.
			pass

	def script_openDownloader(self, gesture):
		if self.dlg:
			self.dlg.Raise()
			self.dlg.SetFocus()
			return
			
		# Check dependencies before opening
		try:
			downloader.check_dependencies()
		except Exception as e:
			# If missing, maybe ask to download?
			# For now, just warn
			ui.message("YouTube Downloader dependencies missing. Please check the addon installation.")
			return

		# Get clipboard text
		try:
			if wx.TheClipboard.Open():
				if wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_TEXT)):
					data = wx.TextDataObject()
					wx.TheClipboard.GetData(data)
					text = data.GetText().strip()
					# Simple check if it looks like a YT link
					if "youtube.com" in text or "youtu.be" in text:
						self.dlg = dialogs.DownloaderDialog(gui.mainFrame, self, url=text)
					else:
						self.dlg = dialogs.DownloaderDialog(gui.mainFrame, self)
				else:
					self.dlg = dialogs.DownloaderDialog(gui.mainFrame, self)
				wx.TheClipboard.Close()
			else:
				self.dlg = dialogs.DownloaderDialog(gui.mainFrame, self)
		except:
			self.dlg = dialogs.DownloaderDialog(gui.mainFrame, self)
			
		self.dlg.Show()

	def start_download(self, url, is_audio, quality_str, start_time, end_time, playlist_mode=None, playlist_items=None, playlist_title=None, known_title=None):
		"""Adds a download to the queue."""
		d_id = self.next_download_id
		self.next_download_id += 1
		
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
				'known_title': known_title
			}
		}
		
		# Update UI immediately
		if self.dlg:
			self.dlg.add_download_item(d_id, self.downloads[d_id]['title'])
		
		self.download_queue.append(d_id)
		self._process_queue()
		
	def start_batch_download(self, url, is_audio, quality_str, items, playlist_title):
		"""Starts multiple downloads from a playlist selection."""
		# items is list of {'id':..., 'title':...}
		
		# Create a subfolder name based on playlist title
		# We pass this to the downloader to handle folder creation
		
		for item in items:
			# Construct video URL
			vid_url = f"https://www.youtube.com/watch?v={item['id']}"
			# Add to queue
			# We pass playlist_mode=True to ensure it uses the playlist folder logic if needed
			# But actually, if we want individual files in a folder, we can just pass the folder path logic
			# or let the downloader handle it via playlist_title arg.
			
			self.start_download(
				vid_url, 
				is_audio, 
				quality_str, 
				None, None, # No trimming for batch usually
				playlist_mode=True, # Use playlist logic for args
				playlist_items=None, # Single item download but part of playlist context
				playlist_title=playlist_title,
				known_title=item['title']
			)

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
		data = self.downloads[d_id]
		params = data['params']
		
		# Update status
		self._update_ui_status(d_id, f"{data['title']} - Starting...")
		
		# Start thread
		t = threading.Thread(target=self._download_thread, args=(d_id, params))
		t.start()

	def _download_thread(self, d_id, params):
		# Define progress hook
		def progress_hook(status_msg, percent=None):
			if d_id in self.downloads:
				# Store current filename if available (for cleanup)
				# We don't easily get the filename from yt-dlp stdout until end, 
				# but we can try to infer or just rely on title.
				
				self._update_ui_status(d_id, f"{self.downloads[d_id]['title']} - {status_msg}", percent)

		try:
			# Get default download path from config
			download_path = config.conf["youtubeDownloader"]["downloadPath"]
			if not download_path:
				download_path = os.path.join(os.path.expanduser("~"), "Downloads")
				
			# Call downloader
			process = downloader.download_video_with_process(
				params['url'],
				download_path,
				params['is_audio'],
				params['quality_str'],
				params['start_time'],
				params['end_time'],
				progress_hook,
				playlist_mode=params['playlist_mode'],
				playlist_items=params['playlist_items'],
				playlist_title=params['playlist_title']
			)
			
			if d_id in self.downloads:
				self.downloads[d_id]['process'] = process
				
			# Wait for finish
			process.wait()
			
			if d_id in self.downloads:
				if process.returncode == 0:
					self.downloads[d_id]['status'] = "Completed"
					self._update_ui_status(d_id, f"{self.downloads[d_id]['title']} - Completed", 100)
				else:
					# Check if it was stopped manually (we set status to Stopped/Removed)
					curr_status = self.downloads[d_id].get('status', '')
					if "Stopped" not in curr_status:
						self.downloads[d_id]['status'] = "Error"
						self._update_ui_status(d_id, f"{self.downloads[d_id]['title']} - Error")
						
		except Exception as e:
			if d_id in self.downloads:
				self.downloads[d_id]['status'] = "Error"
				self._update_ui_status(d_id, f"{self.downloads[d_id]['title']} - Error: {str(e)}")
		finally:
			# Trigger next in queue
			wx.CallAfter(self._process_queue)

	def _update_ui_status(self, d_id, status_text, percent=None):
		self.downloads[d_id]['status'] = status_text
		if self.dlg:
			wx.CallAfter(self.dlg.update_status, d_id, status_text, percent)

	def is_url_downloading(self, url):
		for data in self.downloads.values():
			if data['url'] == url and "Completed" not in data.get('status', '') and "Error" not in data.get('status', '') and "Stopped" not in data.get('status', ''):
				return True
		return False

	def retry_download(self, d_id):
		if d_id in self.downloads:
			data = self.downloads[d_id]
			
			# Reset status
			data['status'] = 'Queued'
			self._update_ui_status(d_id, f"{data['title']} - Queued")
			
			# Re-add to queue
			if d_id not in self.download_queue:
				self.download_queue.append(d_id)
			
			self._process_queue()
			return True
		return False

	def stop_download(self, d_id):
		if d_id in self.downloads:
			data = self.downloads[d_id]
			
			if d_id in self.download_queue:
				self.download_queue.remove(d_id)
			
			proc = data.get('process')
			if proc and proc.poll() is None:
				proc.terminate()
				proc.wait(timeout=3)
			
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

	def save_state(self):
		# Placeholder for saving state to disk if needed
		pass
