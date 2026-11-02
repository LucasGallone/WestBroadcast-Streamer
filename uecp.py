"""UECP (RDS) extraction from MP2 / AAC audio and forwarding over TCP, UDP or serial.

Pipeline (see SourceChannel._read_loop in app.py):
  ffmpeg  --PCM------------------------------------------------------>  audio queue (as before)
          --compressed audio, unmodified (-c:a copy) to 127.0.0.1-->  UecpTap
  UecpTap --MP2: Mp2UecpExtractor (pure Python, frame ancillary data)
          --AAC: AacUecpExtractor (aac_uecp_x64.dll, ADTS or LATM data stream elements)
          --> complete FE..FF wire frames --> CRC check --> SourceChannel.uecp_pending
  BroadcastEngine._uecp_loop releases each frame once the audio it arrived with has been played,
  and only for the on-air source, through UecpRouter to a TCP server, UDP or serial port.
"""
import collections
import ctypes
import os
import queue
import socket
import sys
import threading
import time

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# ffmpeg codec name -> (muxer for the passthrough copy, display label)
SUPPORTED_CODECS = {
    'mp2': ('mp2', 'MP2'),
    'aac': ('adts', 'AAC (ADTS)'),
    'aac_latm': ('latm', 'AAC (LATM)'),
}
# Source types whose ffmpeg input carries the compressed audio itself
SOURCE_TYPES = ('stream', 'rtp_mpegts', 'multiplex', 'rtp_sdp')

MAX_FRAME = 512


def base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def codec_label(codec):
    if not codec:
        return ''
    return SUPPORTED_CODECS.get(codec, (None, codec.upper()))[1]


# --- UECP frame validation ---

def unstuff(data):
    out, i, n = bytearray(), 0, len(data)
    while i < n:
        if data[i] == 0xFD and i + 1 < n:
            out.append(0xFD + data[i + 1])
            i += 2
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def crc16_ccitt(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc ^ 0xFFFF


def crc_ok(wire):
    """wire is a complete FE..FF frame, still byte-stuffed. CRC covers ADD..data (UECP spec 2.2.1)."""
    inner = unstuff(wire[1:-1])
    # ADD(2) SQC(1) MFL(1) MEC(1)... CRC(2)
    if len(inner) < 7 or inner[3] != len(inner) - 6:
        return False
    return crc16_ccitt(inner[:-2]) == int.from_bytes(inner[-2:], 'big')


# --- MP2 ---

_MP2_BITRATES = {
    True: (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0),   # MPEG-1
    False: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),       # MPEG-2/2.5
}
_MP2_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def mp2_frame_len(h):
    """Frame length in bytes for a Layer II header at h[0:4], or 0 if it isn't one."""
    if h[0] != 0xFF or (h[1] & 0xE0) != 0xE0:
        return 0
    version, layer = (h[1] >> 3) & 3, (h[1] >> 1) & 3
    if version == 1 or layer != 2:
        return 0
    br_idx, sr_idx, padding = h[2] >> 4, (h[2] >> 2) & 3, (h[2] >> 1) & 1
    if sr_idx == 3:
        return 0
    bitrate = _MP2_BITRATES[version == 3][br_idx]
    if not bitrate:
        return 0
    return 144000 * bitrate // _MP2_RATES[version][sr_idx] + padding


