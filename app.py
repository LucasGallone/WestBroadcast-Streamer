import os
import sys
import time
import json
import subprocess
import threading
import webbrowser
import queue
import tkinter as tk
import numpy as np
import sounddevice as sd
import gc
import urllib.request 
import re
import socket
import smtplib
import ssl
import unicodedata
from email.utils import formatdate
from email.mime.text import MIMEText
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, session, redirect, url_for, send_file, jsonify, Response
from flask_socketio import SocketIO
import logging
from datetime import datetime, timedelta

# --- 1. CONFIGURATION & LOGGING ---
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CONFIG_FILE = 'config.json'
SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK_SIZE = 1024 

BACKUP_DIR = 'backup-audio-files'
os.makedirs(BACKUP_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    'server': {'port': 8090, 'user': 'admin', 'password': 'admin', 'instance_name': '', 'op_user': 'operator', 'op_pass': 'operator', 'op_enabled': False, 'op_audio_access': False, 'op_fm_access': False, 'op_allow_restart': False, 'op_backup_access': False, 'hide_bg_on_login': False, 'peak_hold_enabled': False, 'peak_hold_time': 3},
    'audio': {'output_device': None, 'output_gain_db': 0.0, 'output_latency_ms': 1000},
    'sources': [
        {'name': 'Main Source', 'type': 'stream', 'url': 'http://stream.srg-ssr.ch/m/couleur3/mp3_128', 'rtp_uri': '', 'path': '', 'input_device': None, 'repeat': True, 'gain': 0.0, 'buffer_kb': 1024, 'meta_enabled': False, 'meta_path': 'C:\\streamer-main.txt', 'meta_only_played': False, 'meta_normalize': False, 'meta_uppercase': False, 'meta_rtplus': False, 'meta_rtplus_format': 'artist_title', 'alert_silent': False, 'alert_unreachable': False, 'tone_wave': 'sine', 'tone_freq': 1000},
        {'name': 'Backup Source 1', 'type': 'stream', 'url': '', 'rtp_uri': '', 'path': '', 'repeat': True, 'gain': 0.0, 'buffer_kb': 1024, 'meta_enabled': False, 'meta_path': 'C:\\streamer-backup1.txt', 'meta_only_played': False, 'meta_normalize': False, 'meta_uppercase': False, 'meta_rtplus': False, 'meta_rtplus_format': 'artist_title', 'alert_silent': False, 'alert_unreachable': False, 'tone_wave': 'sine', 'tone_freq': 1000},
        {'name': 'Backup Source 2', 'type': 'stream', 'url': '', 'rtp_uri': '', 'path': '', 'repeat': True, 'gain': 0.0, 'buffer_kb': 1024, 'meta_enabled': False, 'meta_path': 'C:\\streamer-backup2.txt', 'meta_only_played': False, 'meta_normalize': False, 'meta_uppercase': False, 'meta_rtplus': False, 'meta_rtplus_format': 'artist_title', 'alert_silent': False, 'alert_unreachable': False, 'tone_wave': 'sine', 'tone_freq': 1000}
    ],
    'settings': {
        'loss_threshold_db': -45.0,
        'loss_timeout_sec': 10.0,
        'recovery_threshold_db': -35.0,
        'recovery_timeout_sec': 5.0,
        'selection_mode': 'auto'
    },
    'fm': {
        'tilt': False,
        'tone_enabled': False,
        'tone_wave': 'sine',
        'tone_freq': 1000,
        'tone_gain': -10.0
    },
    'smtp': {
        'enabled': False,
        'host': '',
        'port': 587,
        'user': '',
        'pass': '',
        'from': '',
        'recipients': ['', '', '', ''],
        'spam_delay': 120,
        'trigger_delay': 30,
        'tls': False
    }
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            if 'instance_name' not in cfg['server']: cfg['server']['instance_name'] = ''
            
            # Operator account
            for key in['op_user', 'op_pass', 'op_enabled', 'op_audio_access', 'op_fm_access', 'op_allow_restart', 'op_backup_access', 'hide_bg_on_login', 'peak_hold_enabled', 'peak_hold_time']:
                if key not in cfg['server']:
                    cfg['server'][key] = DEFAULT_CONFIG['server'][key]
                    
            if 'fm' not in cfg: cfg['fm'] = DEFAULT_CONFIG['fm'].copy()
            if 'fm' not in cfg: cfg['fm'] = DEFAULT_CONFIG['fm'].copy()
            if 'playlists' not in cfg: cfg['playlists'] = {}
            if 'output_latency_ms' not in cfg['audio']: cfg['audio']['output_latency_ms'] = 1000
            if 'preemph' in cfg['fm']: del cfg['fm']['preemph']
            if 'smtp' not in cfg: cfg['smtp'] = DEFAULT_CONFIG['smtp'].copy()
            
            # SMTP recipients
            if 'recipients' not in cfg['smtp']:
                old_to = cfg['smtp'].get('to', '')
                cfg['smtp']['recipients'] = [old_to, '', '', '']
                if 'to' in cfg['smtp']: del cfg['smtp']['to']
            
            # Defaults for delays and tls
            if 'spam_delay' not in cfg['smtp']: cfg['smtp']['spam_delay'] = 120
            if 'trigger_delay' not in cfg['smtp']: cfg['smtp']['trigger_delay'] = 30
            if 'tls' not in cfg['smtp']: cfg['smtp']['tls'] = False

            for src in cfg['sources']:
                if 'type' not in src: src['type'] = 'stream'
                if 'path' not in src or src['path'] is None: src['path'] = ''
                if 'url' not in src or src['url'] is None: src['url'] = ''
                if 'backup_file' not in src: src['backup_file'] = ''
                if 'backup_playlist_name' not in src: src['backup_playlist_name'] = ''
                if 'backup_mode' not in src: src['backup_mode'] = 'single'
                if 'rtp_uri' not in src: src['rtp_uri'] = ''
                if 'repeat' not in src: src['repeat'] = True
                if 'buffer_kb' not in src: src['buffer_kb'] = 1024
                if 'meta_enabled' not in src: src['meta_enabled'] = False
                if 'meta_path' not in src: src['meta_path'] = ''
                if 'pre_buffer' in src: del src['pre_buffer']
                if 'tone_wave' not in src: src['tone_wave'] = 'sine'
                if 'tone_freq' not in src: src['tone_freq'] = 1000
                if 'input_device' not in src: src['input_device'] = None
                if 'meta_normalize' not in src: src['meta_normalize'] = False
                if 'meta_only_played' not in src: src['meta_only_played'] = False
                if 'meta_uppercase' not in src: src['meta_uppercase'] = False
                if 'meta_rtplus' not in src: src['meta_rtplus'] = False
                if 'meta_rtplus_format' not in src: src['meta_rtplus_format'] = 'artist_title'
                if 'meta_rtplus_separator' not in src: src['meta_rtplus_separator'] = ' - '
                if 'meta_max_64' not in src: src['meta_max_64'] = False
                if 'alert_silent' not in src: src['alert_silent'] = False
                if 'alert_unreachable' not in src: src['alert_unreachable'] = False

            for k, v in DEFAULT_CONFIG['settings'].items():
                if k not in cfg['settings']: cfg['settings'][k] = v
            return cfg
    except: return DEFAULT_CONFIG

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=4)
    except: pass

CONFIG = load_config()

# --- INTERNAL LOGS MANAGEMENT ---
INTERNAL_LOGS = []
LOGIN_ATTEMPTS = {}

def add_internal_log(event, level="INFO"):
    try:
        ip = request.remote_addr if request else "SYSTEM"
    except:
        ip = "SYSTEM"
        
    log_entry = {
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "ip": ip,
        "event": event,
        "level": level
    }
    INTERNAL_LOGS.append(log_entry)
    # Keep the last 1000 logs
    if len(INTERNAL_LOGS) > 1000:
        INTERNAL_LOGS.pop(0)
    print(f"[{level}] {event}")

# --- 2. FLASK INIT & SOCKETIO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')

# --- 3. HELPERS ---
def get_audio_files_info():
    files = []
    if not os.path.exists(BACKUP_DIR): return files
    for f in os.listdir(BACKUP_DIR):
        p = os.path.abspath(os.path.join(BACKUP_DIR, f))
        if os.path.isfile(p):
            # Listing files names without calling an external tool
            files.append({'name': f})
    return files

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def normalize_text_content(text):
    if not text: return ""
    # NFD normalization in order to separate the characters with accents
    normalized = unicodedata.normalize('NFD', text)
    # Filtering the non-combinant character (remove the accents) and return the text as is (No forced capital letters)
    return "".join(c for c in normalized if not unicodedata.combining(c))

def extract_stream_title(url):
    try:
        # Forcing an unverified SSL context to ensure the stream can be read on any version of Windows
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={'Icy-MetaData': '1', 'User-Agent': 'VLC/3.0.0'})
        with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
            metaint_header = response.headers.get('icy-metaint')
            if not metaint_header: return None
            metaint = int(metaint_header)
            # Read 5 consecutive blocks to ensure the title isn't missed during a change
            for _ in range(5):
                response.read(metaint)
                length_byte = response.read(1)
                if not length_byte: break
                length = ord(length_byte) * 16
                if length > 0:
                    meta_data = response.read(length)
                meta_str = meta_data.decode('utf-8', errors='ignore').rstrip('\0')
                m = re.search(r"StreamTitle='(.*?)';", meta_str)
                if m and m.group(1).strip(): 
                    return m.group(1).strip()
    except: pass
    return None

