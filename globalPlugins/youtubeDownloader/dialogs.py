import addonHandler
addonHandler.initTranslation()

import wx
import os
from . import downloader
import threading
import re
import config
import ui
import datetime

# Machine-readable format values. These are stored in config and passed to
# the downloader; the _() wrapped labels next to them are purely cosmetic
# and can be translated without breaking any logic.
FMT_MP3 = "mp3"
FMT_M4A = "m4a"
FMT_WAV = "wav"
FMT_FLAC = "flac"
FMT_OGG = "ogg"
FMT_MP4 = "mp4"

# Machine-readable quality values. "best" means the format's default best
# quality; numbers are kbps (audio) or vertical resolution (video).
Q_BEST = "best"

# Internal status markers (e.g. "Downloading", "Completed") double as state
# indicators shared between the plugin, the UI and saved state files, so they
# intentionally remain untranslated English-only substrings.

class PlaylistSelectionDialog(wx.Dialog):
	def __init__(self, parent, title, items):
		super().__init__(parent, title=_("Select Videos from %s") % title, size=(600, 400))
		self.items = items # [{'id':..., 'title':...}]
		
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)
		
		lbl = wx.StaticText(panel, label=_("Found %d videos. Select the items to download:") % len(items))
		vbox.Add(lbl, flag=wx.ALL, border=10)
		
		# Use ListCtrl instead of CheckListBox for better accessibility
		self.check_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_NO_HEADER)
		self.check_list.EnableCheckBoxes(True)
		# Set a very large width to prevent truncation tooltips which cause double speaking
		self.check_list.InsertColumn(0, _("Video Title"), width=2000)
		
		for i, item in enumerate(items):
			self.check_list.InsertItem(i, item['title'])
			# Default: Unchecked (User requested)
			self.check_list.CheckItem(i, False)
			
		vbox.Add(self.check_list, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=10)
		
		# Buttons for Select All / None
		hbox_sel = wx.BoxSizer(wx.HORIZONTAL)
		btn_all = wx.Button(panel, label=_("Select All"))
		btn_none = wx.Button(panel, label=_("Select None"))
		btn_all.Bind(wx.EVT_BUTTON, self.on_all)
		btn_none.Bind(wx.EVT_BUTTON, self.on_none)
		hbox_sel.Add(btn_all, flag=wx.RIGHT, border=5)
		hbox_sel.Add(btn_none)
		vbox.Add(hbox_sel, flag=wx.ALIGN_CENTER|wx.TOP|wx.BOTTOM, border=5)
		
		# Main Buttons
		hbox_btn = wx.BoxSizer(wx.HORIZONTAL)
		btn_ok = wx.Button(panel, id=wx.ID_OK, label=_("Download Selected"))
		btn_cancel = wx.Button(panel, id=wx.ID_CANCEL, label=_("Cancel"))
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
		super().__init__(parent, title=_("YouTube Downloader"), size=(600, 650))
		self.plugin = plugin_instance
		self.Center()
		self.Raise()
		self.SetFocus()
		
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)
		
		# URL Input
		lbl_url = wx.StaticText(panel, label=_("Enter YouTube video link or playlist link:"))
		self.txt_url = wx.TextCtrl(panel, value=url)
		self.txt_url.SetName(_("Enter YouTube video link or playlist link"))
		vbox.Add(lbl_url, flag=wx.LEFT|wx.TOP, border=10)
		vbox.Add(self.txt_url, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Format Selection: list of (value, translated label) pairs
		self.formats = [
			(FMT_MP3, _("MP3 (Audio)")),
			(FMT_M4A, _("M4A (Audio)")),
			(FMT_WAV, _("WAV (Audio)")),
			(FMT_FLAC, _("FLAC (Audio)")),
			(FMT_OGG, _("OGG (Audio)")),
			(FMT_MP4, _("MP4 (Video)")),
		]
		lbl_format = wx.StaticText(panel, label=_("Format:"))
		self.choice_format = wx.Choice(panel, choices=[label for _, label in self.formats])
		self.choice_format.SetName(_("Format"))
		
		# Set last used format from config
		last_format = config.conf["youtubeDownloader"]["lastFormat"]
		try:
			found = False
			for i, (value, label) in enumerate(self.formats):
				# Match either the machine value or a legacy stored label
				# (e.g. "MP3") from older versions, case-insensitively.
				if last_format == value or label.lower().startswith(last_format.lower()):
					self.choice_format.SetSelection(i)
					found = True
					break
			if not found:
				self.choice_format.SetSelection(0)
		except Exception:
			self.choice_format.SetSelection(0)
			
		self.choice_format.Bind(wx.EVT_CHOICE, self.on_format_change)
		vbox.Add(lbl_format, flag=wx.LEFT, border=10)
		vbox.Add(self.choice_format, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Quality Selection
		lbl_quality = wx.StaticText(panel, label=_("Quality:"))
		self.choice_quality = wx.Choice(panel, choices=[])
		self.choice_quality.SetName(_("Quality"))
		vbox.Add(lbl_quality, flag=wx.LEFT, border=10)
		vbox.Add(self.choice_quality, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Trimming (Start / End Time)
		sb_trim = wx.StaticBox(panel, label=_("Trimming (Optional)"))
		sbs_trim = wx.StaticBoxSizer(sb_trim, wx.VERTICAL)
		
		lbl_trim_help = wx.StaticText(panel, label=_("Format: MM:SS (e.g. 1:30) or seconds (e.g. 90)"))
		sbs_trim.Add(lbl_trim_help, flag=wx.LEFT|wx.TOP|wx.BOTTOM, border=5)
		
		hbox_trim_inputs = wx.BoxSizer(wx.HORIZONTAL)
		
		lbl_start = wx.StaticText(panel, label=_("Start:"))
		self.txt_start = wx.TextCtrl(panel, value="")
		self.txt_start.SetName(_("Start Time")) # Accessibility Label
		
		lbl_end = wx.StaticText(panel, label=_("End:"))
		self.txt_end = wx.TextCtrl(panel, value="")
		self.txt_end.SetName(_("End Time")) # Accessibility Label
		
		hbox_trim_inputs.Add(lbl_start, flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=5)
		hbox_trim_inputs.Add(self.txt_start, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=5)
		hbox_trim_inputs.Add(lbl_end, flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=5)
		hbox_trim_inputs.Add(self.txt_end, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=5)
		
		sbs_trim.Add(hbox_trim_inputs, flag=wx.EXPAND|wx.BOTTOM, border=5)
		
		vbox.Add(sbs_trim, flag=wx.EXPAND|wx.ALL, border=10)
		
		# Download Button
		self.btn_download = wx.Button(panel, label=_("Add to Download Queue"))
		self.btn_download.Bind(wx.EVT_BUTTON, self.on_download)
		vbox.Add(self.btn_download, flag=wx.ALIGN_CENTER|wx.ALL, border=10)
		
		# Active Downloads Label
		lbl_list = wx.StaticText(panel, label=_("Active Downloads:"))
		vbox.Add(lbl_list, flag=wx.LEFT, border=10)
		
		# ListCtrl for Downloads
		self.list_downloads = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL)
		self.list_downloads.SetName(_("Active Downloads List"))
		self.list_downloads.InsertColumn(0, _("Download Status"), width=550)
		self.list_downloads.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_list_selection)
		self.list_downloads.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_list_selection)
		
		vbox.Add(self.list_downloads, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
		
		# Contextual Buttons (Stop, Retry, Remove)
		hbox_controls = wx.BoxSizer(wx.HORIZONTAL)
		
		self.btn_retry = wx.Button(panel, label=_("Retry"))
		self.btn_retry.Bind(wx.EVT_BUTTON, self.on_retry)
		self.btn_retry.Enable(False)
		
		self.btn_remove = wx.Button(panel, label=_("Remove"))
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
		
		self.btn_close = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
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
			title = data['title']
			status = data.get('status', '')
			# Stored statuses of running items already start with the title
			# (e.g. "My Video - Downloading... 45%"); avoid showing it twice.
			if not status or status.startswith(title):
				display = status or title
			else:
				display = f"{title} - {status}"
			self.add_download_item(d_id, display)
			
		self.update_button_states()
			
	def add_download_item(self, d_id, display_text):
		self.list_downloads.InsertItem(self.list_downloads.GetItemCount(), display_text)
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
		
	def get_selected_format(self):
		"""Returns the machine-readable value of the selected format (e.g. 'mp3')."""
		return self.formats[self.choice_format.GetSelection()][0]
	
	def on_format_change(self, event):
		format_value = self.get_selected_format()
		
		# Quality options: list of (value, translated label) pairs
		qualities = []
		if format_value == FMT_MP4: # Video
			qualities = [
				(Q_BEST, _("Best (Default)")),
				("1080", _("1080p")),
				("720", _("720p")),
				("480", _("480p")),
				("360", _("360p")),
			]
		elif format_value in (FMT_WAV, FMT_FLAC): # Lossless Audio
			qualities = [(Q_BEST, _("Lossless (Default)"))]
		else: # Lossy Audio (MP3, M4A, OGG)
			qualities = [
				(Q_BEST, _("Best (Default)")),
				("320", _("320 kbps")),
				("256", _("256 kbps")),
				("192", _("192 kbps")),
				("128", _("128 kbps")),
			]
			
		self.qualities = qualities
		self.choice_quality.Set([label for _, label in qualities])
		self.choice_quality.SetSelection(0)
		
		# Try to restore last quality if possible. Older versions stored the
		# translated label; only exact machine-value matches are honoured.
		last_quality = config.conf["youtubeDownloader"]["lastQuality"]
		try:
			for i, (value, _) in enumerate(qualities):
				if value == last_quality:
					self.choice_quality.SetSelection(i)
					break
		except Exception:
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
			wx.MessageBox(_("Please provide a valid YouTube URL to proceed."), _("Input Required"), wx.OK | wx.ICON_WARNING)
			return
			
		if not self.is_valid_url(url):
			wx.MessageBox(_("The URL provided does not appear to be a valid YouTube link.\nPlease check the URL and try again."), _("Invalid URL"), wx.OK | wx.ICON_ERROR)
			return
		
		# Check for duplicates
		if self.plugin.is_url_downloading(url):
			wx.MessageBox(_("This URL is already being downloaded."), _("Duplicate Download"), wx.OK | wx.ICON_WARNING)
			return
			
		format_value = self.get_selected_format()
		is_audio = format_value != FMT_MP4
		audio_format = format_value if is_audio else FMT_MP3 # not used for video
		
		quality_value = self.qualities[self.choice_quality.GetSelection()][0]
		
		# Parse Time Input
		start_time_raw = self.txt_start.GetValue().strip()
		end_time_raw = self.txt_end.GetValue().strip()
		
		start_time = self.parse_time_str(start_time_raw)
		end_time = self.parse_time_str(end_time_raw)
		
		# Stop if parsing failed but input provided
		if start_time_raw and start_time is None:
			wx.MessageBox(_("Invalid start time format.\nPlease use MM:SS (e.g. 1:30) or seconds (e.g. 90)."), _("Invalid Input"), wx.OK | wx.ICON_ERROR)
			return
		if end_time_raw and end_time is None:
			wx.MessageBox(_("Invalid end time format.\nPlease use MM:SS (e.g. 1:30) or seconds (e.g. 90)."), _("Invalid Input"), wx.OK | wx.ICON_ERROR)
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
				except Exception:
					return 0
			
			s_sec = to_seconds(start_time)
			e_sec = to_seconds(end_time)
			
			if s_sec >= e_sec:
				wx.MessageBox(_("Start time must be less than end time."), _("Invalid Range"), wx.OK | wx.ICON_ERROR)
				return
				
		# Save user's selections for next time (machine-readable values only)
		config.conf["youtubeDownloader"]["lastFormat"] = format_value
		config.conf["youtubeDownloader"]["lastQuality"] = quality_value
		
		# Playlist Logic
		playlist_mode = False
		has_list = "list=" in url
		has_video = "v=" in url or "youtu.be/" in url
		
		if has_list:
			if has_video:
				# Ambiguous case: Video in Playlist
				dlg = wx.MessageDialog(self, _("This video is part of a playlist.\nDo you want to download the entire playlist?\n\nYes: download the whole playlist.\nNo: download only this video."), _("Playlist Detected"), wx.YES_NO | wx.ICON_QUESTION)
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
			msg = _("Please wait, getting videos for the playlist...")
			self.lbl_status.SetLabel(msg)
			ui.message(msg)
			self.btn_download.Disable()
			
			# Run fetch in thread
			threading.Thread(target=self._fetch_playlist_and_show_dialog, args=(url, is_audio, quality_value, audio_format)).start()
			return

		self.lbl_status.SetLabel(_("Starting download..."))
		
		# Delegate to plugin (Single Video)
		self.plugin.start_download(url, is_audio, quality_value, start_time, end_time, playlist_mode=False, audio_format=audio_format)
		
		# Clear input and reset focus for next download
		self.txt_url.SetValue("")
		self.txt_url.SetFocus()

	def _fetch_playlist_and_show_dialog(self, url, is_audio, quality_value, audio_format):
		try:
			info = downloader.get_playlist_info(url)
			wx.CallAfter(self._show_playlist_dialog, info, url, is_audio, quality_value, audio_format)
		except Exception as e:
			wx.CallAfter(self._on_playlist_fetch_error, str(e))
			
	def _on_playlist_fetch_error(self, error_msg):
		self.btn_download.Enable()
		self.lbl_status.SetLabel(_("Error fetching playlist."))
		wx.MessageBox(_("Failed to fetch playlist info:\n%s") % error_msg, _("Error"), wx.OK | wx.ICON_ERROR)
		
	def _show_playlist_dialog(self, info, url, is_audio, quality_value, audio_format):
		self.btn_download.Enable()
		self.lbl_status.SetLabel("")
		
		dlg = PlaylistSelectionDialog(self, info['title'], info['entries'])
		if dlg.ShowModal() == wx.ID_OK:
			items = dlg.get_selected_items()
			if items:
				# Start a batch download for the selected videos.
				self.plugin.start_batch_download(url, is_audio, quality_value, items, info['title'], audio_format=audio_format)

				# Clear input
				self.txt_url.SetValue("")
				self.txt_url.SetFocus()
			else:
				self.lbl_status.SetLabel(_("No videos selected."))
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
			except Exception:
				return None
				
		# Check if MM:SS or HH:MM:SS
		parts = time_str.split(':')
		if len(parts) == 2: # MM:SS
			try:
				m = int(parts[0])
				s = int(parts[1])
				return str(datetime.timedelta(minutes=m, seconds=s))
			except Exception:
				return None
		elif len(parts) == 3: # HH:MM:SS
			try:
				h = int(parts[0])
				m = int(parts[1])
				s = int(parts[2])
				return str(datetime.timedelta(hours=h, minutes=m, seconds=s))
			except Exception:
				return None
				
		return None
