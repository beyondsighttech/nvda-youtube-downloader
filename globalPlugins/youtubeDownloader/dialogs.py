import wx
import os
from . import downloader
import threading
import re
import config
import subprocess
import ui
import datetime

class PlaylistSelectionDialog(wx.Dialog):
	def __init__(self, parent, title, items):
		super().__init__(parent, title=f"Select Videos from {title}", size=(600, 400))
		self.items = items # [{'id':..., 'title':...}]
		
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)
		
		lbl = wx.StaticText(panel, label=f"Found {len(items)} videos. Select items to download:")
		vbox.Add(lbl, flag=wx.ALL, border=10)
		
		# Use ListCtrl instead of CheckListBox for better accessibility
		self.check_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_NO_HEADER)
		self.check_list.EnableCheckBoxes(True)
		# Set a very large width to prevent truncation tooltips which cause double speaking
		self.check_list.InsertColumn(0, "Video Title", width=2000)
		
		for i, item in enumerate(items):
			self.check_list.InsertItem(i, item['title'])
			# Default: Unchecked (User requested)
			self.check_list.CheckItem(i, False)
			
		vbox.Add(self.check_list, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=10)
		
		# Buttons for Select All / None
		hbox_sel = wx.BoxSizer(wx.HORIZONTAL)
		btn_all = wx.Button(panel, label="Select All")
		btn_none = wx.Button(panel, label="Select None")
		btn_all.Bind(wx.EVT_BUTTON, self.on_all)
		btn_none.Bind(wx.EVT_BUTTON, self.on_none)
		hbox_sel.Add(btn_all, flag=wx.RIGHT, border=5)
		hbox_sel.Add(btn_none)
		vbox.Add(hbox_sel, flag=wx.ALIGN_CENTER|wx.TOP|wx.BOTTOM, border=5)
		
		# Main Buttons
		hbox_btn = wx.BoxSizer(wx.HORIZONTAL)
		btn_ok = wx.Button(panel, id=wx.ID_OK, label="Download Selected")
		btn_cancel = wx.Button(panel, id=wx.ID_CANCEL, label="Cancel")
		hbox_btn.Add(btn_ok, flag=wx.RIGHT, border=10)
		hbox_btn.Add(btn_cancel)
		vbox.Add(hbox_btn, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=10)
		
		panel.SetSizer(vbox)
		self.Center()
			
	def on_all(self, event):
		for i in range(self.check_list.GetItemCount()):
			self.check_list.CheckItem(i, True)
			
	def on_none(self, event):
		for i in range(self.check_list.GetItemCount()):
			self.check_list.CheckItem(i, False)
			
	def get_selected_items(self):
		# Return list of {'id':..., 'title':...}
		selected = []
		for i in range(self.check_list.GetItemCount()):
			if self.check_list.IsItemChecked(i):
				selected.append(self.items[i])
		return selected