class Mp2UecpExtractor:
    """UECP carried in MP2 ancillary data (same layout as UecpBridge / DVB-UECP-Tools uecp_mp2.py):
    the last byte of each frame is a length (0xFD = escaped: the length is the byte before it),
    preceded by that many UECP bytes stored in reverse order. Messages may span frames."""

    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.buf = bytearray()
        self.msg = bytearray()
        self.active = False

    def feed(self, data):
        self.buf += data
        buf, i, n = self.buf, 0, len(self.buf)
        while i + 4 <= n:
            flen = mp2_frame_len(buf[i:i + 4])
            if not flen:
                nxt = buf.find(b'\xff', i + 1)
                i = nxt if nxt >= 0 else n
                continue
            if i + flen > n:
                break
            # Reject false syncs: the following frame (when buffered) must start with a header too
            if i + flen + 4 <= n and not mp2_frame_len(buf[i + flen:i + flen + 4]):
                i += 1
                continue
            self._frame(buf[i:i + flen])
            i += flen
        del self.buf[:i]

    def _frame(self, f):
        last = f[-1]
        if last == 0xFD:
            length, end = f[-2], len(f) - 2
        elif last != 0x00:
            length, end = last, len(f) - 1
        else:
            return
        if length > end - 4:
            return
        for b in reversed(f[end - length:end]):
            if b == 0xFE:
                self.active = True
                self.msg = bytearray()
            elif not self.active:
                continue
            elif b == 0xFF:
                self.active = False
                self.on_frame(b'\xfe' + bytes(self.msg) + b'\xff')
            else:
                self.msg.append(b)
                if len(self.msg) > MAX_FRAME:
                    self.active = False

    def close(self):
        pass


# --- AAC (aac_uecp DLL built from native/aac_uecp) ---

_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t)
_aac_lib = None
_aac_error = None


def aac_library():
    """Load aac_uecp_x64.dll / aac_uecp_x86.dll from the app folder. Returns (lib, error)."""
    global _aac_lib, _aac_error
    if _aac_lib is None and _aac_error is None:
        name = 'aac_uecp_x64.dll' if ctypes.sizeof(ctypes.c_void_p) == 8 else 'aac_uecp_x86.dll'
        path = os.path.join(base_dir(), name)
        try:
            lib = ctypes.CDLL(path)
            lib.aac_decoder_init.argtypes = [_CALLBACK]
            lib.aac_decoder_init.restype = ctypes.c_void_p
            lib.aac_decoder_feed.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
            lib.aac_decoder_feed.restype = None
            lib.aac_decoder_close.argtypes = [ctypes.c_void_p]
            lib.aac_decoder_close.restype = None
            _aac_lib = lib
        except OSError as e:
            _aac_error = f"{name} could not be loaded ({e})"
    return _aac_lib, _aac_error


class AacUecpExtractor:
    """UECP carried in AAC data stream elements. Accepts ADTS or LOAS/LATM, any chunk size.
    The DLL calls back with complete FE..FF frames, synchronously from feed()."""

    def __init__(self, on_frame):
        lib, err = aac_library()
        if not lib:
            raise RuntimeError(err)
        self.lib = lib
        self._cb = _CALLBACK(lambda p, n: on_frame(ctypes.string_at(p, n)))  # keep a reference
        self.handle = lib.aac_decoder_init(self._cb)
        if not self.handle:
            raise RuntimeError("AAC decoder initialisation failed")

    def feed(self, data):
        self.lib.aac_decoder_feed(self.handle, data, len(data))

    def close(self):
        if self.handle:
            self.lib.aac_decoder_close(self.handle)
            self.handle = None


# --- Tap on one ffmpeg process ---

class UecpTap:
    """Receives ffmpeg's passthrough copy of the audio on a localhost socket and extracts UECP.
    The reader never blocks on anything else, so it can't stall ffmpeg (and with it the PCM output)."""

    def __init__(self, codec, on_frame):
        self.codec = codec
        self.muxer = SUPPORTED_CODECS[codec][0]
        self.extractor = Mp2UecpExtractor(on_frame) if codec == 'mp2' else AacUecpExtractor(on_frame)
        self.closed = False
        self.connected = False
        self.conn = None
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(1)
        self.srv.settimeout(0.5)
        self.port = self.srv.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def output_args(self, map_spec):
        return ['-map', map_spec, '-c:a', 'copy', '-flush_packets', '1', '-f', self.muxer,
                f'tcp://127.0.0.1:{self.port}']

    def _run(self):
        try:
            while not self.closed:
                try:
                    self.conn, _ = self.srv.accept()
                    break
                except socket.timeout:
                    continue
            if self.closed or not self.conn:
                return
            self.connected = True
            self.conn.settimeout(0.5)
            while not self.closed:
                try:
                    data = self.conn.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                try:
                    self.extractor.feed(data)
                except Exception:
                    pass
        except OSError:
            pass

    def close(self):
        """Call only after the ffmpeg process has been killed."""
        self.closed = True
        for s in (self.conn, self.srv):
            if s:
                try: s.close()
                except OSError: pass
        self.thread.join(timeout=2)
        if not self.thread.is_alive():
            self.extractor.close()