def send_smtp_alert(subject, body):
    cfg_smtp = CONFIG['smtp']
    if not cfg_smtp['enabled'] or not cfg_smtp['host']:
        return

    # Filtering the empty recipients fields
    recipients = [r for r in cfg_smtp['recipients'] if r.strip()]
    if not recipients:
        return

    try:
        msg = MIMEText(body)
        instance = CONFIG['server']['instance_name']
        prefix = f"WestBroadcast Streamer - {instance}" if instance else "WestBroadcast Streamer"
        msg['Subject'] = f"[{prefix}] {subject}"
        msg['From'] = cfg_smtp['from']
        msg['To'] = ", ".join(recipients)
        msg['Date'] = formatdate(localtime=True)

        context = ssl.create_default_context()

        if cfg_smtp.get('tls'):
            # Implicit SSL configuration
            server = smtplib.SMTP_SSL(cfg_smtp['host'], cfg_smtp['port'], context=context, timeout=15)
        else:
            # Explicit STARTTLS configuration
            server = smtplib.SMTP(cfg_smtp['host'], cfg_smtp['port'], timeout=15)
            server.ehlo()  # Initial identification
            server.starttls(context=context)  # Securing the line
            server.ehlo()  # New identification after securing

        if cfg_smtp['user'] and cfg_smtp['pass']:
            server.login(cfg_smtp['user'], cfg_smtp['pass'])
            
        server.send_message(msg)
        server.quit()
        
        add_internal_log(f"Email sent: {subject}", "INFO")
    except Exception as e:
        add_internal_log(f"SMTP Error: {str(e)}", "ERROR")