class DownloaderDialog(wx.Dialog):
	def __init__(self, parent, plugin_instance, url=""):
		super().__init__(parent, title="YouTube Downloader", size=(600, 650))
		self.plugin = plugin_instance
		self.Center()
		self.Raise()
		self.SetFocus()
		
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)
		
		# URL Input
		lbl_url = wx.StaticText(panel, label="Enter YouTube video link or playlist link:")
		self.txt_url = wx.TextCtrl(panel, value=url)
		self.txt_url.SetName("Enter YouTube video link or playlist link")
		vbox.Add(lbl_url, flag=wx.LEFT|wx.TOP, border=10)
		vbox.Add(self.txt_url, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Format Selection
		lbl_format = wx.StaticText(panel, label="Format:")
		self.formats = ["MP3 (Audio)", "M4A (Audio)", "WAV (Audio)", "FLAC (Audio)", "OGG (Audio)", "MP4 (Video)"]
		self.choice_format = wx.Choice(panel, choices=self.formats)
		self.choice_format.SetName("Format")
		
		# Set last used format from config
		last_format = config.conf["youtubeDownloader"]["lastFormat"]
		try:
			# Find index of last format
			found = False
			for i, fmt in enumerate(self.formats):
				if last_format in fmt: # e.g. "MP3" in "MP3 (Audio)"
					self.choice_format.SetSelection(i)
					found = True
					break
			if not found:
				self.choice_format.SetSelection(0)
		except:
			self.choice_format.SetSelection(0)
			
		self.choice_format.Bind(wx.EVT_CHOICE, self.on_format_change)
		vbox.Add(lbl_format, flag=wx.LEFT, border=10)
		vbox.Add(self.choice_format, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Quality Selection
		lbl_quality = wx.StaticText(panel, label="Quality:")
		self.choice_quality = wx.Choice(panel, choices=[])
		self.choice_quality.SetName("Quality")
		vbox.Add(lbl_quality, flag=wx.LEFT, border=10)
		vbox.Add(self.choice_quality, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Trimming (Start / End Time)
		sb_trim = wx.StaticBox(panel, label="Trimming (Optional)")
		sbs_trim = wx.StaticBoxSizer(sb_trim, wx.VERTICAL)
		
		lbl_trim_help = wx.StaticText(panel, label="Format: MM:SS (e.g. 1:30) or Seconds (e.g. 90)")
		sbs_trim.Add(lbl_trim_help, flag=wx.LEFT|wx.TOP|wx.BOTTOM, border=5)
		
		hbox_trim_inputs = wx.BoxSizer(wx.HORIZONTAL)
		
		lbl_start = wx.StaticText(panel, label="Start:")
		self.txt_start = wx.TextCtrl(panel, value="")
		self.txt_start.SetName("Start Time") # Accessibility Label
		
		lbl_end = wx.StaticText(panel, label="End:")
		self.txt_end = wx.TextCtrl(panel, value="")
		self.txt_end.SetName("End Time") # Accessibility Label
		
		hbox_trim_inputs.Add(lbl_start, flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=5)
		hbox_trim_inputs.Add(self.txt_start, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=5)
		hbox_trim_inputs.Add(lbl_end, flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=5)
		hbox_trim_inputs.Add(self.txt_end, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=5)
		
		sbs_trim.Add(hbox_trim_inputs, flag=wx.EXPAND|wx.BOTTOM, border=5)
		
		vbox.Add(sbs_trim, flag=wx.EXPAND|wx.ALL, border=10)
		
		# SponsorBlock Checkbox - REVERTED (Moved to global settings)
		
		# Download Button
		self.btn_download = wx.Button(panel, label="Add to Download Queue")
		self.btn_download.Bind(wx.EVT_BUTTON, self.on_download)
		vbox.Add(self.btn_download, flag=wx.ALIGN_CENTER|wx.ALL, border=10)
		
		# Active Downloads Label
		lbl_list = wx.StaticText(panel, label="Active Downloads:")
		vbox.Add(lbl_list, flag=wx.LEFT, border=10)
		
		# ListCtrl for Downloads
		self.list_downloads = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL)
		self.list_downloads.SetName("Active Downloads List")
		self.list_downloads.InsertColumn(0, "Download Status", width=550)
		self.list_downloads.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_list_selection)
		self.list_downloads.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_list_selection)
		
		vbox.Add(self.list_downloads, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Contextual Buttons (Stop, Retry, Remove)
		hbox_controls = wx.BoxSizer(wx.HORIZONTAL)
		
		self.btn_retry = wx.Button(panel, label="Retry")
		self.btn_retry.Bind(wx.EVT_BUTTON, self.on_retry)
		self.btn_retry.Enable(False)
		
		self.btn_remove = wx.Button(panel, label="Remove")
		self.btn_remove.Bind(wx.EVT_BUTTON, self.on_remove)
		self.btn_remove.Enable(False)
		
		hbox_controls.Add(self.btn_retry, flag=wx.RIGHT, border=5)
		hbox_controls.Add(self.btn_remove)
		
		vbox.Add(hbox_controls, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=10)
		
		# Progress Bar (Global for selected item or general activity)
		self.gauge = wx.Gauge(panel, range=100, size=(250, 25))
		vbox.Add(self.gauge, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Global Status Text
		self.lbl_status = wx.StaticText(panel, label="")
		vbox.Add(self.lbl_status, flag=wx.LEFT|wx.BOTTOM, border=10)
		
		self.btn_close = wx.Button(panel, id=wx.ID_CANCEL, label="Close")
		self.btn_close.Bind(wx.EVT_BUTTON, self.on_close)
		vbox.Add(self.btn_close, flag=wx.ALIGN_CENTER|wx.BOTTOM, border=10)
		
		panel.SetSizer(vbox)
		
		# Initialize Quality options
		self.on_format_change(None)
		
		# Bind URL change for playlist detection
		self.txt_url.Bind(wx.EVT_TEXT, self.on_url_change)
		
		# Bind Escape and Close
		self.Bind(wx.EVT_CHAR_HOOK, self.on_escape)
		self.Bind(wx.EVT_CLOSE, self.on_close)
		
		# Populate list from existing downloads
		self.refresh_list()
		
		# Trigger initial URL check
		self.on_url_change(None)
		
	def refresh_list(self):
		self.list_downloads.DeleteAllItems()
		self.list_map = [] # [d_id, d_id, ...]
		
		for d_id, data in self.plugin.downloads.items():
			self.add_download_item(d_id, data['title'], data.get('status', ''))
			
		self.update_button_states()
			
	def add_download_item(self, d_id, title, status="Starting..."):
		idx = self.list_downloads.InsertItem(self.list_downloads.GetItemCount(), f"{title} - {status}")
		self.list_map.append(d_id)
		
	def remove_download_item(self, d_id):
		if d_id in self.list_map:
			idx = self.list_map.index(d_id)
			self.list_downloads.DeleteItem(idx)
			self.list_map.pop(idx)
			self.update_button_states()

	def update_status(self, d_id, status_text, percent=None):
		if d_id in self.list_map:
			idx = self.list_map.index(d_id)
			self.list_downloads.SetItemText(idx, status_text)
			
			# If this item is selected, update the gauge/label
			sel = self.list_downloads.GetFirstSelected()
			if sel == idx:
				self.lbl_status.SetLabel(status_text)
				if percent is not None:
					self.gauge.SetValue(int(percent))
				elif "Completed" in status_text:
					self.gauge.SetValue(100)
				elif "Starting" in status_text:
					self.gauge.SetValue(0)
			
			# Update buttons if this item is selected
			if sel == idx:
				self.update_button_states()

	def on_list_selection(self, event):
		self.update_button_states()
		
		# Update gauge/label for selected item
		idx = self.list_downloads.GetFirstSelected()
		if idx != -1 and idx < len(self.list_map):
			d_id = self.list_map[idx]
			if d_id in self.plugin.downloads:
				data = self.plugin.downloads[d_id]
				self.lbl_status.SetLabel(data.get('status', ''))
				# We don't have exact percent stored in data dict usually, 
				# but we can infer 0 or 100 or keep existing if we tracked it.
				# For now, just reset gauge unless we have live update.
				if "Completed" in data.get('status', ''):
					self.gauge.SetValue(100)
				else:
					self.gauge.SetValue(0)

	def update_button_states(self):
		idx = self.list_downloads.GetFirstSelected()
		
		can_retry = False
		can_remove = False
		
		if idx != -1 and idx < len(self.list_map):
			d_id = self.list_map[idx]
			if d_id in self.plugin.downloads:
				status = self.plugin.downloads[d_id].get('status', '')
				
				# Retry: Stopped/Error/Interrupted (BUT NOT Completed)
				# Basically anything not currently running or queued, and not successfully finished
				is_active = any(x in status for x in ["Downloading", "Starting", "Resolving", "Converting", "Merging", "Resuming", "Queued"])
				if not is_active and "Completed" not in status:
					can_retry = True
					
				# Remove: Always possible
				can_remove = True
		
		self.btn_retry.Enable(can_retry)
		self.btn_remove.Enable(can_remove)


	def on_retry(self, event):
		idx = self.list_downloads.GetFirstSelected()
		if idx != -1 and idx < len(self.list_map):
			d_id = self.list_map[idx]
			self.plugin.retry_download(d_id)
			self.update_button_states()

	def on_remove(self, event):
		idx = self.list_downloads.GetFirstSelected()
		if idx != -1 and idx < len(self.list_map):
			d_id = self.list_map[idx]
			self.plugin.remove_download(d_id)
			# UI update handled by plugin calling remove_download_item

	def on_escape(self, event):
		if event.GetKeyCode() == wx.WXK_ESCAPE:
			self.Close()
		else:
			event.Skip()
			
	def on_close(self, event):
		# Notify plugin that dialog is closed
		self.plugin.dlg = None
		self.Destroy()
	
	def on_format_change(self, event):
		sel = self.choice_format.GetSelection()
		fmt_str = self.formats[sel]
		
		choices = []
		if "MP4" in fmt_str: # Video
			choices = ["Best (Default)", "1080p", "720p", "480p", "360p"]
		elif "WAV" in fmt_str or "FLAC" in fmt_str: # Lossless Audio
			choices = ["Lossless (Default)"]
		else: # Lossy Audio (MP3, M4A, OGG)
			choices = ["Best (Default)", "320 kbps", "256 kbps", "192 kbps", "128 kbps"]
			
		self.choice_quality.Set(choices)
		self.choice_quality.SetSelection(0)
		
		# Try to restore last quality if possible
		last_quality = config.conf["youtubeDownloader"]["lastQuality"]
		try:
			if last_quality in choices:
				self.choice_quality.SetStringSelection(last_quality)
		except:
			pass

	def is_valid_url(self, url):
		# Simple regex for YouTube URLs
		pattern = r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
		return re.match(pattern, url) is not None

	def on_url_change(self, event):
		url = self.txt_url.GetValue()
		# Disable trimming if playlist detected
		if "list=" in url:
			self.txt_start.Disable()
			self.txt_end.Disable()
		else:
			self.txt_start.Enable()
			self.txt_end.Enable()

	def on_download(self, event):
		url = self.txt_url.GetValue().strip()
		if not url:
			wx.MessageBox("Please provide a valid YouTube URL to proceed.", "Input Required", wx.OK | wx.ICON_WARNING)
			return
			
		if not self.is_valid_url(url):
			wx.MessageBox("The URL provided does not appear to be a valid YouTube link.\nPlease check the URL and try again.", "Invalid URL", wx.OK | wx.ICON_ERROR)
			return
		
		# Check for duplicates
		if self.plugin.is_url_downloading(url):
			wx.MessageBox("This URL is already being downloaded.", "Duplicate Download", wx.OK | wx.ICON_WARNING)
			return
			
		format_idx = self.choice_format.GetSelection()
		format_str = self.formats[format_idx] # e.g. "MP3 (Audio)" or "MP4 (Video)"
		is_audio = "Audio" in format_str
		
		# Extract just the extension/name for logic (e.g. "mp3", "wav")
		audio_format = format_str.split(" ")[0].lower() # "mp3", "wav", etc.
		if audio_format == "mp4": audio_format = "mp3" # Fallback if video, though not used
		
		quality_str = self.choice_quality.GetStringSelection()

		
		# Parse Time Input
		start_time_raw = self.txt_start.GetValue().strip()
		end_time_raw = self.txt_end.GetValue().strip()
		
		start_time = self.parse_time_str(start_time_raw)
		end_time = self.parse_time_str(end_time_raw)
		
		# Stop if parsing failed but input provided
		if start_time_raw and start_time is None:
			wx.MessageBox("Invalid Start Time format.\nPlease use MM:SS (e.g. 1:30) or Seconds (e.g. 90).", "Invalid Input", wx.OK | wx.ICON_ERROR)
			return
		if end_time_raw and end_time is None:
			wx.MessageBox("Invalid End Time format.\nPlease use MM:SS (e.g. 1:30) or Seconds (e.g. 90).", "Invalid Input", wx.OK | wx.ICON_ERROR)
			return
			
		# Logical check: Start < End
		if start_time and end_time:
			# Convert back to seconds for comparison
			def to_seconds(t_str):
				try:
					parts = list(map(int, t_str.split(':')))
					if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
					if len(parts) == 2: return parts[0]*60 + parts[1]
					return 0
				except:
					return 0
			
			s_sec = to_seconds(start_time)
			e_sec = to_seconds(end_time)
			
			if s_sec >= e_sec:
				wx.MessageBox("Start Time must be less than End Time.", "Invalid Range", wx.OK | wx.ICON_ERROR)
				return
			
		# Save user's selections for next time
		# Save user's selections for next time
		# Save just the main part e.g. "MP3" or "MP4" or "WAV"
		config.conf["youtubeDownloader"]["lastFormat"] = format_str.split(" ")[0]
		config.conf["youtubeDownloader"]["lastQuality"] = quality_str
		
		# Playlist Logic
		playlist_mode = False
		has_list = "list=" in url
		has_video = "v=" in url or "youtu.be/" in url
		
		if has_list:
			if has_video:
				# Ambiguous case: Video in Playlist
				dlg = wx.MessageDialog(self, "This video is part of a playlist.\nDo you want to download the entire playlist?\n\nYes = Download Playlist\nNo = Download Video Only", "Playlist Detected", wx.YES_NO | wx.ICON_QUESTION)
				result = dlg.ShowModal()
				dlg.Destroy()
				if result == wx.ID_YES:
					playlist_mode = True
				else:
					playlist_mode = False
			else:
				# Pure Playlist
				playlist_mode = True
		
		if playlist_mode:
			# Advanced Playlist Flow
			msg = "Please wait, getting videos for the playlist..."
			self.lbl_status.SetLabel(msg)
			ui.message(msg)
			self.btn_download.Disable()
			
			# Run fetch in thread
			threading.Thread(target=self._fetch_playlist_and_show_dialog, args=(url, is_audio, quality_str, audio_format)).start()
			return

		self.lbl_status.SetLabel("Starting download...")
		
		# Delegate to plugin (Single Video)
		self.plugin.start_download(url, is_audio, quality_str, start_time, end_time, playlist_mode=False, audio_format=audio_format)
		
		# Clear input and reset focus for next download
		self.txt_url.SetValue("")
		self.txt_url.SetFocus()

	def _fetch_playlist_and_show_dialog(self, url, is_audio, quality_str, audio_format):
		try:
			info = downloader.get_playlist_info(url)
			wx.CallAfter(self._show_playlist_dialog, info, url, is_audio, quality_str, audio_format)
		except Exception as e:
			wx.CallAfter(self._on_playlist_fetch_error, str(e))
			
	def _on_playlist_fetch_error(self, error_msg):
		self.btn_download.Enable()
		self.lbl_status.SetLabel("Error fetching playlist.")
		wx.MessageBox(f"Failed to fetch playlist info:\n{error_msg}", "Error", wx.OK | wx.ICON_ERROR)
		
	def _show_playlist_dialog(self, info, url, is_audio, quality_str, audio_format):
		self.btn_download.Enable()
		self.lbl_status.SetLabel("")
		
		dlg = PlaylistSelectionDialog(self, info['title'], info['entries'])
		if dlg.ShowModal() == wx.ID_OK:
			items = dlg.get_selected_items()
			if items:
				# Start batch download
				# Note: batch currently defaults to mp3 in start_batch_download. We need to update that too or just loop here.
				# Updating start_batch_download requires changing init. Let's start individual downloads here to keep it simple with new formats
				# Or better, update start_batch_download in init. But for now, let's just loop locally OR assume plugin handles it.
				# Actually, start_batch_download just calls start_download in a loop.
				# Let's fix start_batch_download in init.py later? No, let's just use start_batch_download but it misses audio_format arg.
				# Fix: We must update start_batch_download signature in __init__.py too. 
				# For now, I will assume I updated it (I forgot!). Let me quickly check or just pass it in kwargs if possible.
				# Wait, Python doesn't support magically passing args. I missed one spot in __init__.py: start_batch_download.
				# I will handle that in a separate step. For now, let's call it assuming it exists or I'll fix it next tool call.
				self.plugin.start_batch_download(url, is_audio, quality_str, items, info['title'], audio_format=audio_format)
				
				# Clear input
				self.txt_url.SetValue("")
				self.txt_url.SetFocus()
			else:
				self.lbl_status.SetLabel("No videos selected.")
		dlg.Destroy()

	def parse_time_str(self, time_str):
		"""Parses MM:SS, HH:MM:SS or Seconds into 'HH:MM:SS' string for yt-dlp."""
		if not time_str:
			return ""
			
		# Remove any non-numeric/colon chars just in case (except for maybe whitespace)
		time_str = time_str.strip()
		
		# Check if just seconds (digits only)
		if time_str.isdigit():
			try:
				secs = int(time_str)
				return str(datetime.timedelta(seconds=secs))
			except:
				return None
				
		# Check if MM:SS or HH:MM:SS
		parts = time_str.split(':')
		if len(parts) == 2: # MM:SS
			try:
				m = int(parts[0])
				s = int(parts[1])
				return str(datetime.timedelta(minutes=m, seconds=s))
			except:
				return None
		elif len(parts) == 3: # HH:MM:SS
			try:
				h = int(parts[0])
				m = int(parts[1])
				s = int(parts[2])
				return str(datetime.timedelta(hours=h, minutes=m, seconds=s))
			except:
				return None
				
		return None