# --- Outputs ---

OUTPUT_METHODS = ('tcp', 'udp', 'serial')


def output_key(src):
    method = src.get('uecp_output', 'tcp')
    if method == 'serial':
        return ('serial', str(src.get('uecp_serial_port', '')).strip(), int(src.get('uecp_serial_baud', 115200)))
    if method not in OUTPUT_METHODS:
        method = 'tcp'
    return (method, str(src.get('uecp_host', '')).strip(), int(src.get('uecp_port', 8300)))


def describe_key(key):
    kind, a, b = key
    if kind == 'serial':
        return f"{a} @ {b} baud"
    return f"{a}:{b} ({kind.upper()})"


def list_serial_ports():
    if not SERIAL_AVAILABLE:
        return []
    try:
        return sorted(p.device for p in serial.tools.list_ports.comports())
    except Exception:
        return []


class UecpOutput:
    """One destination (TCP client, UDP or serial port). Frames are queued and written as-is by a
    background thread that reconnects with backoff; when the queue is full the oldest is dropped.

    Whatever the encoder sends back (acknowledgements, echoes, logs) is read and discarded by a
    separate drain thread for as long as the connection is open, so replies can never fill a
    buffer and stall either side. The writer only ever writes, with a timeout."""

    BACKOFF_MIN, BACKOFF_MAX = 0.5, 10.0
    IO_TIMEOUT = 2.0

    def __init__(self, key, log):
        self.key = key
        self.log = log
        self.q = queue.Queue(maxsize=256)
        self.status = "Idle"
        self.sent = 0
        self.dropped = 0
        self.running = True
        self.conn = None
        self.conn_lost = None   # set by the drain thread when the peer closes / the port fails
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, frame):
        while True:
            try:
                self.q.put_nowait(frame)
                return
            except queue.Full:
                try:
                    self.q.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass

    def stop(self):
        self.running = False
        try: self.q.put_nowait(None)
        except queue.Full: pass

    def _open(self):
        kind, a, b = self.key
        if kind == 'serial':
            if not SERIAL_AVAILABLE:
                raise RuntimeError("pyserial is not installed")
            # read timeout so the drain thread wakes up regularly to notice the port being closed
            # serial_for_url: a plain port name (COM3) or a pyserial URL (rfc2217://, socket://, loop://)
            return serial.serial_for_url(a, baudrate=b, timeout=0.5, write_timeout=self.IO_TIMEOUT)
        if kind == 'udp':
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((a, b)) # fixes the destination (and resolves the host once); no handshake
        else:
            s = socket.create_connection((a, b), timeout=3)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(self.IO_TIMEOUT)
        return s

    def _drain(self, conn):
        """Read and discard anything coming back, until this connection is replaced or closed."""
        kind = self.key[0]
        while self.running and self.conn is conn:
            try:
                if kind == 'serial':
                    conn.read(max(1, conn.in_waiting))
                    continue
                data = conn.recv(65536)
                if not data and kind == 'tcp':
                    self.conn_lost = conn # encoder closed the connection
                    return
            except socket.timeout:
                continue
            except ConnectionResetError:
                # UDP: Windows reports an ICMP "port unreachable" for an earlier datagram this way.
                # Nobody listening is not an error for UDP, so keep going.
                if kind == 'udp':
                    continue
                self.conn_lost = conn
                return
            except Exception:
                if self.conn is conn:
                    self.conn_lost = conn
                return

    def _write(self, frame):
        kind = self.key[0]
        if kind == 'serial':
            self.conn.write(frame)
        elif kind == 'udp':
            try:
                self.conn.send(frame)
            except ConnectionResetError:
                self.conn.send(frame) # stale ICMP error from an earlier datagram (Windows); retry once
        else:
            self.conn.sendall(frame)

    def _close(self):
        if self.conn:
            conn, self.conn = self.conn, None # the drain thread exits once conn is no longer current
            try: conn.close()
            except Exception: pass

    def _run(self):
        backoff = self.BACKOFF_MIN
        frame = None
        while self.running:
            if frame is None:
                frame = self.q.get()
                if frame is None:
                    break
            if self.conn is not None and self.conn_lost is self.conn:
                self.log(f"UECP output {describe_key(self.key)} closed by the remote end, reconnecting", "WARNING")
                self._close()
            if self.conn is None:
                try:
                    conn = self._open()
                    self.conn = conn
                    self.conn_lost = None
                    threading.Thread(target=self._drain, args=(conn,), daemon=True).start()
                    verb = "Sending to" if self.key[0] == 'udp' else "Connected to"
                    self.status = f"{verb} {describe_key(self.key)}"
                    self.log(f"UECP output ready: {describe_key(self.key)}", "INFO")
                    backoff = self.BACKOFF_MIN
                except Exception as e:
                    was_error = self.status.startswith("Error")
                    self.status = f"Error: {e}"
                    if not was_error:
                        self.log(f"UECP output {describe_key(self.key)} failed: {e}", "ERROR")
                    t_end = time.time() + backoff
                    while self.running and time.time() < t_end:
                        time.sleep(0.1)
                    backoff = min(backoff * 2, self.BACKOFF_MAX)
                    continue
            try:
                self._write(frame)
                self.sent += 1
                frame = None
            except Exception as e:
                self.status = f"Error: {e}"
                self.log(f"UECP output {describe_key(self.key)} lost: {e}", "ERROR")
                self._close()
        self._close()


