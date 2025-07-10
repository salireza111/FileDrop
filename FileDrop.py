import sys, socket, struct, time, json, threading, itertools
from pathlib import Path
from typing import Dict, Tuple
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QListWidget,
    QListWidgetItem, QProgressBar, QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QDialogButtonBox, QTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QIcon

import os
import stat
try:
    import paramiko
except ImportError:
    paramiko = None
ICON_PATH = os.path.abspath("assets/icon.png")

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "BUFFER_SIZE": 64 * 1024,
    "ANNOUNCE_INTERVAL": 2.0,
    "TCP_PORT": 5001
}

# Settings 

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


settings = load_settings()
BUFFER_SIZE = settings["BUFFER_SIZE"]
ANNOUNCE_INTERVAL = settings["ANNOUNCE_INTERVAL"]
TCP_PORT = settings["TCP_PORT"]

NOTE_HEADER = b'NOTE'  # 4‑byte header that marks a note message

# Utils

def human_size(num):
    for unit in ("","K","M","G","T"):
        if num < 1024:
            return f"{num:.1f} {unit}B"
        num /= 1024
    return f"{num:.1f} PB"


def get_local_ip():
    # Prefer a private LAN IP (not VPN)
    import socket
    try:
        # Try all interfaces for a private IP
        for iface in socket.getaddrinfo(socket.gethostname(), None):
            ip = iface[4][0]
            if ip.startswith('192.168.') or ip.startswith('10.') or ip.startswith('172.'):
                return ip
        # Fallback: connect to a public IP (may use VPN)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"


def broadcast_ip(ip):
    if ip.startswith('127.'):
        return '255.255.255.255'
    parts = ip.split('.')
    parts[-1] = '255'
    return '.'.join(parts)

# Discovery Threads