# --- 4. AUDIO CLASSES ---
class SourceChannel:
    def __init__(self, index):
        self.index = index
        self.queue = queue.Queue(maxsize=10000) 
        self.running = False
        self.play_start_time = 0
        self.process = None
        self.thread = None
        self.last_vu = {'l': -90.0, 'r': -90.0}
        self.status_text = "STOPPED"
        self.status_color = "#999"
        self.codec_info = ""
        self.next_phantom_read = 0
        self.last_data_time = 0 
        self.is_reconnecting = False
        self.last_vu = {'l': -60.0, 'r': -60.0}

    def start(self):
        if self.running: return
        self.running = True
        self.is_reconnecting = False # Reset
        self.playlist_idx = 0 # Position initialization
        
        src = CONFIG['sources'][self.index]
        buf_kb = src.get('buffer_kb', 1024)
        q_size = max(100, int(buf_kb * 1024 / (BLOCK_SIZE * CHANNELS * 4)))
        self.queue = queue.Queue(maxsize=q_size)
        
        # PROBE LOOP
        if (src['type'] == 'stream' or src['type'] == 'rtp') and (src['url'] or src['rtp_uri']):
            threading.Thread(target=self._probe_loop, daemon=True).start()
        elif src['type'] == 'file' and src['path']:
            threading.Thread(target=self._probe_loop, daemon=True).start()
        elif src['type'] == 'backup_dir' and src.get('backup_file'):
            threading.Thread(target=self._probe_loop, daemon=True).start()

        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.process:
            try: self.process.kill()
            except: pass
        if self.thread:
            self.thread.join(timeout=0.5)
        with self.queue.mutex: self.queue.queue.clear()
        self.status_text = "STOPPED"
        self.status_color = "#999"
        self.codec_info = ""
        self.is_reconnecting = False

    def _probe_loop(self):
        while self.running:
            if not self.codec_info and self.status_text == "PLAYING":
                src = CONFIG['sources'][self.index]
                target = ""
                
                # IP Stream: Try fast path via HTTP Headers
                if src['type'] == 'stream' and src['url']:
                    target = src['url']
                    try:
                        req = urllib.request.Request(src['url'], headers={'Icy-MetaData': '1', 'User-Agent': 'VLC/3.0.0'})
                        with urllib.request.urlopen(req, timeout=3) as response:
                            headers = response.headers
                            c_type = headers.get('Content-Type', '').split(';')[0].replace('audio/', '').upper()
                            if 'MPEG' in c_type: c_type = 'MP3'
                            br = headers.get('icy-br') or headers.get('ice-bitrate')
                            info_parts = []
                            if c_type and len(c_type) < 12: info_parts.append(c_type)
                            if br: info_parts.append(f"{br} Kbps")
                            if info_parts: self.codec_info = " - ".join(info_parts)
                    except: pass

                # Fallback to ffprobe (reliable) if fast path failed or missing bitrate
                if not self.codec_info or (src['type'] == 'stream' and 'Kbps' not in self.codec_info):
                    if src['type'] == 'rtp': target = src['rtp_uri']
                    elif src['type'] == 'file': target = src['path']
                    elif src['type'] == 'backup_dir':
                        if src.get('backup_mode', 'single') == 'single' and src.get('backup_file'):
                            target = os.path.join(BACKUP_DIR, src['backup_file'])
                        elif src.get('backup_mode', 'single') == 'playlist' and src.get('backup_playlist_name'):
                            playlist = CONFIG.get('playlists', {}).get(src['backup_playlist_name'], [])
                            p_idx = getattr(self, 'playlist_idx', 0)
                            if p_idx < len(playlist): target = os.path.join(BACKUP_DIR, playlist[p_idx])
                    elif src['type'] == 'stream': target = src['url']
                    
                    if target:
                        try:
                            # Detecting the absolute path of the application folder
                            if getattr(sys, 'frozen', False):
                                base_path = os.path.dirname(sys.executable)
                            else:
                                base_path = os.path.dirname(os.path.abspath(__file__))
                            
                            exe_name = 'ffprobe.exe' if sys.platform == 'win32' else 'ffprobe'
                            ffprobe_path = os.path.join(base_path, exe_name)

                            cmd = [ffprobe_path, '-v', 'quiet', '-print_format', 'json', '-show_streams', '-show_format',
                                   '-analyzeduration', '5000000', '-probesize', '5000000', '-user_agent', 'VLC/3.0.0', target]
                            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                            out, _ = proc.communicate(timeout=10)
                            data = json.loads(out)
                            c_name, b_rate = "", 0
                            for s in data.get('streams', []):
                                if s['codec_type'] == 'audio':
                                    c_name = s.get('codec_name', 'unk').upper()
                                    b_rate = int(s.get('bit_rate', 0))
                                    break
                            if b_rate == 0: b_rate = int(data.get('format', {}).get('bit_rate', 0))
                            if c_name:
                                self.codec_info = f"{c_name} - {b_rate // 1000} Kbps" if b_rate > 0 else c_name
                        except: pass
                
                # Safety: stop re-probing even if everything fails
                if not self.codec_info and self.status_text == "PLAYING":
                    self.codec_info = "IP STREAM" if src['type'] == 'stream' else "UNKNOWN"
            
            time.sleep(5)   

    def get_status_display(self, is_active, is_silence_detected):
        # 1ST PRIORITY: Unreachable stream case
        if self.status_text == "UNREACHABLE":
            return "UNREACHABLE", "#8B0000"

        # 2ND PRIORITY: Buffering status case
        if self.is_reconnecting or self.status_text == "BUFFERING":
            return "BUFFERING...", "#e67e22"

        # 3RD PRIORITY: Data timeout during playback
        if self.running and self.status_text == "PLAYING" and (time.time() - self.last_data_time > 5.0):
             return "UNREACHABLE", "#8B0000"

        src = CONFIG['sources'][self.index]
        if src['type'] == 'stream' and not src['url']: return "NOT CONFIGURED", "#999"
        if src['type'] == 'rtp' and not src['rtp_uri']: return "NOT CONFIGURED", "#999"
        if src['type'] == 'device' and src.get('input_device') is None: return "NOT CONFIGURED", "#999"
        if src['type'] == 'file' and not src['path']: return "NOT CONFIGURED", "#999"
        if src['type'] == 'backup_dir':
            if src.get('backup_mode', 'single') == 'single' and not src.get('backup_file'): return "NOT CONFIGURED", "#999"
            if src.get('backup_mode', 'single') == 'playlist' and not src.get('backup_playlist_name'): return "NOT CONFIGURED", "#999"
        
        if src['type'] == 'file' and src['path'] and not os.path.exists(src['path']): return "FILE NOT FOUND", "#b00"
        if src['type'] == 'backup_dir':
            if src.get('backup_mode', 'single') == 'single':
                if src.get('backup_file') and not os.path.exists(os.path.join(BACKUP_DIR, src['backup_file'])): return "FILE NOT FOUND", "#b00"
            else:
                p_idx = getattr(self, 'playlist_idx', 0)
                playlist = CONFIG.get('playlists', {}).get(src.get('backup_playlist_name', ''), [])
                if playlist and p_idx < len(playlist) and not os.path.exists(os.path.join(BACKUP_DIR, playlist[p_idx])): return "FILE NOT FOUND", "#b00"

        if self.running and self.status_text == "UNREACHABLE":
             return "UNREACHABLE", "#8B0000"

        # Active management
        if is_active:
            if self.status_text == "BUFFERING": return "BUFFERING...", "#e67e22"
            # Prevent "SILENT" status display for 5 seconds if playback has just started
            if is_silence_detected and (time.time() - self.play_start_time > 5.0): 
                return "SILENT", "#8B0000"
            if self.status_text == "PLAYING": return "PLAYING", "#006400"
            return "UNREACHABLE", "#8B0000"

        # Inactive management (for backups when they're not being called upon)
        if self.running and self.status_text == "PLAYING":
            if is_silence_detected: return "SILENT", "#8B0000" # Display SILENT status even if the source is not played
            return "READY TO PLAY", "#666"
        
        if self.status_text == "UNREACHABLE": return "UNREACHABLE", "#8B0000"
        return "READY TO PLAY", "#666"

    def _read_loop(self):
        while self.running:
            self.last_data_time = time.time()
            # Flag reset at every attempt
            self.is_reconnecting = False
            
            src = CONFIG['sources'][self.index]
            user_buffer_kb = src.get('buffer_kb', 1024)
            ffmpeg_net_buf_bytes = str(max(user_buffer_kb * 1024, 4096))

            # --- FM Processing Filters ---
            af_filters = []
            if CONFIG['fm'].get('tilt'):
                af_filters.append("allpass=f=200:width_type=h:width=100")
                af_filters.append("allpass=f=400:width_type=h:width=100")
            
            filter_arg = []
            if af_filters:
                filter_arg = ['-af', ",".join(af_filters)]

            cmd = []
            valid = False
            rw_timeout = '15000000' 

            if src['type'] == 'device':
                if src.get('input_device') is not None:
                    self.status_text = "PLAYING"
                    self.play_start_time = time.time()
                    self.last_data_time = time.time()
                    self.codec_info = "INPUT DEVICE"
                    
                    def in_callback(indata, frames, time_info, status):
                        if not self.running or engine.channels[self.index] is not self: return
                        if engine.current_source_idx == self.index:
                            if not self.queue.full(): self.queue.put(indata.copy())
                        else:
                            # Calculation of the VU meter data in background
                            gain_in = 10 ** (CONFIG['sources'][self.index]['gain'] / 20.0)
                            pk = np.max(np.abs(indata)) * gain_in
                            db = float(20 * np.log10(pk) if pk > 0.001 else -60.0)
                            engine.vu_data['sources'][self.index]['l'] = db
                            engine.vu_data['sources'][self.index]['r'] = db

                    try:
                        with sd.InputStream(device=int(src['input_device']), samplerate=SAMPLE_RATE, channels=CHANNELS, callback=in_callback, blocksize=BLOCK_SIZE):
                            while self.running: 
                                self.last_data_time = time.time()
                                time.sleep(0.1)
                    except: self.status_text = "UNREACHABLE"
                    
                    self.is_reconnecting = True
                    time.sleep(5)
                    continue
                else:
                    self.status_text = "NO CONFIG"
                    time.sleep(1)
                    continue

            # Detecting the absolute path for FFmpeg
            if getattr(sys, 'frozen', False): base_path = os.path.dirname(sys.executable)
            else: base_path = os.path.dirname(os.path.abspath(__file__))
            ffmpeg_exe = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
            ffmpeg_path = os.path.join(base_path, ffmpeg_exe)

            if src['type'] == 'file':
                if src['path'] and os.path.exists(src['path']):
                    valid = True
                    cmd =[ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-stream_loop', '-1', '-re', '-i', src['path']] + filter_arg
                else:
                    self.status_text = "FILE ERROR"
            elif src['type'] == 'backup_dir':
                if src.get('backup_mode', 'single') == 'single':
                    bpath = os.path.join(BACKUP_DIR, src.get('backup_file', ''))
                    if src.get('backup_file') and os.path.exists(bpath):
                        valid = True
                        cmd =[ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-stream_loop', '-1', '-re', '-i', bpath] + filter_arg
                    else:
                        self.status_text = "FILE ERROR"
                else:
                    playlist = CONFIG.get('playlists', {}).get(src.get('backup_playlist_name', ''), [])
                    if playlist:
                        if getattr(self, 'playlist_idx', 0) >= len(playlist):
                            self.playlist_idx = 0
                        p_idx = self.playlist_idx
                        bpath = os.path.join(BACKUP_DIR, playlist[p_idx])
                        if os.path.exists(bpath):
                            valid = True
                            cmd =[ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-re', '-i', bpath] + filter_arg
                        else:
                            self.status_text = "FILE ERROR"
                            self.playlist_idx += 1
                    else:
                        self.status_text = "FILE ERROR"
            elif src['type'] == 'rtp':
                if src['rtp_uri']:
                    valid = True
                    cmd = [ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-timeout', rw_timeout, '-i', src['rtp_uri']] + filter_arg
                else:
                    self.status_text = "NO CONFIG"
            elif src['type'] == 'tone':
                valid = True
                freq = src.get('tone_freq', 1000)
                wave = src.get('tone_wave', 'sine')
                expr = ""
                if wave == 'sine': expr = f"sin(2*PI*t*{freq})"
                else: expr = f"if(gt(sin(2*PI*t*{freq}),0),1,-1)"
                lavfi_str = f"aevalsrc='{expr}|{expr}:s={SAMPLE_RATE}'"
                cmd = [ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-re', '-f', 'lavfi', '-i', lavfi_str] + filter_arg
            else: # stream
                if src['url']:
                    valid = True
                    cmd = [ffmpeg_path, '-re', '-hide_banner', '-loglevel', 'error', 
                           '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
                           '-rw_timeout', rw_timeout,
                           '-i', src['url']] + filter_arg
                else:
                    self.status_text = "NO CONFIG"

            if not valid:
                time.sleep(1)
                continue

            cmd.extend(['-f', 's16le', '-ac', str(CHANNELS), '-ar', str(SAMPLE_RATE), '-acodec', 'pcm_s16le', 'pipe:1'])
            self.status_text = "BUFFERING"

            try:
                if sys.platform == "win32":
                    self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                else:
                    self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                
                time.sleep(0.5)
                if self.process.poll() is not None:
                    raise Exception("Process died immediately")
                
                self.status_text = "PLAYING"
                self.play_start_time = time.time()
                self.last_data_time = time.time()

                while self.running:
                    raw = self.process.stdout.read(BLOCK_SIZE * 2 * CHANNELS)
                    if not raw:
                        if self.process.poll() is not None: break
                        time.sleep(0.01)
                        continue
                    
                    self.last_data_time = time.time()
                    
                    int16_data = np.frombuffer(raw, dtype=np.int16).reshape(-1, CHANNELS)
                    float_data = int16_data.astype(np.float32) / 32768.0
                    
                    if not self.queue.full():
                        self.queue.put(float_data)
                    else:
                        time.sleep(0.005) 

            except Exception as e:
                self.status_text = "UNREACHABLE"
                # On ne met pas de break ici pour laisser le finally gérer la reconnexion
            finally:
                is_normal_eof = False
                if self.process:
                    if self.process.poll() == 0: is_normal_eof = True
                    try: self.process.kill()
                    except: pass
            
            # SORTI DU BLOC FINALLY : Enchaînement de la playlist
            if self.running and src['type'] == 'backup_dir' and src.get('backup_mode', 'single') == 'playlist' and valid and is_normal_eof:
                self.playlist_idx = getattr(self, 'playlist_idx', 0) + 1
                time.sleep(0.1)
                continue
                
                self.status_text = "UNREACHABLE"
                self.is_reconnecting = True
                
                # 10 seconds timeout before the next reconnection attempt (if the stream has UNREACHABLE status)
                for _ in range(100):
                    if not self.running: break
                    time.sleep(0.1)


class BroadcastEngine:
    def __init__(self):
        self.start_time = time.time()
        self.running = True
        self.run_id = time.time()
        self.stream = None
        self.current_source_idx = 0
        self.tone_phase = 0
        
        self.vu_data = {
            'out_l': -60.0, 'out_r': -60.0,
            'sources': [{'l': -60.0, 'r': -60.0} for _ in range(3)]
        }
        
        self.current_metadata_title = ""
        self.silence_start = 0
        self.is_silence = False
        self.manual_log_triggered = False
        self.recovery_timers = {0: 0, 1: 0, 2: 0}
        self.is_recovering = {0: False, 1: False, 2: False}
        
        # SMTP alerts tracking
        self.last_notified_status = [None, None, None]
        # SMTP timers
        self.smtp_last_sent = [0, 0, 0] # Timestamp for the most recent sending
        self.smtp_trigger_start = [0, 0, 0] # Delay start for the trigger
        self.smtp_recovery_start = [0, 0, 0] # Délai before sending a recovery notification email
        self.smtp_active_error_type = [None, None, None] # Current error tracking
        self.smtp_alert_sent_for_current_fault = [False, False, False]
        
        self.channels = [SourceChannel(i) for i in range(3)]
        self.analysis_active = False
        
        self.t_monitor = threading.Thread(target=self._monitor_loop, args=(self.run_id,), daemon=True)
        self.t_monitor.start()
        
        self.t_meta = threading.Thread(target=self._meta_loop, args=(self.run_id,), daemon=True)
        self.t_meta.start()
        
        self.start_audio_stream()
        if '--is-restart' in sys.argv:
            add_internal_log("Audio engine restarted.", "SYSTEM")
        else:
            add_internal_log("Audio engine started.", "SYSTEM")

    def get_uptime_string(self):
        delta = timedelta(seconds=int(time.time() - self.start_time))
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"

    def get_source_status(self, idx):
        is_active = (idx == self.current_source_idx)
        ch = self.channels[idx]

        # If the process is technically down, we don't count the downtime
        if ch.status_text == "UNREACHABLE":
            return ch.get_status_display(is_active, False)

        # Silence calculation only if the source is technically active
        vu_l = self.vu_data['sources'][idx]['l']
        vu_r = self.vu_data['sources'][idx]['r']
        threshold = CONFIG['settings']['loss_threshold_db']
        is_silent_now = (max(vu_l, vu_r) < threshold)
        
        return ch.get_status_display(is_active, is_silent_now)

    def get_codecs(self):
        return [ch.codec_info for ch in self.channels]

    def start_audio_stream(self):
        try:
            device = CONFIG['audio']['output_device']
            if device is not None: device = int(device)
            else: device = sd.default.device[1]

            lat_sec = float(CONFIG['audio'].get('output_latency_ms', 1000)) / 1000.0

            self.stream = sd.OutputStream(
                device=device, samplerate=SAMPLE_RATE, channels=CHANNELS,
                dtype='float32', blocksize=BLOCK_SIZE, latency=lat_sec, callback=self._audio_callback
            )
            self.stream.start()
        except Exception as e:
            add_internal_log(f"Audio Output Error: {str(e)}", "ERROR")
            logging.error(f"Audio Output Error: {e}")

    def restart_engine(self):
        # ID change to invalidate and force the termination of old threads
        self.run_id = time.time() 
        
        for ch in self.channels: ch.stop()
        if self.stream: 
            try: self.stream.stop(); self.stream.close()
            except: pass
        
        gc.collect()
        self.channels = [SourceChannel(i) for i in range(3)]
        self.current_source_idx = 0 
        
        # Restarting new threads
        self.t_monitor = threading.Thread(target=self._monitor_loop, args=(self.run_id,), daemon=True)
        self.t_monitor.start()
        
        self.t_meta = threading.Thread(target=self._meta_loop, args=(self.run_id,), daemon=True)
        self.t_meta.start()
        
        self.start_audio_stream()
        add_internal_log("Audio engine restarted.", "SYSTEM")

    def _meta_loop(self, current_run_id):
        last_titles =["", "", ""]
        raw_titles = ["", "", ""] # Saves the raw "current song" metadata to prevent songs titles from being deleted 
        while self.running and self.run_id == current_run_id:
            for i in range(3):
                src = CONFIG['sources'][i]
                title = ""
                
                # Check stream URL first
                if src['type'] == 'stream' and src['url']:
                    try:
                        extracted = extract_stream_title(src['url'])
                    except:
                        extracted = None
                    if extracted is not None:
                        title = extracted
                    else:
                        title = raw_titles[i] # Keeps the previous song name in case of a network failure
                elif src['type'] == 'file' and src['path']:
                    title = os.path.basename(src['path'])
                    raw_titles[i] = title
                elif src['type'] == 'backup_dir':
                    if src.get('backup_mode', 'single') == 'single' and src.get('backup_file'):
                        title = src['backup_file']
                        raw_titles[i] = title
                    elif src.get('backup_mode', 'single') == 'playlist' and src.get('backup_playlist_name'):
                        playlist = CONFIG.get('playlists', {}).get(src['backup_playlist_name'], [])
                        p_idx = getattr(self.channels[i], 'playlist_idx', 0)
                        if p_idx < len(playlist):
                            title = playlist[p_idx]
                            raw_titles[i] = title
                elif src['type'] == 'tone':
                    title = "Test Tone Generator"
                    raw_titles[i] = title
                elif src['type'] == 'device':
                    title = "Audio Input Device"
                    raw_titles[i] = title
                else:
                    raw_titles[i] = ""
                
                if i == self.current_source_idx:
                    self.current_metadata_title = title

                if src['meta_enabled'] and src['meta_path'] and title:
                    # Check "Export only when played" option
                    if src.get('meta_only_played') and i != self.current_source_idx:
                        continue

                    # Normalization logic
                    final_title = title
                    if src.get('meta_normalize'):
                        final_title = normalize_text_content(title)
                        
                    # Uppercase logic (applied AFTER the characters normalization / accents removal)
                    if src.get('meta_uppercase'):
                        final_title = final_title.upper()

                    # Apply a strict limit on the output TXT to 64 characters for the Radiotext function (RDS)
                    if src.get('meta_max_64') and len(final_title) > 64:
                        final_title = final_title[:61] + "..."

                    # Radiotext+ / StereoTool formatting
                    if src.get('meta_rtplus'):
                        # Special characters must be escaped in Stereo Tool (even if there is no artist or title)
                        final_title = final_title.replace(':', '\\:').replace('/', '\\/')
                        
                        separator = src.get('meta_rtplus_separator', ' - ')
                        if separator in final_title:
                            parts = final_title.split(separator, 1)
                            if src.get('meta_rtplus_format') == 'title_artist':
                                final_title = f"\\+Ti{parts[0]}\\-{separator}\\+Ar{parts[1]}\\-"
                            else:
                                final_title = f"\\+Ar{parts[0]}\\-{separator}\\+Ti{parts[1]}\\-"

                    if final_title != last_titles[i]:
                        last_titles[i] = final_title
                        try:
                            with open(src['meta_path'], 'w', encoding='utf-8-sig') as f:
                                f.write(final_title)
                        except: pass
            
            time.sleep(10)

    def _monitor_loop(self, current_run_id):
        block_duration = BLOCK_SIZE / SAMPLE_RATE
        
        while self.running and self.run_id == current_run_id:
            now = time.time()
            for i in range(3):
                src_cfg = CONFIG['sources'][i]
                ch = self.channels[i]
                
                # 1. Start / Stop managmeent
                should_run = False
                if src_cfg['type'] == 'stream': should_run = True
                elif src_cfg['type'] == 'rtp': should_run = True 
                elif src_cfg['type'] == 'tone': should_run = True
                elif src_cfg['type'] == 'device': should_run = True
                elif src_cfg['type'] in ['file', 'backup_dir']: 
                     # Only run file if it IS the current source
                     if self.current_source_idx == i: should_run = True
                
                if should_run:
                    if src_cfg['type'] == 'file' and not src_cfg['path']: should_run = False
                    if src_cfg['type'] == 'backup_dir':
                        if src_cfg.get('backup_mode', 'single') == 'single' and not src_cfg.get('backup_file'): should_run = False
                        if src_cfg.get('backup_mode', 'single') == 'playlist' and not src_cfg.get('backup_playlist_name'): should_run = False
                    if src_cfg['type'] == 'stream' and not src_cfg['url']: should_run = False
                    if src_cfg['type'] == 'rtp' and not src_cfg['rtp_uri']: should_run = False
                    if src_cfg['type'] == 'device' and src_cfg.get('input_device') is None: should_run = False

                if should_run and not ch.running: ch.start()
                elif not should_run and ch.running: ch.stop()

                # 2. Technical timeout (FFmpeg failure scenario)
                if ch.running and ch.status_text == "PLAYING" and (time.time() - ch.last_data_time > 5.0):
                     if ch.process:
                         try: ch.process.kill()
                         except: pass
                     ch.status_text = "UNREACHABLE"

                # 3. VU-Meters update
                if not ch.running or ch.status_text == "UNREACHABLE":
                    self.vu_data['sources'][i]['l'] = -60.0
                    self.vu_data['sources'][i]['r'] = -60.0
                elif i != self.current_source_idx and ch.running:
                    # Backup sources playback
                    try:
                        pre_buf = 2.0 
                        target_qsize = int(pre_buf * (SAMPLE_RATE / BLOCK_SIZE))
                        if target_qsize < 1: target_qsize = 1
                        q_sz = ch.queue.qsize()
                        
                        if q_sz > target_qsize and now >= ch.next_phantom_read:
                            data = ch.queue.get_nowait()
                            
                            if ch.next_phantom_read == 0: ch.next_phantom_read = now
                            ch.next_phantom_read += block_duration
                            if ch.next_phantom_read < now: ch.next_phantom_read = now + block_duration

                            gain_in = 10 ** (src_cfg['gain'] / 20.0)
                            data = data * gain_in
                            
                            pk_l = np.max(np.abs(data[:, 0])) if len(data) > 0 else 0
                            pk_r = np.max(np.abs(data[:, 1])) if len(data) > 0 else 0
                            self.vu_data['sources'][i]['l'] = float(20 * np.log10(pk_l) if pk_l > 0.00001 else -60.0)
                            self.vu_data['sources'][i]['r'] = float(20 * np.log10(pk_r) if pk_r > 0.00001 else -60.0)
                    except: pass

                # 4. SMTP Alerts logic
                current_status_str, _ = self.get_source_status(i)
                status_key = current_status_str
                
                # Treating the BUFFERING status as a potential stream failure
                if status_key == "BUFFERING..." or ch.status_text == "UNREACHABLE":
                    status_key = "UNREACHABLE"
                
                is_problem_state = False
                if status_key == "SILENT" and src_cfg['alert_silent']: is_problem_state = True
                if status_key == "UNREACHABLE" and src_cfg['alert_unreachable']: is_problem_state = True
                
                smtp_settings = CONFIG['smtp']
                trigger_wait = float(smtp_settings.get('trigger_delay', 30))
                spam_wait_sec = float(smtp_settings.get('spam_delay', 120)) * 60.0

                if is_problem_state:
                    # Chronometer reset in case of a status update (e.g. UNREACHABLE > SILENT)
                    if status_key != self.smtp_active_error_type[i]:
                        self.smtp_trigger_start[i] = now
                        self.smtp_active_error_type[i] = status_key

                    elapsed_trigger = now - self.smtp_trigger_start[i]
                    
                    if elapsed_trigger >= trigger_wait:
                        # Send the email only if the lock is open AND the anti-spam delay has expired
                        if not self.smtp_alert_sent_for_current_fault[i] and (now - self.smtp_last_sent[i]) > spam_wait_sec:
                            msg_subject = f"Alert: {src_cfg['name'].upper()} is {status_key}"
                            
                            mode = CONFIG['settings'].get('selection_mode', 'auto')
                            mode_warn = "\n\nReminder: Automatic mode is disabled. The decoder won't switch to any backup source." if mode != 'auto' else ""
                            
                            msg_body = f"{src_cfg['name'].upper()} is currently {status_key}!\nAnomaly detected on: {datetime.now().strftime('%d/%m/%Y at %H:%M:%S')}\n\nYou will be notified as soon as the source is recovered.\n\n{mode_warn}"
                            send_smtp_alert(msg_subject, msg_body)
                            
                            self.last_notified_status[i] = status_key
                            self.smtp_last_sent[i] = now
                            self.smtp_alert_sent_for_current_fault[i] = True
                else:
                    self.smtp_trigger_start[i] = 0 
                    self.smtp_active_error_type[i] = None # Error type status reset
                    
                    # Audio recovery logic
                    if self.last_notified_status[i] in ["SILENT", "UNREACHABLE"] and status_key in ["PLAYING", "READY TO PLAY"]:
                        if self.smtp_recovery_start[i] == 0:
                            self.smtp_recovery_start[i] = now
                        
                        elapsed_recovery = now - self.smtp_recovery_start[i]
                        recovery_wait = float(CONFIG['settings'].get('recovery_timeout_sec', 5.0))

                        if elapsed_recovery >= recovery_wait:
                            msg_subject = f"Recovery Notification for {src_cfg['name'].upper()}"
                            
                            mode = CONFIG['settings'].get('selection_mode', 'auto')
                            mode_warn = "\n\nReminder: Automatic mode is disabled." if mode != 'auto' else ""
                            
                            msg_body = f"{src_cfg['name'].upper()} is working properly again.\nNormal broadcasting has resumed.\n\nNotification sent on: {datetime.now().strftime('%d/%m/%Y at %H:%M:%S')}\n\n{mode_warn}"
                            send_smtp_alert(msg_subject, msg_body)
                            
                            self.last_notified_status[i] = status_key
                            self.smtp_recovery_start[i] = 0
                            self.smtp_alert_sent_for_current_fault[i] = False # Unlocking for the next event
                    else:
                        self.smtp_recovery_start[i] = 0
            
            # 5. Failover logic
            mode = CONFIG['settings'].get('selection_mode', 'auto')
            
            if mode == 'auto':
                active_ch = self.channels[self.current_source_idx]
                current_max_db = max(self.vu_data['sources'][self.current_source_idx]['l'], 
                                     self.vu_data['sources'][self.current_source_idx]['r'])
                
                is_active_unreachable = (active_ch.status_text == "UNREACHABLE")
                
                if current_max_db < CONFIG['settings'].get('loss_threshold_db', -60.0) or is_active_unreachable:
                    if not self.is_silence:
                        self.silence_start = time.time()
                        self.is_silence = True
                    
                    timeout = 5.0 if is_active_unreachable else CONFIG['settings'].get('loss_timeout_sec', 10.0)
                    
                    if (time.time() - self.silence_start) > timeout:
                       old_idx = self.current_source_idx
                       old_name = CONFIG['sources'][old_idx]['name'].upper()
                       reason_msg = f"{old_name} unreachable" if is_active_unreachable else f"Silence detected on {old_name}"
                    
                       candidate_idx = self.current_source_idx
                       found_backup = False

                       for _ in range(2):
                           candidate_idx = (candidate_idx + 1) % 3
                           s = CONFIG['sources'][candidate_idx]
                           is_conf = False
                           if s['type'] == 'stream' and s['url']: is_conf = True
                           elif s['type'] == 'rtp' and s['rtp_uri']: is_conf = True
                           elif s['type'] == 'file' and s['path']: is_conf = True
                           elif s['type'] == 'backup_dir':
                               if s.get('backup_mode', 'single') == 'single' and s.get('backup_file'): is_conf = True
                               elif s.get('backup_mode', 'single') == 'playlist' and s.get('backup_playlist_name'): is_conf = True
                           elif s['type'] == 'tone': is_conf = True
                           elif s['type'] == 'device' and s.get('input_device') is not None: is_conf = True
                        
                           if is_conf:
                               self.current_source_idx = candidate_idx
                               found_backup = True
                               break
                       
                       new_idx = self.current_source_idx
                       new_name = CONFIG['sources'][new_idx]['name'].upper()
                       
                       if old_idx != new_idx:
                           add_internal_log(f"{reason_msg}. Switching to {new_name}.", "WARNING")
                       else:
                           add_internal_log(f"{reason_msg}.", "WARNING")
                       
                       self.silence_start = time.time()
                else:
                    self.is_silence = False

                # 6. Recovery logic
                if self.current_source_idx != 0:
                    for prio_idx in range(self.current_source_idx):
                        prio_ch = self.channels[prio_idx]
                        prio_db = max(self.vu_data['sources'][prio_idx]['l'], self.vu_data['sources'][prio_idx]['r'])
                        
                        if prio_ch.status_text not in ["UNREACHABLE", "BUFFERING"] and prio_db > CONFIG['settings']['recovery_threshold_db']:
                            if not self.is_recovering[prio_idx]:
                                self.recovery_timers[prio_idx] = time.time()
                                self.is_recovering[prio_idx] = True
                            elif (time.time() - self.recovery_timers[prio_idx]) > CONFIG['settings']['recovery_timeout_sec']:
                                rec_name = CONFIG['sources'][prio_idx]['name'].upper()
                                add_internal_log(f"Audio recovery triggered. Switching back to {rec_name}.", "RECOVERY")
                                self.current_source_idx = prio_idx
                                self.is_recovering[prio_idx] = False
                                self.is_silence = False
                                break
                        else:
                            self.is_recovering[prio_idx] = False
            else:
                # In manual mode, we force the anomaly log on the played source
                active_idx = self.current_source_idx
                ch = self.channels[active_idx]
                db = max(self.vu_data['sources'][active_idx]['l'], self.vu_data['sources'][active_idx]['r'])
                is_active_unreachable = (ch.status_text == "UNREACHABLE")
                
                if db < CONFIG['settings'].get('loss_threshold_db', -60.0) or is_active_unreachable:
                    if not self.is_silence:
                        self.silence_start = time.time()
                        self.is_silence = True
                        self.manual_log_triggered = False # Ready to log a potential new failure
                    
                    timeout = 5.0 if is_active_unreachable else CONFIG['settings'].get('loss_timeout_sec', 10.0)
                    
                    # Unique log: We check that the timeout has expired AND that the log has not yet been generated
                    if (time.time() - self.silence_start) > timeout and not self.manual_log_triggered:
                        name = CONFIG['sources'][active_idx]['name'].upper()
                        reason_msg = f"{name} unreachable" if is_active_unreachable else f"Silence detected on {name}"
                        add_internal_log(f"{reason_msg}.", "WARNING")
                        self.manual_log_triggered = True # Lock the log for this anomaly
                else:
                    # When recovered
                    if self.manual_log_triggered:
                        name = CONFIG['sources'][active_idx]['name'].upper()
                        add_internal_log(f"Normal broadcasting has resumed on {name}.", "RECOVERY")
                    
                    self.is_silence = False
                    self.manual_log_triggered = False # Lock reset

            time.sleep(0.005)

    def _audio_callback(self, outdata, frames, time_info, status):
        # Override logic for the Test Tone Generator (Enabled from the FM Settings)
        if CONFIG['fm'].get('tone_enabled'):
            freq = float(CONFIG['fm'].get('tone_freq', 1000))
            gain = float(CONFIG['fm'].get('tone_gain', -10))
            wave = CONFIG['fm'].get('tone_wave', 'sine')
            
            t = (np.arange(frames) + self.tone_phase) / SAMPLE_RATE
            self.tone_phase += frames
            
            if wave == 'sine': sig = np.sin(2 * np.pi * freq * t)
            else: sig = np.sign(np.sin(2 * np.pi * freq * t))
            
            sig = sig * (10 ** (gain / 20.0))
            sig = sig.reshape(-1, 1)
            outdata[:] = np.hstack([sig] * CHANNELS)
            return

        ch = self.channels[self.current_source_idx]
        try:
            data = ch.queue.get_nowait()
        except:
            outdata.fill(0)
            self.vu_data['sources'][self.current_source_idx]['l'] = -60.0
            self.vu_data['sources'][self.current_source_idx]['r'] = -60.0
            self.vu_data['out_l'] = -60.0
            self.vu_data['out_r'] = -60.0
            return

        if len(data) < frames:
            outdata.fill(0)
            return

        gain_in = 10 ** (CONFIG['sources'][self.current_source_idx]['gain'] / 20.0)
        input_sig = data * gain_in
        
        pk_src_l = np.max(np.abs(input_sig[:, 0])) if len(input_sig) > 0 else 0
        pk_src_r = np.max(np.abs(input_sig[:, 1])) if len(input_sig) > 0 else 0
        self.vu_data['sources'][self.current_source_idx]['l'] = float(20 * np.log10(pk_src_l) if pk_src_l > 0.00001 else -60.0)
        self.vu_data['sources'][self.current_source_idx]['r'] = float(20 * np.log10(pk_src_r) if pk_src_r > 0.00001 else -60.0)

        gain_out = 10 ** (CONFIG['audio']['output_gain_db'] / 20.0)
        output_sig = input_sig * gain_out
        np.clip(output_sig, -1.0, 1.0, out=output_sig)
        
        peak_l = np.max(np.abs(output_sig[:, 0])) if len(output_sig) > 0 else 0
        peak_r = np.max(np.abs(output_sig[:, 1])) if len(output_sig) > 0 else 0
        self.vu_data['out_l'] = float(20 * np.log10(peak_l) if peak_l > 0.00001 else -60.0)
        self.vu_data['out_r'] = float(20 * np.log10(peak_r) if peak_r > 0.00001 else -60.0)
        
        if self.analysis_active:
            socketio.emit('audio_analysis_data', {'samples': output_sig[:, 0].tolist()})
            
        outdata[:] = output_sig

# --- 5. ENGINE INITIALISATION ---
engine = BroadcastEngine()

# --- 6. FLASK ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def index():
    # Handling connection errors caused by redirects
    login_error = (request.args.get('error') == '1')
    
    # Security logic in order to hide the accounts passwords (admin + operator) in the source code if the user is not logged in
    safe_cfg = CONFIG
    if not session.get('logged_in') or session.get('role') != 'admin':
        safe_cfg = json.loads(json.dumps(CONFIG))
        safe_cfg['server']['password'] = ''
        safe_cfg['server']['op_pass'] = ''
        safe_cfg['smtp']['pass'] = ''
    
    if not session.get('logged_in'): 
        return render_template('index.html', login_needed=True, cfg=safe_cfg, login_error=login_error)
        
    if request.method == 'POST':
        try:
            needs_restart = False
            
            new_dev = int(request.form.get('audio_device'))
            new_latency = int(float(request.form.get('out_latency', 1000)))
            
            # Forcing engine restart in case of a major change in the configuration
            if CONFIG['audio']['output_device'] != new_dev or CONFIG['audio'].get('output_latency_ms') != new_latency:
                needs_restart = True
                
            CONFIG['audio']['output_device'] = new_dev
            CONFIG['audio']['output_latency_ms'] = new_latency
            
            CONFIG['audio']['output_gain_db'] = float(request.form.get('out_gain', 0))
            CONFIG['settings']['loss_threshold_db'] = float(request.form.get('loss_thresh'))
            CONFIG['settings']['loss_timeout_sec'] = int(float(request.form.get('loss_time', 10)))
            CONFIG['settings']['recovery_threshold_db'] = float(request.form.get('rec_thresh'))
            CONFIG['settings']['recovery_timeout_sec'] = int(float(request.form.get('rec_time', 5)))

            for i in range(3):
                new_type = request.form.get(f'type{i}')
                new_url = request.form.get(f'url{i}', '')
                new_uri = request.form.get(f'rtp_uri{i}', '')
                new_path = request.form.get(f'path{i}', '')
                new_backup_file = request.form.get(f'backup_file{i}', '')
                new_backup_mode = request.form.get(f'backup_mode{i}', 'single')
                new_playlist_name = request.form.get(f'backup_playlist_name{i}', '')
                new_buffer = int(request.form.get(f'buffer_kb{i}', 1024))
                new_in_dev = request.form.get(f'input_device{i}')
                
                src = CONFIG['sources'][i]
                src['input_device'] = int(new_in_dev) if (new_in_dev and new_in_dev != 'None') else None
                if (src['type'] != new_type or src['url'] != new_url or src['rtp_uri'] != new_uri or src['path'] != new_path or src.get('backup_file') != new_backup_file or src.get('backup_mode') != new_backup_mode or src.get('backup_playlist_name') != new_playlist_name or src['buffer_kb'] != new_buffer):
                    needs_restart = True
                
                src['type'] = new_type
                src['url'] = new_url
                src['rtp_uri'] = new_uri
                src['path'] = new_path
                src['backup_file'] = new_backup_file
                src['backup_mode'] = new_backup_mode
                src['backup_playlist_name'] = new_playlist_name
                src['buffer_kb'] = new_buffer
                
                if new_type in ['file', 'backup_dir']:
                    src['repeat'] = True
                else:
                    src['repeat'] = (request.form.get(f'repeat{i}') == 'on')
                src['gain'] = float(request.form.get(f'gain{i}', 0))
                src['meta_enabled'] = (request.form.get(f'meta_enabled{i}') == 'on')
                src['meta_path'] = request.form.get(f'meta_path{i}', '')

                src['meta_normalize'] = (request.form.get(f'meta_normalize{i}') == 'on')
                src['meta_only_played'] = (request.form.get(f'meta_only_played{i}') == 'on')
                src['meta_uppercase'] = (request.form.get(f'meta_uppercase{i}') == 'on')
                src['meta_rtplus'] = (request.form.get(f'meta_rtplus{i}') == 'on')
                src['meta_rtplus_format'] = request.form.get(f'meta_rtplus_format{i}', 'artist_title')
                
                # Separator management (listed or customized)
                sep_val = request.form.get(f'meta_rtplus_separator{i}', ' - ')
                if sep_val == 'custom':
                    sep_val = request.form.get(f'meta_rtplus_custom_sep{i}', ' - ')
                src['meta_rtplus_separator'] = sep_val
                
                src['meta_max_64'] = (request.form.get(f'meta_max_64{i}') == 'on')
                src['alert_silent'] = (request.form.get(f'alert_silent{i}') == 'on')
                src['alert_unreachable'] = (request.form.get(f'alert_unreachable{i}') == 'on')
                
                # Test Tone parameters
                src['tone_wave'] = request.form.get(f'tone_wave{i}', 'sine')
                src['tone_freq'] = int(request.form.get(f'tone_freq{i}', 1000))
            
            save_config(CONFIG)
            
            if needs_restart:
                engine.restart_engine()
        except Exception as e:
            add_internal_log(f"Config POST Error: {str(e)}", "ERROR")
            logging.error(f"POST Error: {e}")
            
    devs = []
    in_devs = []
    try:
        query = sd.query_devices()
        host_apis = sd.query_hostapis()
        for i, d in enumerate(query):
            api_name = host_apis[d['hostapi']]['name']
            if d['max_output_channels'] > 0: 
                devs.append({'id': i, 'name': f"[{api_name}] {d['name']}"})
            if d['max_input_channels'] > 0:
                in_devs.append({'id': i, 'name': f"[{api_name}] {d['name']}"})
        
        devs.sort(key=lambda x: x['name'])
        in_devs.sort(key=lambda x: x['name'])
    except: pass
    
    audio_files = get_audio_files_info()
    return render_template('index.html', login_needed=False, cfg=safe_cfg, devices=devs, in_devices=in_devs, audio_files=audio_files)

@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    if not session.get('logged_in'): return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    if session.get('role') != 'admin' and not CONFIG['server'].get('op_backup_access'): return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
    if 'file' not in request.files: return jsonify({'status': 'error', 'message': 'No file selected'})
    file = request.files['file']
    if file.filename == '': return jsonify({'status': 'error', 'message': 'No file selected'})
    filename = secure_filename(file.filename)
    # Formats whitelist for the backup audio files uploader
    allowed_ext = {'.mp3', '.wav', '.ogg', '.aac', '.flac', '.m4a'}
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in allowed_ext:
        return jsonify({'status': 'error', 'message': 'File type not accepted.'})
        
    file.save(os.path.join(BACKUP_DIR, filename))
    add_internal_log(f"Backup audio file uploaded: {filename}", "SYSTEM")
    return jsonify({'status': 'ok', 'message': 'File added to the directory.'})

@app.route('/delete_audio', methods=['POST'])
def delete_audio():
    if not session.get('logged_in'): return jsonify({'status': 'error'}), 403
    if session.get('role') != 'admin' and not CONFIG['server'].get('op_backup_access'): return jsonify({'status': 'error'}), 403
    filename = request.form.get('filename')
    if filename:
        p = os.path.join(BACKUP_DIR, secure_filename(filename))
        if os.path.exists(p):
            os.remove(p)
            add_internal_log(f"Audio file deleted: {filename}", "SYSTEM")
            return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'})

@app.route('/update_playlists', methods=['POST'])
def update_playlists():
    if not session.get('logged_in'): return jsonify({'status': 'error'})
    if session.get('role') != 'admin' and not CONFIG['server'].get('op_backup_access'): return jsonify({'status': 'error'})
    CONFIG['playlists'] = request.json.get('playlists', {})
    save_config(CONFIG)
    add_internal_log("Playlists updated.", "SYSTEM")
    return jsonify({'status': 'ok'})

@app.route('/api/audio_files')
def api_audio_files():
    if not session.get('logged_in'): return jsonify([])
    return jsonify(get_audio_files_info())

@app.route('/update_fm', methods=['POST'])
def update_fm():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    try:
        CONFIG['fm']['tilt'] = (request.form.get('fm_tilt') == 'on')
        CONFIG['fm']['tone_enabled'] = (request.form.get('tone_enabled') == 'on')
        CONFIG['fm']['tone_wave'] = request.form.get('tone_wave', 'sine')
        CONFIG['fm']['tone_freq'] = int(request.form.get('tone_freq', 1000))
        CONFIG['fm']['tone_gain'] = float(request.form.get('tone_gain', -10.0))
        save_config(CONFIG)
        engine.restart_engine()
        add_internal_log("FM/Tone settings updated.", "INFO")
        return redirect(url_for('index'))
    except: return "Error"

@app.route('/update_smtp', methods=['POST'])
def update_smtp():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    try:
        CONFIG['smtp']['enabled'] = (request.form.get('smtp_enabled') == 'on')
        CONFIG['smtp']['host'] = request.form.get('smtp_host')
        CONFIG['smtp']['port'] = int(request.form.get('smtp_port'))
        CONFIG['smtp']['user'] = request.form.get('smtp_user')
        CONFIG['smtp']['pass'] = request.form.get('smtp_pass')
        CONFIG['smtp']['from'] = request.form.get('smtp_from')
        CONFIG['smtp']['spam_delay'] = int(float(request.form.get('smtp_spam_delay', 120)))
        CONFIG['smtp']['trigger_delay'] = int(float(request.form.get('smtp_trigger_delay', 30)))
        CONFIG['smtp']['tls'] = (request.form.get('smtp_tls') == 'on')
        
        # Multiple recipients management
        recipients = []
        for i in range(4):
            val = request.form.get(f'smtp_to_{i}', '').strip()
            recipients.append(val)
        CONFIG['smtp']['recipients'] = recipients
        
        save_config(CONFIG)
        add_internal_log("SMTP settings updated.", "INFO")
        return redirect(url_for('index'))
    except: return "Error"

@app.route('/smtp_test', methods=['POST'])
def smtp_test():
    if not session.get('logged_in'): return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    
    cfg_smtp = CONFIG['smtp']
    if not cfg_smtp['host']:
        return jsonify({'status': 'error', 'message': 'SMTP Host not configured.\n\nIf you have just configured the service, you must click on "Save changes" BEFORE performing a test.'})

    recipients = [r for r in cfg_smtp['recipients'] if r.strip()]
    if not recipients:
        return jsonify({'status': 'error', 'message': 'No recipients configured.\nPlease verify your configuration and try again.'})

    subject = "Test Email"
    body = ("This is a test email from WestBroadcast Streamer.\n\n"
            "This confirms that the SMTP configuration has been set up correctly.\n"
            "You can now receive alerts in the event of a failure or silence on your audio sources.")

    try:
        msg = MIMEText(body)
        instance = CONFIG['server']['instance_name']
        prefix = f"WestBroadcast Streamer - {instance}" if instance else "WestBroadcast Streamer"
        msg['Subject'] = f"[{prefix}] {subject}"
        msg['From'] = cfg_smtp['from']
        msg['To'] = ", ".join(recipients)
        msg['Date'] = formatdate(localtime=True)

        context = ssl.create_default_context()

        if cfg_smtp.get('tls'):
            # TLS Logic
            server = smtplib.SMTP_SSL(cfg_smtp['host'], cfg_smtp['port'], context=context, timeout=15)
        else:
            # STARTTLS Logic
            server = smtplib.SMTP(cfg_smtp['host'], cfg_smtp['port'], timeout=15)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()

        if cfg_smtp['user'] and cfg_smtp['pass']:
            server.login(cfg_smtp['user'], cfg_smtp['pass'])
            
        server.send_message(msg)
        server.quit()
        
        return jsonify({'status': 'ok', 'message': 'Test OK. The connection to the SMTP server was successful.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"The connection to the SMTP server has failed. Please check your configuration and try again.\n\nError details: {str(e)}"})

@app.route('/api/logs')
def api_logs():
    if not session.get('logged_in'): return jsonify({'logs': [], 'total': 0, 'page': 1})
    
    # Retrieving pagination and filter settings
    try: page = int(request.args.get('page', 1))
    except: page = 1
    
    log_filter = request.args.get('filter', 'ALL')
    per_page = 50

    # 1. Filtering
    filtered_logs = []
    # We go through the list in reverse order to see the most recent entries
    for log in reversed(INTERNAL_LOGS):
        if log_filter == "ALL" or log['level'] == log_filter:
            filtered_logs.append(log)
    
    # 2. Pagination
    total_logs = len(filtered_logs)
    total_pages = (total_logs + per_page - 1) // per_page
    if total_pages < 1: total_pages = 1
    
    if page > total_pages: page = total_pages
    if page < 1: page = 1

    start = (page - 1) * per_page
    end = start + per_page
    
    # Cutting
    logs_slice = filtered_logs[start:end]

    return jsonify({
        'logs': logs_slice,
        'total': total_logs,
        'page': page,
        'total_pages': total_pages
    })

@app.route('/logs_export')
def logs_export():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    def generate():
        yield "Timestamp | Type | Event\n"
        yield "--------------------------\n"
        for log in INTERNAL_LOGS:
            yield f"{log['timestamp']} | {log['level']} | {log['event']}\n"
    return Response(generate(), mimetype="text/plain", headers={"Content-Disposition": "attachment;filename=logs.txt"})

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    if not session.get('logged_in'): return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    INTERNAL_LOGS.clear()
    add_internal_log("Logs cleared by user.", "SYSTEM")
    return jsonify({'status': 'ok'})

@app.route('/login', methods=['POST'])
def login():
    ip = request.remote_addr
    now = time.time()
    
    # Clearing login attempts older than 90 seconds
    if ip in LOGIN_ATTEMPTS:
        LOGIN_ATTEMPTS[ip] = [t for t in LOGIN_ATTEMPTS[ip] if now - t < 90]
    
    # Attempts amount verification
    if len(LOGIN_ATTEMPTS.get(ip, [])) >= 3:
        add_internal_log(f"3 failed login attempts from IP {ip}", "AUTH")
        return "Too many failed login attempts. For security reasons, you must wait 90 seconds before trying again.", 429

    # Credentials verification
    if request.form.get('username') == CONFIG['server']['user'] and request.form.get('password') == CONFIG['server']['password']:
        session['logged_in'] = True
        session['role'] = 'admin' # Administrator role attribution
        if ip in LOGIN_ATTEMPTS: del LOGIN_ATTEMPTS[ip] 
        add_internal_log(f"Successful login from IP {ip} as Administrator.", "AUTH")
        return redirect(url_for('index'))
        
    elif CONFIG['server'].get('op_enabled') and request.form.get('username') == CONFIG['server'].get('op_user') and request.form.get('password') == CONFIG['server'].get('op_pass'):
        session['logged_in'] = True
        session['role'] = 'operator' # Operator role attribution
        if ip in LOGIN_ATTEMPTS: del LOGIN_ATTEMPTS[ip]
        add_internal_log(f"Successful login from IP {ip} as Operator.", "AUTH")
        return redirect(url_for('index'))
    else:
        # Logging failed attempt(s)
        if ip not in LOGIN_ATTEMPTS: LOGIN_ATTEMPTS[ip] = []
        LOGIN_ATTEMPTS[ip].append(now)
        
        add_internal_log(f"Failed login attempt from IP {ip}", "AUTH")
        return redirect(url_for('index', error='1'))

@app.route('/logout')
def logout(): session.pop('logged_in', None); return redirect(url_for('index'))

@app.route('/set_mode', methods=['POST'])
def set_mode():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    
    mode = request.form.get('mode', 'auto')
    CONFIG['settings']['selection_mode'] = mode
    save_config(CONFIG)
    
    if mode != 'auto':
        try:
            forced_idx = int(mode)
            engine.current_source_idx = forced_idx
            engine.is_silence = False
            src_name = CONFIG['sources'][forced_idx]['name'].upper()
            add_internal_log(f"Manual mode enabled. Forcing playback of {src_name}.", "SYSTEM")
        except: pass
    else:
        add_internal_log("Automatic mode enabled.", "SYSTEM")
        best_idx = engine.current_source_idx
        for i in range(3):
            s = CONFIG['sources'][i]
            is_conf = False
            if s['type'] == 'stream' and s['url']: is_conf = True
            elif s['type'] == 'rtp' and s['rtp_uri']: is_conf = True
            elif s['type'] == 'file' and s['path'] and os.path.exists(s['path']): is_conf = True
            elif s['type'] == 'backup_dir':
                if s.get('backup_mode', 'single') == 'single' and s.get('backup_file') and os.path.exists(os.path.join(BACKUP_DIR, s.get('backup_file'))): is_conf = True
                elif s.get('backup_mode', 'single') == 'playlist' and s.get('backup_playlist_name'): is_conf = True
            elif s['type'] == 'tone': is_conf = True
            elif s['type'] == 'device' and s.get('input_device') is not None: is_conf = True
            
            if not is_conf: continue
            
            if s['type'] in ['file', 'backup_dir', 'tone']:
                best_idx = i
                break
                
            ch = engine.channels[i]
            vu = max(engine.vu_data['sources'][i]['l'], engine.vu_data['sources'][i]['r'])
            thresh = float(CONFIG['settings'].get('loss_threshold_db', -60.0))
            
            if ch.status_text == "PLAYING" and vu > thresh:
                best_idx = i
                break
        
        if engine.current_source_idx != best_idx:
            engine.current_source_idx = best_idx
        engine.is_silence = False
        
    return redirect(url_for('index'))

@app.route('/update_security', methods=['POST'])
def update_security():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    try:
        old_port = CONFIG['server']['port']
        new_port = int(request.form.get('srv_port'))
        
        CONFIG['server']['port'] = new_port
        CONFIG['server']['user'] = request.form.get('srv_user')
        CONFIG['server']['instance_name'] = request.form.get('srv_name')
        CONFIG['server']['password'] = request.form.get('srv_pass')
        CONFIG['server']['hide_bg_on_login'] = (request.form.get('hide_bg') == 'on')
        CONFIG['server']['peak_hold_enabled'] = (request.form.get('peak_hold') == 'on')
        try: CONFIG['server']['peak_hold_time'] = int(request.form.get('peak_time', 3))
        except: CONFIG['server']['peak_hold_time'] = 3
        CONFIG['server']['op_enabled'] = (request.form.get('op_enabled') == 'on')
        CONFIG['server']['op_user'] = request.form.get('op_user', 'operator')
        CONFIG['server']['op_pass'] = request.form.get('op_pass', 'operator')
        CONFIG['server']['op_audio_access'] = (request.form.get('op_audio') == 'on')
        CONFIG['server']['op_fm_access'] = (request.form.get('op_fm') == 'on')
        CONFIG['server']['op_allow_restart'] = (request.form.get('op_allow_restart') == 'on')
        CONFIG['server']['op_backup_access'] = (request.form.get('op_backup') == 'on')
        save_config(CONFIG)
        
        if old_port != new_port:
            add_internal_log(f"HTTP Port changed from {old_port} to {new_port}. System restart requested.", "SYSTEM")
            def restart_thread():
                time.sleep(1)
                args = sys.argv.copy()
                if '--is-restart' not in args: args.append('--is-restart')
                subprocess.Popen([sys.executable] + args)
                os._exit(0)
            threading.Thread(target=restart_thread).start()
            return f"""<!DOCTYPE html><html><head></head><body style="font-family:sans-serif;text-align:center;padding-top:50px;"><h2>HTTP Port modified. The decoder is restarting... Please wait.</h2><p>You will be redirected to the main page in 5 seconds.</p><script>setTimeout(function(){{ window.location.href = window.location.protocol + '//' + window.location.hostname + ':{new_port}/'; }}, 5000);</script></body></html>"""
            
        return redirect(url_for('index'))
    except: return "Error"

@app.route('/sys_restart')
def sys_restart():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    if session.get('role') != 'admin' and not CONFIG['server'].get('op_allow_restart'):
        return "You do not have the necessary permissions to perform this operation.", 403
        
    add_internal_log("System restart requested.", "SYSTEM")
    def restart_thread():
        time.sleep(1)
        args = sys.argv.copy()
        if '--is-restart' not in args: args.append('--is-restart')
        subprocess.Popen([sys.executable] + args)
        os._exit(0)
    threading.Thread(target=restart_thread).start()
    return """<!DOCTYPE html><html><head><meta http-equiv="refresh" content="5;url=/"></head><body style="font-family:sans-serif;text-align:center;padding-top:50px;"><h2>The decoder is restarting... Please wait.</h2><p>You will be redirected to the main page in 5 seconds.</p></body></html>"""

@app.route('/sys_restore')
def sys_restore():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    global CONFIG
    CONFIG = DEFAULT_CONFIG.copy() 
    save_config(DEFAULT_CONFIG)    
    add_internal_log("Factory restore requested.", "SYSTEM")
    def restart_thread():
        time.sleep(1)
        args = sys.argv.copy()
        if '--is-restart' not in args: args.append('--is-restart')
        subprocess.Popen([sys.executable] + args)
        os._exit(0)
    threading.Thread(target=restart_thread).start()
    return """<!DOCTYPE html><html><head><meta http-equiv="refresh" content="5;url=/"></head><body style="font-family:sans-serif;text-align:center;padding-top:50px;"><h2>Resetting the decoder to factory settings... Please wait.</h2><p>You will be redirected to the main page in 5 seconds.</p></body></html>"""

@app.route('/sys_export')
def sys_export():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    save_config(CONFIG) 
    return send_file(CONFIG_FILE, as_attachment=True, download_name='config.json')

@app.route('/sys_import', methods=['POST'])
def sys_import():
    if not session.get('logged_in'): return "You do not have the necessary permissions to perform this operation.", 403
    if 'config_file' not in request.files: return "No file"
    file = request.files['config_file']
    if file.filename == '': return "No filename"
    if file:
        file.save(CONFIG_FILE)
        add_internal_log("Configuration imported.", "SYSTEM")
        def restart_thread():
            time.sleep(1)
            args = sys.argv.copy()
            if '--is-restart' not in args: args.append('--is-restart')
            subprocess.Popen([sys.executable] + args)
            os._exit(0)
        threading.Thread(target=restart_thread).start()
        return """<!DOCTYPE html><html><head><meta http-equiv="refresh" content="5;url=/"></head><body style="font-family:sans-serif;text-align:center;padding-top:50px;"><h2>The configuration file has been imported successfully. Restarting the decoder... </h2><p>You will be redirected to the main page in 5 seconds.</p></body></html>"""
    return "Error"

@socketio.on('set_analysis_state')
def handle_analysis_state(data):
    if not session.get('logged_in'): return
    engine.analysis_active = data.get('active', False)
    add_internal_log(f"Audio Analysis engine {'started' if engine.analysis_active else 'stopped'}.", "SYSTEM")

# --- 7. LOOPS & MAIN ---
def socket_emit_loop():
    while True:
        try:
            statuses = [engine.get_source_status(i) for i in range(3)]
            codecs = engine.get_codecs()
            
            idx = engine.current_source_idx
            src = CONFIG['sources'][idx]
            np_str = ""
            if src['type'] == 'stream':
                if src['url']:
                    np_str = f"Now playing: {src['url']}"
                    if engine.current_metadata_title:
                        np_str += f" ({engine.current_metadata_title})"
                else: np_str = "Now playing: ..."
            elif src['type'] == 'rtp':
                if src['rtp_uri']:
                    np_str = f"Now playing: {src['rtp_uri']} (RTP)"
                else: np_str = "Now playing: ..."
            elif src['type'] == 'tone':
                np_str = "Now playing: Test Tone Generator"
            else:
                if src.get('path'):
                    np_str = f"Now playing: {src['path']}"
                else:
                    np_str = "Now playing: ..."

            socketio.emit('status_update', {
                'vu': engine.vu_data,
                'active_idx': engine.current_source_idx,
                'uptime': engine.get_uptime_string(),
                'src_statuses': statuses,
                'codecs': codecs,
                'now_playing': np_str
            })
        except: pass
        time.sleep(0.1) 

def start_gui():
    root = tk.Tk()
    root.title("WestBroadcast Streamer")
    root.geometry("450x150")
    
    ip = get_local_ip()
    port = CONFIG['server']['port']
    
    tk.Label(root, text=f"WEBSERVER IS RUNNING ON PORT {port}", fg="green", font=("Segoe UI", 12, "bold")).pack(pady=(15, 0))
    tk.Label(root, text="KEEP THIS WINDOW OPEN FOR THE AUDIO OUTPUT!", fg="red", font=("Segoe UI", 10, "bold")).pack(pady=(0, 5))
    tk.Label(root, text=f"IP: {ip}", fg="#333", font=("Segoe UI", 10)).pack(pady=2)
    tk.Button(root, text="CLICK HERE TO OPEN THE WEBSERVER INTERFACE\n(Default credentials: admin/admin)", bg="#3c8dbc", fg="white", font=("Segoe UI", 9, "bold"), command=lambda: webbrowser.open(f"http://localhost:{port}")).pack(pady=10)
    tk.Label(root, text="Default credentials: admin / admin", fg="black", font=("Segoe UI", 8)).pack(pady=5)
    
    root.mainloop()

if __name__ == '__main__':
    threading.Thread(target=socket_emit_loop, daemon=True).start()
    threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=CONFIG['server']['port'], debug=False, use_reloader=False), daemon=True).start()
    print(f"--- WEBSERVER NOW READY ON PORT {CONFIG['server']['port']} ---")
    start_gui()