class UecpRouter:
    """Shares one UecpOutput per destination, so sources pointing at the same serial port
    or TCP server use a single connection."""

    def __init__(self, log):
        self.log = log
        self.outputs = {}
        self.lock = threading.Lock()

    def send(self, src, frame):
        key = output_key(src)
        if not key[1]:
            return
        with self.lock:
            out = self.outputs.get(key)
            if out is None:
                out = self.outputs[key] = UecpOutput(key, self.log)
        out.send(frame)

    def status(self, src):
        with self.lock:
            out = self.outputs.get(output_key(src))
        return (out.status, out.sent) if out else ("Idle", 0)

    def prune(self, keep_keys):
        """Close destinations that no enabled source uses any more."""
        with self.lock:
            for key in list(self.outputs):
                if key not in keep_keys:
                    self.outputs.pop(key).stop()


class FrameCountingQueue(queue.Queue):
    """queue.Queue of audio blocks that counts frames (samples per channel) going in and out.
    UECP frames are stamped with frames_in when extracted and released once frames_out passes the
    stamp, i.e. once the audio they arrived with has left the buffer - whatever the buffer depth."""

    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        self.frames_in = 0
        self.frames_out = 0

    def _put(self, item):
        super()._put(item)
        self.frames_in += len(item)

    def _get(self):
        item = super()._get()
        self.frames_out += len(item)
        return item


class UecpPending:
    """Validated frames awaiting release, each stamped with the audio queue's frames_in."""

    MAX = 2000

    def __init__(self):
        self.items = collections.deque()

    def add(self, stamp, frame):
        if len(self.items) >= self.MAX:
            self.items.popleft()
        self.items.append((stamp, frame))

    def pop_played(self, frames_out):
        out = []
        while self.items and self.items[0][0] <= frames_out:
            out.append(self.items.popleft()[1])
        return out

    def clear(self):
        self.items.clear()