class AnnouncerThread(QThread):
    """Broadcast this device so senders can see it."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.running = True

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            ip = get_local_ip()
            payload = json.dumps({"ip": ip, "name": self.name}).encode()
            sock.sendto(payload, (broadcast_ip(ip), TCP_PORT))
            time.sleep(ANNOUNCE_INTERVAL)

    def stop(self):
        self.running = False
        self.wait()


class ListenerThread(QThread):
    """Listen for receivers announcing themselves."""

    new_peer = pyqtSignal(str, str) 

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", TCP_PORT))
        while self.running:
            try:
                data, _ = sock.recvfrom(1024)
                info = json.loads(data.decode())
                self.new_peer.emit(info["ip"], info["name"])
            except Exception:
                continue

    def stop(self):
        self.running = False
        self.wait()

# Receiver Thread

class ReceiverThread(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, float)  # percent
    new_note = pyqtSignal(str)  # received note

    def __init__(self, save_dir: str):
        super().__init__()
        self.save_dir = save_dir
        self._running = True

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", TCP_PORT))
        srv.listen(1)
        self.status.emit(f"Listening on {TCP_PORT} …")
        while self._running:
            conn, addr = srv.accept()
            if not self._running:
                conn.close()
                break
            with conn:
                self.status.emit(f"Connected: {addr[0]}")
                # ---- header ----
                header = conn.recv(4)
                if len(header) < 4:
                    continue
                # Note handling
                if header == NOTE_HEADER:
                    length_bytes = conn.recv(4)
                    if len(length_bytes) < 4:
                        continue
                    note_len = struct.unpack("!I", length_bytes)[0]
                    note_data = b''
                    while len(note_data) < note_len:
                        chunk = conn.recv(min(BUFFER_SIZE, note_len - len(note_data)))
                        if not chunk:
                            break
                        note_data += chunk
                    try:
                        text = note_data.decode()
                    except UnicodeDecodeError:
                        text = ''
                    self.new_note.emit(text)
                    self.status.emit("Received note ✓")
                    continue  # wait for next connection/message
                # File transfer handling
                name_len = struct.unpack("!I", header)[0]
                filename = conn.recv(name_len).decode()
                size_bytes = conn.recv(8)
                filesize = struct.unpack("!Q", size_bytes)[0]
                dest = Path(self.save_dir) / Path(filename).name

                # Ensure unique filename (do not overwrite)
                base = dest.stem
                ext = dest.suffix
                parent = dest.parent
                counter = 1
                while dest.exists():
                    dest = parent / f"{base} ({counter}){ext}"
                    counter += 1

                start = time.perf_counter()
                received = 0
                with open(dest, "wb") as f:
                    while received < filesize:
                        chunk = conn.recv(min(BUFFER_SIZE, filesize - received))
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        elapsed = max(time.perf_counter() - start, 1e-3)
                        speed = (received / (1024 ** 2)) / elapsed
                        percent = int(received / filesize * 100)
                        self.progress.emit(percent, speed)
                self.status.emit(f"Saved {dest.name} ✓")

    def stop(self):
        self._running = False
        try:
            socket.create_connection(("127.0.0.1", TCP_PORT), timeout=1).close()
        except Exception:
            pass
        self.wait()

# Drag‑and‑drop label

class DragLabel(QLabel):
    file_dropped = pyqtSignal(str)

    def __init__(self, text):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            """
            QLabel {
                border: 2px dashed #90A4AE;
                border-radius: 12px;
                padding: 24px;
                color: #90A4AE;
                font-size: 16px;
            }
            """
        )
        self.setCursor(Qt.PointingHandCursor)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            self.file_dropped.emit(url.toLocalFile())
        e.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            file_path, _ = QFileDialog.getOpenFileName(self, "Select file to send")
            if file_path:
                self.file_dropped.emit(file_path)

# Add SCPDialog class

class SCPDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SCP Download")
        self.sftp = None
        self.ssh = None
        self.current_path = '.'
        self.connected = False
        self.resize(520, 420)
        self.layout = QVBoxLayout(self)
        form = QFormLayout()
        self.ip_edit = QLineEdit(); self.ip_edit.setPlaceholderText("e.g. 192.168.1.10")
        self.port_spin = QSpinBox(); self.port_spin.setRange(1, 65535); self.port_spin.setValue(22)
        self.user_edit = QLineEdit(); self.user_edit.setPlaceholderText("username")
        self.pass_edit = QLineEdit(); self.pass_edit.setEchoMode(QLineEdit.Password)
        self.local_edit = QLineEdit(); self.local_edit.setText(str(Path.home() / "Downloads"))
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._choose_local)
        row = QHBoxLayout(); row.addWidget(self.local_edit); row.addWidget(browse_btn)
        form.addRow("IP/Host:", self.ip_edit)
        form.addRow("Port:", self.port_spin)
        form.addRow("Username:", self.user_edit)
        form.addRow("Password:", self.pass_edit)
        form.addRow("Save to:", row)
        self.layout.addLayout(form)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._connect)
        self.layout.addWidget(self.connect_btn)
        # File browser area (hidden until connected)
        self.browser_widget = QWidget(); self.browser_layout = QVBoxLayout(self.browser_widget)
        nav_row = QHBoxLayout()
        self.up_btn = QPushButton("Up")
        self.up_btn.clicked.connect(self._go_up)
        self.path_lbl = QLabel("")
        nav_row.addWidget(self.up_btn); nav_row.addWidget(self.path_lbl); nav_row.addStretch(1)
        self.browser_layout.addLayout(nav_row)
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self._item_activated)
        self.browser_layout.addWidget(self.file_list)
        self.download_btn = QPushButton("Download Selected File")
        self.download_btn.clicked.connect(self._download_file)
        self.browser_layout.addWidget(self.download_btn)
        self.browser_widget.setVisible(False)
        self.layout.addWidget(self.browser_widget)
        self.status_lbl = QLabel("")
        self.layout.addWidget(self.status_lbl)
        self.btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.btns.rejected.connect(self.reject)
        self.layout.addWidget(self.btns)
        self.selected_file = None
    def _choose_local(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose local folder", self.local_edit.text())
        if folder:
            self.local_edit.setText(folder)
    def _connect(self):
        try:
            import paramiko
        except ImportError:
            self.status_lbl.setText("Please install paramiko: pip install paramiko")
            return
        ip = self.ip_edit.text().strip()
        port = self.port_spin.value()
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()
        self.status_lbl.setText("Connecting…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(ip, port=port, username=username, password=password, timeout=10)
            self.sftp = self.ssh.open_sftp()
            self.current_path = self.sftp.normalize('.')
            self.connected = True
            self._show_browser()
            self.status_lbl.setText("Connected. Browse and select a file to download.")
        except Exception as e:
            self.status_lbl.setText(f"Connection failed: {e}")
        QApplication.restoreOverrideCursor()
    def _show_browser(self):
        self.connect_btn.setVisible(False)
        self.browser_widget.setVisible(True)
        self._list_dir()
    def _list_dir(self):
        self.file_list.clear()
        self.path_lbl.setText(self.current_path)
        try:
            entries = self.sftp.listdir_attr(self.current_path)
            # Folders first, then files
            folders = [e for e in entries if stat.S_ISDIR(e.st_mode)]
            files = [e for e in entries if not stat.S_ISDIR(e.st_mode)]
            for f in sorted(folders, key=lambda x: x.filename):
                item = QListWidgetItem(f"📁 {f.filename}")
                item.setData(Qt.UserRole, (f.filename, True))
                self.file_list.addItem(item)
            for f in sorted(files, key=lambda x: x.filename):
                item = QListWidgetItem(f"{f.filename}")
                item.setData(Qt.UserRole, (f.filename, False))
                self.file_list.addItem(item)
        except Exception as e:
            self.status_lbl.setText(f"Failed to list directory: {e}")
    def _item_activated(self, item):
        name, is_dir = item.data(Qt.UserRole)
        if is_dir:
            if self.current_path.endswith('/'):
                self.current_path = self.current_path + name
            else:
                self.current_path = self.current_path + '/' + name
            self._list_dir()
        else:
            self.selected_file = self.current_path + ('/' if not self.current_path.endswith('/') else '') + name
            for i in range(self.file_list.count()):
                self.file_list.item(i).setSelected(False)
            item.setSelected(True)
    def _go_up(self):
        if self.current_path == '/' or self.current_path == '':
            return
        self.current_path = str(Path(self.current_path).parent)
        if not self.current_path:
            self.current_path = '/'
        self._list_dir()
    def _download_file(self):
        if not self.selected_file:
            self.status_lbl.setText("Select a file to download.")
            return
        local_dir = self.local_edit.text().strip()
        local_path = os.path.join(local_dir, os.path.basename(self.selected_file))
        self.status_lbl.setText("Downloading…")
        try:
            remote_size = self.sftp.stat(self.selected_file).st_size
            with self.sftp.open(self.selected_file, 'rb') as remote_f, open(local_path, 'wb') as local_f:
                transferred = 0
                while True:
                    chunk = remote_f.read(64*1024)
                    if not chunk:
                        break
                    local_f.write(chunk)
                    transferred += len(chunk)
            self.status_lbl.setText(f"Downloaded to {local_path}")
            # Do not close dialog; allow user to keep browsing/downloading
        except Exception as e:
            self.status_lbl.setText(f"Download failed: {e}")
    def get_params(self):
        # Not used in browser mode, but kept for compatibility
        return {}
    def closeEvent(self, event):
        try:
            if self.sftp:
                self.sftp.close()
            if self.ssh:
                self.ssh.close()
        except Exception:
            pass
        super().closeEvent(event)

# Unified Main Widget (Send + Receive)

class UnifiedWidget(QWidget):
    def __init__(self):
        super().__init__()
        # Change: peers now maps ip -> (name, last_seen_timestamp)
        self.peers: Dict[str, Tuple[str, float]] = {}  # ip -> (name, last_seen)
        self._listener = ListenerThread()
        self._listener.new_peer.connect(self._add_peer)
        self._listener.start()
        self._thread = None  # ReceiverThread
        self._announcer = None  # AnnouncerThread
        self._save_dir = str(Path.home() / "Downloads")
        self._chosen_ip = None
        self._current_ip = get_local_ip()

        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(28, 24, 28, 24)

        # IP and port label
        self.ip_lbl = QLabel(f"Your IP: {self._current_ip}  ·  Port: {TCP_PORT}")
        self.ip_lbl.setStyleSheet("color: #90A4AE; font-size: 14px; margin-bottom: 2px;")
        layout.addWidget(self.ip_lbl)

        # Folder row
        row = QHBoxLayout()
        self.folder_lbl = QLabel(f"Destination: {self._save_dir}")
        self.folder_lbl.setStyleSheet("color: #607D8B; font-size: 14px;")
        choose_btn = QPushButton("Change…")
        choose_btn.setCursor(Qt.PointingHandCursor)
        choose_btn.setStyleSheet(
            """
            QPushButton {
                background: #E3F2FD;
                color: #1976D2;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                min-height: 36px;
                font-size: 15px;
            }
            QPushButton:hover {
                background: #BBDEFB;
            }
            """
        )
        choose_btn.clicked.connect(self._choose_folder)
        row.addWidget(self.folder_lbl)
        row.addWidget(choose_btn)
        layout.addLayout(row)

        # Peer list
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            """
            QListWidget {
                background: #F5F7FA;
                border: none;
                font-size: 15px;
                padding: 8px;
                border-radius: 10px;
            }
            QListWidget::item {
                padding: 10px 8px;
                border-radius: 8px;
            }
            QListWidget::item:selected {
                background: #E3F2FD;
                color: #1976D2;
            }
            """
        )
        self.list_widget.itemDoubleClicked.connect(self._select_peer)
        layout.addWidget(QLabel("Receivers on your network:"))
        layout.addWidget(self.list_widget)

        self._peer_timer = QTimer(self)
        self._peer_timer.timeout.connect(self._remove_stale_peers)
        self._peer_timer.start(2000)  # every 2 seconds

        # Timer to check for IP changes
        self._ip_timer = QTimer(self)
        self._ip_timer.timeout.connect(self._check_ip_change)
        self._ip_timer.start(2000)  # every 2 seconds

        # Drag area
        self.drag_area = DragLabel("Drop a file here to send →")
        self.drag_area.file_dropped.connect(self._send_file)
        layout.addWidget(self.drag_area)

        # Progress & status
        self.progress = QProgressBar(); self.progress.setValue(0)
        self.progress.setStyleSheet(
            """
            QProgressBar {
                border: none;
                border-radius: 8px;
                background: #ECEFF1;
                height: 18px;
                text-align: center;
                font-size: 13px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #42A5F5, stop:1 #1976D2);
                border-radius: 8px;
            }
            """
        )
        layout.addWidget(self.progress)
        self.status = QLabel(); self.status.setStyleSheet("color: #607D8B; font-size: 14px; margin-top: 4px;")
        layout.addWidget(self.status)

        # Shared note UI
        layout.addWidget(QLabel("Shared Note:"))
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Type or paste note here…")
        self.note_edit.setFixedHeight(120)
        self.note_edit.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.note_edit)
        note_btn_row = QHBoxLayout()
        send_note_btn = QPushButton("Send Note")
        send_note_btn.setCursor(Qt.PointingHandCursor)
        send_note_btn.setStyleSheet(
            """
            QPushButton {
                background: #1976D2;
                color: white;
                border: none;
                padding: 10px 24px;
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover { background: #1565C0; }
            """
        )
        send_note_btn.clicked.connect(self._send_note)
        note_btn_row.addStretch(1)
        note_btn_row.addWidget(send_note_btn)
        layout.addLayout(note_btn_row)

        # Start/stop + settings button row
        btn_row = QHBoxLayout()
        self.toggle_btn = QPushButton("Start Receiver")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet(
            """
            QPushButton {
                background: #1976D2;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 30px;
                min-height: 40px;
                font-size: 16px;
                font-weight: 500;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: #1565C0;
            }
            """
        )
        self.toggle_btn.clicked.connect(self._toggle)
        btn_row.addWidget(self.toggle_btn)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet(
            """
            QPushButton {
                background: #E3F2FD;
                color: #1976D2;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                min-height: 40px;
                font-size: 15px;
                font-weight: 500;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: #BBDEFB;
            }
            """
        )
        self.settings_btn.clicked.connect(self._open_settings)
        btn_row.addWidget(self.settings_btn)
        
        # Add SCP Download button
        self.scp_btn = QPushButton("SCP Download")
        self.scp_btn.setCursor(Qt.PointingHandCursor)
        self.scp_btn.setStyleSheet(
            """
            QPushButton {
                background: #E3F2FD;
                color: #1976D2;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                min-height: 40px;
                font-size: 15px;
                font-weight: 500;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: #BBDEFB;
            }
            """
        )
        self.scp_btn.clicked.connect(self._open_scp_dialog)
        btn_row.addWidget(self.scp_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    # Peer handling
    def _add_peer(self, ip: str, name: str):
        # Prevent self-discovery
        if ip == self._current_ip:
            return
        now = time.time()
        if ip in self.peers:
            # Update timestamp and name if changed
            old_name, _ = self.peers[ip]
            self.peers[ip] = (name, now)
            # If name changed, update UI
            if old_name != name:
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item.data(Qt.UserRole) == ip:
                        item.setText(f"{name} ({ip})")
                        break
        else:
            self.peers[ip] = (name, now)
            item = QListWidgetItem(f"{name} ({ip})")
            item.setData(Qt.UserRole, ip)
            self.list_widget.addItem(item)

    def _remove_stale_peers(self):
        # Remove peers not seen in the last 2 × ANNOUNCE_INTERVAL seconds
        threshold = time.time() - 2 * ANNOUNCE_INTERVAL
        to_remove = [ip for ip, (_, last_seen) in self.peers.items() if last_seen < threshold]
        for ip in to_remove:
            del self.peers[ip]
            # Remove from list_widget
            for i in range(self.list_widget.count() - 1, -1, -1):
                item = self.list_widget.item(i)
                if item.data(Qt.UserRole) == ip:
                    self.list_widget.takeItem(i)
                    break
            # Deselect if the removed peer was selected
            if self._chosen_ip == ip:
                self._chosen_ip = None
                self.status.setText("")

    def _select_peer(self, item: QListWidgetItem):
        ip = item.data(Qt.UserRole)
        self._chosen_ip = ip
        self.status.setText(f"Selected {ip}")

    # File sending
    def _send_file(self, path):
        if not self._chosen_ip:
            QMessageBox.warning(self, "No receiver selected", "Please double-click a receiver in the list first.")
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Invalid file", "Please drop a valid file.")
            return
        filesize = os.path.getsize(path)
        fname = os.path.basename(path)
        try:
            self.progress.setValue(0)
            sock = socket.create_connection((self._chosen_ip, TCP_PORT), timeout=5)
            sock.sendall(struct.pack("!I", len(fname)))
            sock.sendall(fname.encode())
            sock.sendall(struct.pack("!Q", filesize))
            sent = 0
            start = time.perf_counter()
            with open(path, "rb") as f:
                while chunk := f.read(BUFFER_SIZE):
                    sock.sendall(chunk)
                    sent += len(chunk)
                    elapsed = max(time.perf_counter() - start, 1e-3)
                    speed = (sent / (1024 ** 2)) / elapsed
                    percent = int(sent / filesize * 100)
                    self.progress.setValue(percent)
                    self.status.setText(f"{percent}% • {speed:.1f} MB/s")
            self.status.setText(f"Sent {fname} ✓")
            self.progress.setValue(100)
        except Exception as e:
            self.status.setText(f"⚠ {e}")
            self.progress.setValue(0)

    # Note sending / receiving
    def _send_note(self):
        if not self._chosen_ip:
            QMessageBox.warning(self, "No receiver selected", "Please double-click a receiver in the list first.")
            return
        text = self.note_edit.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "Empty note", "Nothing to send!")
            return
        data = text.encode()
        try:
            with socket.create_connection((self._chosen_ip, TCP_PORT), timeout=5) as sock:
                sock.sendall(NOTE_HEADER)
                sock.sendall(struct.pack("!I", len(data)))
                sock.sendall(data)
            self.status.setText("Note sent ✓")
        except Exception as e:
            self.status.setText(f"⚠ {e}")

    def receive_note(self, text: str):
        cursor = self.note_edit.textCursor()
        self.note_edit.blockSignals(True)
        self.note_edit.setPlainText(text)
        self.note_edit.blockSignals(False)
        self.note_edit.setTextCursor(cursor)

    # Folder
    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", self._save_dir)
        if folder:
            self._save_dir = folder
            self.folder_lbl.setText(f"Destination: {folder}")

    # Receiver toggle
    def _toggle(self):
        if self._thread is None:
            # Start receiver + announcer
            self._thread = ReceiverThread(self._save_dir)
            self._thread.status.connect(self.status.setText)
            self._thread.progress.connect(self._update_progress)
            self._thread.start()
            self._thread.new_note.connect(self.receive_note)
            self._announcer = AnnouncerThread(socket.gethostname())
            self._announcer.start()
            self.toggle_btn.setText("Stop Receiver")
        else:
            # Stop
            self._thread.stop(); self._thread = None
            if self._announcer:
                self._announcer.stop(); self._announcer = None
            self.toggle_btn.setText("Start Receiver")
            self.status.setText("")
            self.progress.setValue(0)

    def _update_progress(self, percent, speed):
        self.progress.setValue(percent)
        self.status.setText(f"{percent}% • {speed:.1f} MB/s")

    def _open_settings(self):
        global settings, BUFFER_SIZE, ANNOUNCE_INTERVAL, TCP_PORT
        dlg = SettingsDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            new_settings = dlg.get_settings()
            settings.update(new_settings)
            BUFFER_SIZE = settings["BUFFER_SIZE"]
            ANNOUNCE_INTERVAL = settings["ANNOUNCE_INTERVAL"]
            TCP_PORT = settings["TCP_PORT"]
            save_settings(settings)
            self._current_ip = get_local_ip()
            self.ip_lbl.setText(f"Your IP: {self._current_ip}  ·  Port: {TCP_PORT}")

    def _check_ip_change(self):
        new_ip = get_local_ip()
        if new_ip != self._current_ip:
            self._current_ip = new_ip
            self.ip_lbl.setText(f"Your IP: {self._current_ip}  ·  Port: {TCP_PORT}")
            # Restart announcer if running
            if self._announcer:
                self._announcer.stop()
                self._announcer = AnnouncerThread(socket.gethostname())
                self._announcer.start()

    def _open_scp_dialog(self):
        dlg = SCPDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            params = dlg.get_params()
            if params:  # Only call if params are present (old mode)
                self._scp_download(**params)

    def _scp_download(self, ip, port, username, password, remote_path, local_dir):
        try:
            import paramiko
            from paramiko import SSHClient
            import threading
            from PyQt5.QtWidgets import QApplication
        except ImportError:
            QMessageBox.critical(self, "Missing Dependency", "Please install paramiko: pip install paramiko")
            return
        self.status.setText("Connecting via SCP…")
        self.progress.setValue(0)
        def run():
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, port=port, username=username, password=password, timeout=10)
                sftp = ssh.open_sftp()
                remote_size = sftp.stat(remote_path).st_size
                local_path = os.path.join(local_dir, os.path.basename(remote_path))
                with sftp.open(remote_path, 'rb') as remote_f, open(local_path, 'wb') as local_f:
                    transferred = 0
                    while True:
                        chunk = remote_f.read(BUFFER_SIZE)
                        if not chunk:
                            break
                        local_f.write(chunk)
                        transferred += len(chunk)
                        percent = int(transferred / remote_size * 100) if remote_size else 0
                        speed = transferred / (1024*1024)  # MB, rough
                        QApplication.instance().postEvent(self.progress, type('QEvent', (), {'type': lambda: 1000})())
                        self.progress.setValue(percent)
                        self.status.setText(f"SCP: {percent}% • {human_size(transferred)} / {human_size(remote_size)}")
                sftp.close()
                ssh.close()
                self.status.setText(f"SCP: Downloaded {os.path.basename(remote_path)} ✓")
                self.progress.setValue(100)
            except Exception as e:
                self.status.setText(f"SCP Error: {e}")
                self.progress.setValue(0)
        threading.Thread(target=run, daemon=True).start()

# Settings dialog (optional / unchanged)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QFormLayout(self)

        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(4, 1024)
        self.buffer_spin.setSingleStep(8)
        self.buffer_spin.setValue(settings["BUFFER_SIZE"] // 1024)
        self.buffer_spin.setSuffix(" KB")
        layout.addRow("Buffer size:", self.buffer_spin)

        self.announce_spin = QDoubleSpinBox()
        self.announce_spin.setRange(0.5, 10.0)
        self.announce_spin.setSingleStep(0.1)
        self.announce_spin.setValue(settings["ANNOUNCE_INTERVAL"])
        self.announce_spin.setSuffix(" s")
        layout.addRow("Announce interval:", self.announce_spin)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(settings["TCP_PORT"])
        layout.addRow("TCP port:", self.port_spin)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_settings(self):
        return {
            "BUFFER_SIZE": self.buffer_spin.value() * 1024,
            "ANNOUNCE_INTERVAL": self.announce_spin.value(),
            "TCP_PORT": self.port_spin.value(),
        }

# Main Window

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Drop")
        # Set icon for all platforms
        from PyQt5.QtGui import QIcon
        import sys
        if sys.platform == "darwin":
            try:
                import AppKit
                from PyQt5.QtCore import QFileInfo
                nsimage = AppKit.NSImage.alloc().initByReferencingFile_(ICON_PATH)
                if nsimage:
                    AppKit.NSApplication.sharedApplication().setApplicationIconImage_(nsimage)
            except Exception:
                # Fallback to PyQt5 icon if pyobjc is not available
                self.setWindowIcon(QIcon(ICON_PATH))
        else:
            self.setWindowIcon(QIcon(ICON_PATH))
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0)
        unified = UnifiedWidget()
        v.addWidget(unified)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Force light mode
    from PyQt5.QtGui import QPalette, QColor
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(255, 255, 255))
    palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.Base, QColor(245, 245, 245))
    palette.setColor(QPalette.AlternateBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText, QColor(0, 0, 0))
    palette.setColor(QPalette.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Link, QColor(0, 120, 215))
    palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    win = MainWindow(); win.resize(640, 680); win.show()
    if app.exec_() == 0:
        save_settings(settings)
