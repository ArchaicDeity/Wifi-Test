# Installation:
# pip install PyQt6 pyqtgraph speedtest-cli pandas matplotlib requests plotly

import sys
import os
import threading  # For threading.Lock
import time
import datetime
import subprocess
import csv
import json
import queue
import socket
import shutil
from collections import deque

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QTabWidget,
    QFormLayout,
    QGroupBox,
    QPlainTextEdit,
    QSystemTrayIcon,
    QMenu,
    QStyle,
    QMessageBox,
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import (
    QThread,
    QObject,
    pyqtSignal,
    QRunnable,
    QThreadPool,
    QTimer,
)

import psutil

import pyqtgraph as pg

import pandas as pd

import plotly.express as px

# Do NOT import the Python `speedtest` package at top-level. Some
# distributions execute code at import-time which can crash frozen
# executables. We'll use a CLI-based speedtest runner instead and
# optionally use the Python library only when explicitly available
# and safe (not done at import time).
speedtest = None

try:
    import requests
except ImportError:
    requests = None

# On non-Windows, CREATE_NO_WINDOW may not exist; make it safe
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# --- Constants ---
CSV_LOG_FILE = "network_log.csv"
READABLE_LOG_FILE = "network_readable.log"
SUMMARY_JSON_FILE = "summary_report.json"

CSV_HEADER = [
    "timestamp",
    "latency_ms",
    "jitter_ms",
    "dns_latency_ms",
    "http_ttfb_ms",
    "http_status_code",
    "packet_loss",
    "event",
    "download_mbps",
    "upload_mbps",
    "wifi_signal_percent",
]

PING_PLOT_DATA_POINTS = 300  # Number of data points shown on graphs
UI_UPDATE_INTERVAL_MS = 250  # Graph refresh interval
BPS_TO_MBPS = 1_000_000


# ==============================================================================
# Generic Worker for QThreadPool
# ==============================================================================
class Runnable(QRunnable):
    """Generic QRunnable wrapper for arbitrary callables."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        self.fn(*self.args, **self.kwargs)


# ==============================================================================
# Background Worker
# ==============================================================================
class NetworkWorker(QObject):
    """Handles all network monitoring in a background thread."""

    new_ping_result = pyqtSignal(dict)
    new_speed_result = pyqtSignal(dict)
    log_message = pyqtSignal(str)
    disconnected = pyqtSignal()
    reconnected = pyqtSignal(float)
    finished = pyqtSignal()
    traceroute_finished = pyqtSignal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.target_ips = settings['target_ips']
        self._is_running = False
        self.thread_pool = QThreadPool.globalInstance()
        self.speed_test_result_queue = queue.Queue()
        self.prev_net_counters = None
        self.prev_net_time = None

    # ------------------------------------------------------------------ PING --
    def _get_ping_command(self):
        """Returns the ping command (Windows style)."""
        # This app is primarily for Windows; we still guard for interval
        return [
            "ping",
            "-n",
            "1",
            "-w",
            str(int(self.settings["interval_s"] * 1000)),
        ]

    def _ping_host(self, host: str, command: list):
        """Pings a host and returns latency in ms, or None on failure."""
        try:
            output = subprocess.check_output(
                command + [host],
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in output.splitlines():
                if "time=" in line.lower():
                    # Extract number before "ms"
                    return float(line.lower().split("time=")[1].split("ms")[0])
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return None

    # --------------------------------------------------------------- SPEEDTEST --
    def _run_speed_test_task(self):
        """
        Safe speedtest runner using a bundled or system CLI. Always
        pushes a result dict into self.speed_test_result_queue.
        """
        # Prefer a bundled CLI executable (speedtest.exe) if included with
        # the app. When frozen, PyInstaller extracts data files to
        # sys._MEIPASS; otherwise look in local project 'extras/'.
        def find_cli():
            # Check frozen temp folder first
            base = getattr(sys, "_MEIPASS", None)
            if base:
                candidate = os.path.join(base, "speedtest.exe")
                if os.path.exists(candidate):
                    return candidate
            # Check local extras folder (during development)
            local_candidate = os.path.join(os.path.dirname(__file__), "extras", "speedtest.exe")
            if os.path.exists(local_candidate):
                return local_candidate
            # Finally, check PATH for common CLI names
            for name in ("speedtest", "speedtest.exe", "speedtest-cli"):
                path = shutil.which(name)
                if path:
                    return path
            return None

        path = find_cli()
        if path:
            try:
                self.log_message.emit(f"Running speedtest CLI: {os.path.basename(path)}")

                # Try several common JSON output flags for different CLI implementations
                flag_variants = [
                    ["-f", "json", "--accept-license", "--accept-gdpr"],
                    ["--format=json", "--accept-license", "--accept-gdpr"],
                    ["--json"],
                    ["--format=json"],
                    ["-f", "json"],
                    ["--format", "json"],
                    [],
                ]

                parsed = False
                last_exception = None
                for flags in flag_variants:
                    try:
                        cmd = [path] + flags
                        proc = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=60,
                            creationflags=CREATE_NO_WINDOW,
                        )
                        out = (proc.stdout or "").strip()
                        err = (proc.stderr or "").strip()

                        # Some CLIs write JSON to stderr on failure or to stdout on success.
                        candidate = out or err
                        if candidate:
                            try:
                                res = json.loads(candidate)
                                # Normalize speedtest result format
                                if isinstance(res.get("download"), dict):
                                    res["download"] = res["download"]["bandwidth"]
                                if isinstance(res.get("upload"), dict):
                                    res["upload"] = res["upload"]["bandwidth"]
                                self.speed_test_result_queue.put(res)
                                parsed = True
                                break
                            except Exception as pe:
                                snippet = out[:400] if out else "<empty stdout>"
                                err_snippet = err[:400] if err else "<empty stderr>"
                                self.log_message.emit(f"Attempt parse failed for flags {flags}: {pe!r}")
                                self.log_message.emit(f"Raw stdout snippet: {snippet!r}")
                                self.log_message.emit(f"Raw stderr snippet: {err_snippet!r}")
                                last_exception = pe
                        else:
                            self.log_message.emit(f"Speedtest CLI returned no output for flags {flags} (rc={proc.returncode}).")
                    except subprocess.TimeoutExpired:
                        self.log_message.emit(f"Speedtest CLI timed out for flags {flags}")
                    except Exception as e:
                        last_exception = e
                        self.log_message.emit(f"Speedtest CLI invocation error for flags {flags}: {e!r}")

                if parsed:
                    return
                if last_exception:
                    self.log_message.emit(f"CLI parse/invoke attempts exhausted: last error {last_exception!r}")
                else:
                    self.log_message.emit("CLI attempts exhausted with no usable output.")
            except subprocess.TimeoutExpired:
                self.log_message.emit("CLI speedtest timed out")
            except Exception as e:
                self.log_message.emit(f"CLI speedtest error: {e!r}")

        # As a last resort, try importing the Python `speedtest` package at runtime.
        try:
            self.log_message.emit("Falling back to Python 'speedtest' library (runtime import)...")
            import importlib

            st = importlib.import_module("speedtest")
            try:
                s = st.Speedtest()
                s.get_best_server()
                dl = s.download()
                ul = s.upload()
                res = {"download": int(dl), "upload": int(ul)}
                self.speed_test_result_queue.put(res)
                return
            except Exception as pe:
                self.log_message.emit(f"Python speedtest runtime failed: {pe!r}")
        except Exception as ie:
            self.log_message.emit(f"Python speedtest import not available: {ie!r}")

        # If we reached here, all attempts failed
        self.log_message.emit("All speedtest attempts failed.")
        self.speed_test_result_queue.put({"error": "all_failed"})

    # ------------------------------------------------------------ HEALTH CHECKS --
    def _get_http_health(self, url="https://www.google.com"):
        """Performs an HTTP health check and returns TTFB & status code."""
        if not requests:
            # Only log once in run loop; be quiet here
            return None
        try:
            start_time = time.perf_counter()
            response = requests.get(url, stream=True, timeout=5)
            ttfb = (time.perf_counter() - start_time) * 1000  # ms
            return {"ttfb_ms": ttfb, "status_code": response.status_code}
        except requests.exceptions.RequestException:
            return None

    # ------------------------------------------------------------ HEALTH CHECKS --
    def _get_dns_latency(self, domain="google.com"):
        """Measures DNS resolution time for a domain."""
        try:
            start_time = time.perf_counter()
            socket.gethostbyname(domain)
            return (time.perf_counter() - start_time) * 1000  # ms
        except socket.gaierror:
            return None

    def _get_wifi_signal(self):
        """Gets WiFi signal strength percentage (Windows only)."""
        try:
            output = subprocess.check_output(
                ["netsh", "wlan", "show", "interfaces"],
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in output.splitlines():
                if "Signal" in line and "%" in line:
                    # Extract percentage
                    signal_str = line.split(":")[1].strip().replace("%", "")
                    return int(signal_str)
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
            return None
        return None

    # ---------------------------------------------------------------- TRACEROUTE --
    def run_traceroute(self):
        """Runs 'tracert' (Windows) in a background pool thread."""

        def task():
            try:
                self.log_message.emit(
                    f"Running traceroute to {self.target_ips[0] if self.target_ips else '8.8.8.8'}..."
                )
                output = subprocess.check_output(
                    ["tracert", self.target_ips[0] if self.target_ips else "8.8.8.8"],
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                self.traceroute_finished.emit(output)
                self.log_message.emit("✅ Traceroute completed.")
            except Exception as e:
                msg = f"❌ Traceroute failed: {e!r}"
                self.traceroute_finished.emit(msg)
                self.log_message.emit(msg)

        self.thread_pool.start(Runnable(task))

    # --------------------------------------------------------------------- RUN --
    def run(self):
        """Main monitoring loop."""
        self._is_running = True

        latencies = deque(maxlen=20)
        is_disconnected = False
        disconnect_start_time = 0.0
        last_speed_test_time = 0.0
        ping_command = self._get_ping_command()

        with open(CSV_LOG_FILE, "w", newline="", encoding="utf-8") as csvfile, open(
            READABLE_LOG_FILE, "w", encoding="utf-8"
        ) as readablefile:
            csv_writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADER)
            csv_writer.writeheader()

            def log_csv(data: dict):
                data = dict(data)  # copy
                data["timestamp"] = datetime.datetime.now().isoformat()
                csv_writer.writerow({k: data.get(k, "") for k in CSV_HEADER})
                csvfile.flush()

            def log_readable(message: str):
                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                full_message = f"{timestamp} – {message}"
                readablefile.write(full_message + "\n")
                readablefile.flush()
                self.log_message.emit(full_message)

            log_readable("Monitoring started.")

            while self._is_running:
                try:
                    # ---------------- Process pending speed results ----------------
                    try:
                        speed_result = self.speed_test_result_queue.get_nowait()
                        if "error" not in speed_result:
                            download_mbps = speed_result["download"] / BPS_TO_MBPS
                            upload_mbps = speed_result["upload"] / BPS_TO_MBPS
                            log_csv(
                                {
                                    "event": "Speed Test",
                                    "download_mbps": round(download_mbps, 2),
                                    "upload_mbps": round(upload_mbps, 2),
                                }
                            )
                            self.new_speed_result.emit(speed_result)
                            log_readable(
                                f"✅ Speedtest: DL {download_mbps:.2f} Mbps / "
                                f"UL {upload_mbps:.2f} Mbps"
                            )
                        else:
                            log_csv({"event": f"Speedtest Failed ({speed_result['error']})"})
                            log_readable(
                                f"❌ Speedtest failed ({speed_result['error']}). "
                                "See logs for details."
                            )
                    except queue.Empty:
                        pass

                    # ---------------- DNS + HTTP + Ping ----------------
                    dns_latency = self._get_dns_latency()
                    http_health = self._get_http_health()
                    wifi_signal = self._get_wifi_signal()

                    # Bandwidth
                    current_counters = psutil.net_io_counters()
                    current_time = time.time()
                    bandwidth_dl = 0
                    bandwidth_ul = 0
                    if self.prev_net_counters:
                        delta_time = current_time - self.prev_net_time
                        if delta_time > 0:
                            bandwidth_dl = (current_counters.bytes_recv - self.prev_net_counters.bytes_recv) / delta_time / 1024 / 1024 * 8
                            bandwidth_ul = (current_counters.bytes_sent - self.prev_net_counters.bytes_sent) / delta_time / 1024 / 1024 * 8
                    self.prev_net_counters = current_counters
                    self.prev_net_time = current_time

                    latency = None
                    if self.target_ips:
                        latencies = []
                        for target_ip in self.target_ips:
                            lat = self._ping_host(target_ip, ping_command)
                            if lat is not None:
                                latencies.append(lat)
                        if latencies:
                            latency = sum(latencies) / len(latencies)

                    http_ttfb = http_health["ttfb_ms"] if http_health else None
                    http_status = http_health["status_code"] if http_health else None

                    if latency is not None:
                        # Reconnection event
                        if is_disconnected:
                            outage_duration = time.time() - disconnect_start_time
                            self.reconnected.emit(outage_duration)
                            log_readable(
                                f"✅ Reconnected after {outage_duration:.2f} seconds."
                            )
                            log_csv(
                                {
                                    "event": f"Reconnected after {outage_duration:.2f}s",
                                }
                            )
                            is_disconnected = False

                        # Jitter based on previous latency
                        jitter = abs(latency - latencies[-1]) if latencies else 0.0
                        latencies.append(latency)

                        self.new_ping_result.emit(
                            {
                                "latency": latency,
                                "jitter": jitter,
                                "dns_latency": dns_latency,
                                "http_latency": http_ttfb,
                                "wifi_signal": wifi_signal,
                                'bandwidth_dl_mbps': bandwidth_dl,
                                'bandwidth_ul_mbps': bandwidth_ul,
                            }
                        )
                        log_csv(
                            {
                                "latency_ms": latency,
                                "jitter_ms": round(jitter, 2),
                                "dns_latency_ms": dns_latency,
                                "http_ttfb_ms": http_ttfb,
                                "http_status_code": http_status,
                                "packet_loss": 0.0,
                                "wifi_signal_percent": wifi_signal,
                            }
                        )
                    else:
                        # Disconnected
                        if not is_disconnected:
                            is_disconnected = True
                            disconnect_start_time = time.time()
                            self.disconnected.emit()
                            self.run_traceroute()
                            log_readable(
                                "❌ DISCONNECTED – starting automated traceroute..."
                            )

                        log_csv(
                            {
                                "packet_loss": 1.0,
                                "jitter_ms": "",
                                "dns_latency_ms": dns_latency,
                                "http_ttfb_ms": http_ttfb,
                                "http_status_code": http_status,
                                "event": "Disconnected",
                                "wifi_signal_percent": wifi_signal,
                            }
                        )

                    # ---------------- Schedule speedtest ----------------
                    if self.settings["speedtest_enabled"] and not is_disconnected:
                        now = time.time()
                        time_since_last = (now - last_speed_test_time) / 60
                        log_readable(f"Speedtest check: enabled, not disconnected, time since last {time_since_last:.1f} min, interval {self.settings['speedtest_interval_min']} min")
                        if time_since_last >= self.settings["speedtest_interval_min"]:
                            self.thread_pool.start(
                                Runnable(self._run_speed_test_task)
                            )
                            last_speed_test_time = now
                            log_readable("🚀 Speedtest scheduled.")
                        else:
                            log_readable(f"Speedtest not due yet: {time_since_last:.1f} < {self.settings['speedtest_interval_min']}")
                    else:
                        log_readable(f"Speedtest not checked: enabled={self.settings['speedtest_enabled']}, disconnected={is_disconnected}")

                    time.sleep(self.settings["interval_s"])
                except Exception as e:
                    log_readable(f"❌ Fatal error in monitoring loop: {e!r}")
                    break  # Exit the loop on error

            log_readable("Monitoring stopped.")

        self.finished.emit()

    def stop(self):
        self._is_running = False


# ==============================================================================
# GUI Application
# ==============================================================================
class NetworkMonitorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Monitor GUI (Windows)")
        self.setGeometry(100, 100, 1200, 800)

        self.worker_thread: QThread | None = None
        self.network_worker: NetworkWorker | None = None
        self.is_quitting = False  # Distinguish quit vs. hide-to-tray

        # --- Data stores ---
        self.ping_data_lock = threading.Lock()
        self.ping_data_buffer: list[dict] = []

        self.time_data = deque(maxlen=PING_PLOT_DATA_POINTS)
        self.latency_data = deque(maxlen=PING_PLOT_DATA_POINTS)
        self.jitter_data = deque(maxlen=PING_PLOT_DATA_POINTS)
        self.dns_latency_data = deque(maxlen=PING_PLOT_DATA_POINTS)
        self.http_latency_data = deque(maxlen=PING_PLOT_DATA_POINTS)
        self.wifi_signal_data = deque(maxlen=PING_PLOT_DATA_POINTS)

        self.speed_time_data: list[float] = []
        self.download_speeds: list[float] = []
        self.upload_speeds: list[float] = []

        self.start_time = 0.0
        self.disconnect_count = 0
        self.longest_outage = 0.0
        self.ping_count = 0
        self.total_latency = 0.0
        self.max_jitter = 0.0
        self.dns_count = 0
        self.total_dns_latency = 0.0
        self.http_count = 0
        self.total_http_latency = 0.0

        self._init_ui()
        self._init_tray_icon()

        self.graph_update_timer = QTimer(self)
        self.graph_update_timer.setInterval(UI_UPDATE_INTERVAL_MS)
        self.graph_update_timer.timeout.connect(self.process_graph_updates)

    # ---------------------------------------------------------------- TRAY ICON --
    def _init_tray_icon(self):
        style = self.style()
        self.icon_green = QIcon(
            style.standardPixmap(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.icon_yellow = QIcon(
            style.standardPixmap(QStyle.StandardPixmap.SP_MessageBoxWarning)
        )
        self.icon_red = QIcon(
            style.standardPixmap(QStyle.StandardPixmap.SP_MessageBoxCritical)
        )

        self.tray_icon = QSystemTrayIcon(self.icon_green, self)
        self.tray_icon.setToolTip("Network Monitor")

        tray_menu = QMenu()
        show_hide_action = QAction("Show / Hide", self, triggered=self.toggle_window_visibility)
        quit_action = QAction("Quit", self, triggered=self.quit_application)
        tray_menu.addAction(show_hide_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.show()

    def toggle_window_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_window_visibility()

    def quit_application(self):
        self.is_quitting = True
        self.close()

    # --------------------------------------------------------------- UI SETUP --
    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # -------- Top control + settings row --------
        top_panel_layout = QHBoxLayout()
        main_layout.addLayout(top_panel_layout)

        control_box = QGroupBox("Controls")
        control_layout = QHBoxLayout()
        control_box.setLayout(control_layout)

        self.start_stop_button = QPushButton("Start")
        self.start_stop_button.clicked.connect(self.toggle_monitoring)
        control_layout.addWidget(self.start_stop_button)

        self.save_report_button = QPushButton("Save Report")
        self.save_report_button.clicked.connect(self.save_reports)
        self.save_report_button.setEnabled(False)
        control_layout.addWidget(self.save_report_button)

        self.open_reports_button = QPushButton("Open Reports Folder")
        self.open_reports_button.clicked.connect(self.open_reports_folder)
        control_layout.addWidget(self.open_reports_button)

        top_panel_layout.addWidget(control_box)

        # Settings box
        settings_box = QGroupBox("Settings")
        settings_layout = QFormLayout()
        settings_box.setLayout(settings_layout)
        top_panel_layout.addWidget(settings_box, 1)

        self.interval_spinbox = QDoubleSpinBox()
        self.interval_spinbox.setRange(0.5, 60.0)
        self.interval_spinbox.setValue(2.0)
        self.interval_spinbox.setSuffix(" s")
        settings_layout.addRow("Ping Interval:", self.interval_spinbox)

        self.target_ip_input = QLineEdit("8.8.8.8")
        settings_layout.addRow("Target IP:", self.target_ip_input)

        self.speedtest_checkbox = QCheckBox("Enable Periodic Speed Tests")
        settings_layout.addRow(self.speedtest_checkbox)

        self.speedtest_interval_spinbox = QSpinBox()
        self.speedtest_interval_spinbox.setRange(1, 1440)
        self.speedtest_interval_spinbox.setValue(30)
        self.speedtest_interval_spinbox.setSuffix(" min")
        settings_layout.addRow("Speed Test Interval:", self.speedtest_interval_spinbox)

        self.latency_threshold_spinbox = QSpinBox()
        self.latency_threshold_spinbox.setRange(10, 1000)
        self.latency_threshold_spinbox.setValue(150)
        self.latency_threshold_spinbox.setSuffix(" ms")
        settings_layout.addRow("Latency Alert Threshold:", self.latency_threshold_spinbox)

        self.wifi_threshold_spinbox = QSpinBox()
        self.wifi_threshold_spinbox.setRange(0, 100)
        self.wifi_threshold_spinbox.setValue(50)
        self.wifi_threshold_spinbox.setSuffix(" %")
        settings_layout.addRow("WiFi Signal Alert Threshold:", self.wifi_threshold_spinbox)

        # Tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Graphs tab
        graphs_tab = QWidget()
        graphs_layout = QVBoxLayout(graphs_tab)
        self.tabs.addTab(graphs_tab, "Real-Time Graphs")

        self.ping_plot_widget = pg.PlotWidget()
        graphs_layout.addWidget(self.ping_plot_widget)
        self.ping_plot_widget.setLabel("left", "Latency / Jitter (ms)")
        self.ping_plot_widget.setLabel("bottom", "Time (s)")
        self.ping_plot_widget.addLegend()

        self.latency_curve = self.ping_plot_widget.plot(pen="b", name="Latency")
        self.jitter_curve = self.ping_plot_widget.plot(pen="g", name="Jitter")
        self.dns_latency_curve = self.ping_plot_widget.plot(
            pen="y", name="DNS Latency"
        )
        self.http_latency_curve = self.ping_plot_widget.plot(
            pen="c", name="HTTP TTFB"
        )
        self.wifi_signal_curve = self.ping_plot_widget.plot(
            pen="m", name="WiFi Signal %"
        )
        self.packet_loss_scatter = pg.ScatterPlotItem(
            pen=None, symbol="x", brush="r", size=15, name="Packet Loss"
        )
        self.ping_plot_widget.addItem(self.packet_loss_scatter)

        self.speed_plot_widget = pg.PlotWidget()
        graphs_layout.addWidget(self.speed_plot_widget)
        self.speed_plot_widget.setLabel("left", "Speed (Mbps)")
        self.speed_plot_widget.setLabel("bottom", "Time (s)")
        self.speed_plot_widget.addLegend()
        self.download_curve = self.speed_plot_widget.plot(
            pen="c", symbol="o", name="Download"
        )
        self.upload_curve = self.speed_plot_widget.plot(
            pen="m", symbol="o", name="Upload"
        )

        # Bandwidth tab
        bandwidth_tab = QWidget()
        bandwidth_layout = QVBoxLayout(bandwidth_tab)
        self.bandwidth_graph = pg.PlotWidget()
        bandwidth_layout.addWidget(self.bandwidth_graph)
        self.bandwidth_graph.setLabel("left", "Bandwidth (Mbps)")
        self.bandwidth_graph.setLabel("bottom", "Time (s)")
        self.bandwidth_graph.addLegend()
        self.bandwidth_dl_curve = self.bandwidth_graph.plot(pen='g', name='Download')
        self.bandwidth_ul_curve = self.bandwidth_graph.plot(pen='r', name='Upload')
        self.tabs.addTab(bandwidth_tab, "Bandwidth")

        # Logs tab
        self.log_text_edit = QPlainTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.tabs.addTab(self.log_text_edit, "Logs")

        # Summary tab
        summary_tab = QWidget()
        self.summary_layout = QFormLayout(summary_tab)
        self.tabs.addTab(summary_tab, "Summary")
        self._init_summary_labels()

        # Traceroute tab
        traceroute_tab = QWidget()
        traceroute_layout = QVBoxLayout(traceroute_tab)
        self.run_traceroute_button = QPushButton("Run Traceroute")
        self.run_traceroute_button.clicked.connect(self.run_traceroute)
        self.run_speedtest_button = QPushButton("Run Speedtest Now")
        self.run_speedtest_button.clicked.connect(self.run_speedtest_now)
        self.traceroute_output = QPlainTextEdit()
        self.traceroute_output.setReadOnly(True)
        traceroute_layout.addWidget(self.run_traceroute_button)
        traceroute_layout.addWidget(self.run_speedtest_button)
        traceroute_layout.addWidget(self.traceroute_output)
        self.tabs.addTab(traceroute_tab, "Traceroute")

    def _init_summary_labels(self):
        while self.summary_layout.rowCount() > 0:
            self.summary_layout.removeRow(0)

        self.summary_duration = QLabel("N/A")
        self.summary_layout.addRow("Total Test Duration:", self.summary_duration)

        self.summary_disconnects = QLabel("N/A")
        self.summary_layout.addRow("Number of Disconnects:", self.summary_disconnects)

        self.summary_longest_outage = QLabel("N/A")
        self.summary_layout.addRow("Longest Outage:", self.summary_longest_outage)

        self.summary_avg_latency = QLabel("N/A")
        self.summary_layout.addRow("Average Latency:", self.summary_avg_latency)

        self.summary_max_jitter = QLabel("N/A")
        self.summary_layout.addRow("Maximum Jitter:", self.summary_max_jitter)

        self.summary_avg_dns_latency = QLabel("N/A")
        self.summary_layout.addRow("Average DNS Latency:", self.summary_avg_dns_latency)

        self.summary_avg_http_ttfb = QLabel("N/A")
        self.summary_layout.addRow(
            "Average HTTP TTFB:", self.summary_avg_http_ttfb
        )

        self.summary_avg_wifi = QLabel("N/A")
        self.summary_layout.addRow("Average WiFi Signal:", self.summary_avg_wifi)

        self.summary_avg_download = QLabel("N/A")
        self.summary_layout.addRow(
            "Average Download Speed:", self.summary_avg_download
        )

        self.summary_avg_upload = QLabel("N/A")
        self.summary_layout.addRow("Average Upload Speed:", self.summary_avg_upload)

        self.summary_packet_loss = QLabel("0.0%")
        self.summary_layout.addRow("Packet Loss %:", self.summary_packet_loss)

    # ------------------------------------------------------------ MONITOR CTRL --
    def toggle_monitoring(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        self.start_stop_button.setText("Stop")
        self.save_report_button.setEnabled(False)
        self._reset_data_and_summary()

        settings = {
            "interval_s": self.interval_spinbox.value(),
            "target_ips": [ip.strip() for ip in self.target_ip_input.text().split(',') if ip.strip()],
            "speedtest_enabled": self.speedtest_checkbox.isChecked(),
            "speedtest_interval_min": self.speedtest_interval_spinbox.value(),
            "latency_threshold_ms": self.latency_threshold_spinbox.value(),
            "wifi_threshold_percent": self.wifi_threshold_spinbox.value(),
        }

        self.settings = settings

        self.start_time = time.time()

        self.worker_thread = QThread()
        self.network_worker = NetworkWorker(settings)
        self.network_worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.network_worker.run)
        self.network_worker.finished.connect(self.on_worker_finished)

        self.network_worker.log_message.connect(
            self.log_text_edit.appendPlainText
        )
        self.network_worker.new_ping_result.connect(self.buffer_ping_data)
        self.network_worker.new_speed_result.connect(self.update_speed_graphs)
        self.network_worker.disconnected.connect(self.on_disconnect)
        self.network_worker.reconnected.connect(self.on_reconnect)
        self.network_worker.traceroute_finished.connect(
            self.on_traceroute_finished
        )

        self.graph_update_timer.start()
        self.worker_thread.start()

    def stop_monitoring(self):
        if self.network_worker:
            self.network_worker.stop()
        self.start_stop_button.setText("Stopping...")
        self.start_stop_button.setEnabled(False)
        self.graph_update_timer.stop()

    def on_worker_finished(self):
        self.start_stop_button.setText("Start")
        self.start_stop_button.setEnabled(True)
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
        self.worker_thread = None
        self.save_report_button.setEnabled(True)
        self.update_summary_tab()

    def _reset_data_and_summary(self):
        self.ping_data_buffer.clear()
        self.time_data.clear()
        self.latency_data.clear()
        self.jitter_data.clear()
        self.dns_latency_data.clear()
        self.http_latency_data.clear()
        self.wifi_signal_data.clear()

        self.latency_curve.setData([], [])
        self.jitter_curve.setData([], [])
        self.dns_latency_curve.setData([], [])
        self.http_latency_curve.setData([], [])
        self.wifi_signal_curve.setData([], [])
        self.packet_loss_scatter.setData([])

        self.speed_time_data.clear()
        self.download_speeds.clear()
        self.upload_speeds.clear()
        self.download_curve.setData([], [])
        self.upload_curve.setData([], [])

        self.disconnect_count = 0
        self.longest_outage = 0.0
        self.ping_count = 0
        self.total_latency = 0.0
        self.max_jitter = 0.0
        self.dns_count = 0
        self.total_dns_latency = 0.0
        self.http_count = 0
        self.total_http_latency = 0.0

        self.alert_shown = False
        self.packet_loss_history = deque(maxlen=100)
        self.bandwidth_dl_data = deque(maxlen=PING_PLOT_DATA_POINTS)
        self.bandwidth_ul_data = deque(maxlen=PING_PLOT_DATA_POINTS)

        for i in range(self.summary_layout.rowCount()):
            widget = self.summary_layout.itemAt(
                i, QFormLayout.ItemRole.FieldRole
            ).widget()
            if isinstance(widget, QLabel):
                widget.setText("N/A")

        self.log_text_edit.clear()
        self.traceroute_output.clear()

    # --------------------------------------------------------------- GRAPHING --
    def buffer_ping_data(self, data: dict):
        with self.ping_data_lock:
            self.ping_data_buffer.append(data)

    def process_graph_updates(self):
        with self.ping_data_lock:
            if not self.ping_data_buffer:
                # Still keep summary updated
                self.update_summary_tab()
                return
            local_buffer = self.ping_data_buffer[:]
            self.ping_data_buffer.clear()

        LATENCY_WARNING_THRESHOLD_MS = 150
        JITTER_WARNING_THRESHOLD_MS = 50
        is_warning = False

        for data in local_buffer:
            current_time = time.time() - self.start_time
            self.time_data.append(current_time)

            latency = data["latency"]
            jitter = data["jitter"]

            self.latency_data.append(latency)
            self.jitter_data.append(jitter)
            self.ping_count += 1
            self.total_latency += latency
            self.max_jitter = max(self.max_jitter, jitter)

            if (
                latency > LATENCY_WARNING_THRESHOLD_MS
                or jitter > JITTER_WARNING_THRESHOLD_MS
            ):
                is_warning = True

            dns_latency_val = data.get("dns_latency")
            if dns_latency_val is not None:
                self.dns_latency_data.append(dns_latency_val)
                self.total_dns_latency += dns_latency_val
                self.dns_count += 1
            else:
                self.dns_latency_data.append(0.0)

            http_latency_val = data.get("http_latency")
            if http_latency_val is not None:
                self.http_latency_data.append(http_latency_val)
                self.total_http_latency += http_latency_val
                self.http_count += 1
            else:
                self.http_latency_data.append(0.0)

            wifi_signal_val = data.get("wifi_signal")
            if wifi_signal_val is not None:
                self.wifi_signal_data.append(wifi_signal_val)
            else:
                self.wifi_signal_data.append(0)

            self.packet_loss_history.append(1 if latency is None else 0)
            self.bandwidth_dl_data.append(data.get('bandwidth_dl_mbps', 0))
            self.bandwidth_ul_data.append(data.get('bandwidth_ul_mbps', 0))

        # Tray icon status (if not currently in red from disconnect)
        if self.tray_icon.icon().cacheKey() != self.icon_red.cacheKey():
            if is_warning:
                self.tray_icon.setIcon(self.icon_yellow)
                self.tray_icon.setToolTip("Network Status: Unstable")
            else:
                self.tray_icon.setIcon(self.icon_green)
                self.tray_icon.setToolTip("Network Status: Connected")

        self.latency_curve.setData(list(self.time_data), list(self.latency_data))
        self.jitter_curve.setData(list(self.time_data), list(self.jitter_data))
        self.dns_latency_curve.setData(
            list(self.time_data), list(self.dns_latency_data)
        )
        self.http_latency_curve.setData(
            list(self.time_data), list(self.http_latency_data)
        )
        self.bandwidth_dl_curve.setData(list(self.time_data), list(self.bandwidth_dl_data))
        self.bandwidth_ul_curve.setData(list(self.time_data), list(self.bandwidth_ul_data))

        # Alert logic
        if self.latency_data:
            current_latency = self.latency_data[-1]
            current_wifi = self.wifi_signal_data[-1] if self.wifi_signal_data else None
            if (current_latency > self.settings['latency_threshold_ms'] or 
                (current_wifi is not None and current_wifi < self.settings['wifi_threshold_percent'])):
                if not self.alert_shown:
                    self.tray_icon.showMessage("Network Alert", f"Latency > {self.settings['latency_threshold_ms']}ms or WiFi < {self.settings['wifi_threshold_percent']}%", QSystemTrayIcon.MessageIcon.Warning)
                    self.alert_shown = True
            else:
                self.alert_shown = False

        self.update_summary_tab()

    def update_speed_graphs(self, data: dict):
        current_time = time.time() - self.start_time
        download_mbps = data["download"] / BPS_TO_MBPS
        upload_mbps = data["upload"] / BPS_TO_MBPS

        self.speed_time_data.append(current_time)
        self.download_speeds.append(download_mbps)
        self.upload_speeds.append(upload_mbps)

        self.download_curve.setData(self.speed_time_data, self.download_speeds)
        self.upload_curve.setData(self.speed_time_data, self.upload_speeds)

        self.log_text_edit.appendPlainText(
            f"🚀 Speedtest: DL {download_mbps:.2f} Mbps / "
            f"UL {upload_mbps:.2f} Mbps"
        )
        self.log_text_edit.appendPlainText(
            f"Speed graph updated with {len(self.speed_time_data)} points."
        )
        self.update_summary_tab()

    # ------------------------------------------------------------- EVENTS/SUM --
    def on_disconnect(self):
        current_time = time.time() - self.start_time
        y = max(self.latency_data) if self.latency_data else 100.0
        self.packet_loss_scatter.addPoints(
            [{"pos": (current_time, y), "symbol": "x", "brush": "r"}]
        )
        self.disconnect_count += 1
        self.tray_icon.setIcon(self.icon_red)
        self.tray_icon.setToolTip("Network Status: Disconnected")

    def on_reconnect(self, outage_duration: float):
        self.longest_outage = max(self.longest_outage, outage_duration)
        self.tray_icon.setIcon(self.icon_green)
        self.tray_icon.setToolTip("Network Status: Connected")

    def update_summary_tab(self):
        total_duration = time.time() - self.start_time if self.start_time else 0.0
        self.summary_duration.setText(f"{total_duration:.1f} seconds")
        self.summary_disconnects.setText(str(self.disconnect_count))
        self.summary_longest_outage.setText(f"{self.longest_outage:.1f} seconds")

        avg_latency = (
            self.total_latency / self.ping_count if self.ping_count > 0 else 0.0
        )
        self.summary_avg_latency.setText(f"{avg_latency:.2f} ms")
        self.summary_max_jitter.setText(f"{self.max_jitter:.2f} ms")

        avg_dns_latency = (
            self.total_dns_latency / self.dns_count if self.dns_count > 0 else 0.0
        )
        self.summary_avg_dns_latency.setText(f"{avg_dns_latency:.2f} ms")

        avg_http_latency = (
            self.total_http_latency / self.http_count if self.http_count > 0 else 0.0
        )
        self.summary_avg_http_ttfb.setText(f"{avg_http_latency:.2f} ms")

        avg_wifi = (
            sum(self.wifi_signal_data) / len(self.wifi_signal_data)
            if self.wifi_signal_data
            else 0.0
        )
        self.summary_avg_wifi.setText(f"{avg_wifi:.1f} %")

        avg_dl = (
            sum(self.download_speeds) / len(self.download_speeds)
            if self.download_speeds
            else 0.0
        )
        self.summary_avg_download.setText(f"{avg_dl:.2f} Mbps")

        avg_ul = (
            sum(self.upload_speeds) / len(self.upload_speeds)
            if self.upload_speeds
            else 0.0
        )
        self.summary_avg_upload.setText(f"{avg_ul:.2f} Mbps")

        packet_loss_percent = sum(self.packet_loss_history) / len(self.packet_loss_history) * 100 if self.packet_loss_history else 0
        self.summary_packet_loss.setText(f"{packet_loss_percent:.1f}%")

    # ---------------------------------------------------------------- TRACEROUTE --
    def run_traceroute(self):
        if self.network_worker:
            self.traceroute_output.setPlainText("Running traceroute, please wait...")
            self.network_worker.run_traceroute()

    def on_traceroute_finished(self, output: str):
        self.traceroute_output.setPlainText(output)

    def run_speedtest_now(self):
        if self.network_worker:
            self.network_worker.thread_pool.start(
                Runnable(self.network_worker._run_speed_test_task)
            )
            self.log_text_edit.appendPlainText("Manual speedtest triggered.")
        else:
            self.log_text_edit.appendPlainText("Monitoring not started.")

    # ------------------------------------------------------------------ REPORTS --
    def save_reports(self):
        self.log_text_edit.appendPlainText("Generating final reports...")
        try:
            df = pd.read_csv(CSV_LOG_FILE)
            if df.empty:
                self.log_text_edit.appendPlainText("No data to generate reports.")
                return

            reports_dir = "reports"
            os.makedirs(reports_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

            df["timestamp"] = pd.to_datetime(df["timestamp"])

            # Create a comprehensive all-in-one report
            from plotly.subplots import make_subplots
            import plotly.graph_objects as go

            fig = make_subplots(
                rows=3, cols=1,
                subplot_titles=(
                    "Network Health Over Time",
                    "Speedtest Results Over Time",
                    "Summary Statistics"
                ),
                specs=[
                    [{"secondary_y": False}],
                    [{"secondary_y": False}],
                    [{"type": "table"}]
                ]
            )

            # Network health plot
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"],
                    y=df["latency_ms"],
                    mode='lines',
                    name='Latency (ms)',
                    line=dict(color='blue')
                ),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"],
                    y=df["jitter_ms"],
                    mode='lines',
                    name='Jitter (ms)',
                    line=dict(color='green')
                ),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"],
                    y=df["dns_latency_ms"],
                    mode='lines',
                    name='DNS Latency (ms)',
                    line=dict(color='yellow')
                ),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"],
                    y=df["http_ttfb_ms"],
                    mode='lines',
                    name='HTTP TTFB (ms)',
                    line=dict(color='cyan')
                ),
                row=1, col=1
            )

            # Mark disconnect events
            loss_events = df[df["packet_loss"] == 1.0]
            if not loss_events.empty:
                fig.add_trace(
                    go.Scatter(
                        x=loss_events["timestamp"],
                        y=df.loc[loss_events.index, "latency_ms"].fillna(
                            df["latency_ms"].mean() or 100
                        ),
                        mode='markers',
                        marker=dict(color='red', size=10, symbol='x'),
                        name='Packet Loss / Disconnect'
                    ),
                    row=1, col=1
                )

            # Speedtest plot
            speed_df = df[df["download_mbps"].notna()].copy()
            if not speed_df.empty:
                fig.add_trace(
                    go.Scatter(
                        x=speed_df["timestamp"],
                        y=speed_df["download_mbps"],
                        mode='lines+markers',
                        name='Download (Mbps)',
                        line=dict(color='purple')
                    ),
                    row=2, col=1
                )
                fig.add_trace(
                    go.Scatter(
                        x=speed_df["timestamp"],
                        y=speed_df["upload_mbps"],
                        mode='lines+markers',
                        name='Upload (Mbps)',
                        line=dict(color='orange')
                    ),
                    row=2, col=1
                )

            # Summary table
            summary_data = {
                "Metric": [
                    "Total Test Duration",
                    "Number of Disconnects",
                    "Longest Outage",
                    "Average Latency",
                    "Maximum Jitter",
                    "Average DNS Latency",
                    "Average HTTP TTFB",
                    "Average Download Speed",
                    "Average Upload Speed",
                    "Packet Loss %"
                ],
                "Value": [
                    self.summary_duration.text(),
                    self.summary_disconnects.text(),
                    self.summary_longest_outage.text(),
                    self.summary_avg_latency.text(),
                    self.summary_max_jitter.text(),
                    self.summary_avg_dns_latency.text(),
                    self.summary_avg_http_ttfb.text(),
                    self.summary_avg_download.text(),
                    self.summary_avg_upload.text(),
                    self.summary_packet_loss.text()
                ]
            }
            fig.add_trace(
                go.Table(
                    header=dict(values=["Metric", "Value"]),
                    cells=dict(values=[
                        summary_data["Metric"],
                        summary_data["Value"]
                    ])
                ),
                row=3, col=1
            )

            fig.update_layout(
                height=1200,
                title_text="Network Monitor All-in-One Report"
            )
            fig.update_xaxes(title_text="Time", row=1, col=1)
            fig.update_xaxes(title_text="Time", row=2, col=1)
            fig.update_yaxes(
                title_text="Latency / Jitter (ms)",
                row=1, col=1
            )
            fig.update_yaxes(
                title_text="Speed (Mbps)",
                row=2, col=1
            )

            all_in_one_filename = (
                f"{reports_dir}/all_in_one_report_{timestamp}.html"
            )
            fig.write_html(all_in_one_filename)

            # Still save individual reports if needed
            # Network health report
            fig_health = px.line(
                df,
                x="timestamp",
                y=[
                    "latency_ms",
                    "jitter_ms",
                    "dns_latency_ms",
                    "http_ttfb_ms"
                ],
                title="Network Health Over Time",
                labels={"value": "Latency (ms)", "timestamp": "Time"},
            )
            if not loss_events.empty:
                fig_health.add_scatter(
                    x=loss_events["timestamp"],
                    y=df.loc[loss_events.index, "latency_ms"].fillna(
                        df["latency_ms"].mean() or 100
                    ),
                    mode="markers",
                    marker=dict(color="red", size=10, symbol="x"),
                    name="Packet Loss Event",
                )
            health_filename = (
                f"{reports_dir}/network_health_report_{timestamp}.html"
            )
            fig_health.write_html(health_filename)

            # Speedtest report
            if not speed_df.empty:
                fig_speed = px.line(
                    speed_df,
                    x="timestamp",
                    y=["download_mbps", "upload_mbps"],
                    title="Speedtest Results Over Time",
                    labels={"value": "Speed (Mbps)", "timestamp": "Time"},
                )
                speed_filename = (
                    f"{reports_dir}/speedtest_report_{timestamp}.html"
                )
                fig_speed.write_html(speed_filename)

            # JSON summary
            summary_data_json = {
                "duration": self.summary_duration.text(),
                "disconnects": self.summary_disconnects.text(),
                "longest_outage": self.summary_longest_outage.text(),
                "avg_latency": self.summary_avg_latency.text(),
                "max_jitter": self.summary_max_jitter.text(),
                "avg_dns_latency": self.summary_avg_dns_latency.text(),
                "avg_http_ttfb": self.summary_avg_http_ttfb.text(),
                "avg_download": self.summary_avg_download.text(),
                "avg_upload": self.summary_avg_upload.text(),
            }

            summary_filename = f"{reports_dir}/summary_report_{timestamp}.json"
            with open(summary_filename, "w", encoding="utf-8") as f:
                json.dump(summary_data_json, f, indent=4)

            msg = (
                f"Reports saved in {reports_dir}/ with timestamp {timestamp}. "
                f"Open all_in_one_report_{timestamp}.html "
                "for comprehensive view."
            )
            self.log_text_edit.appendPlainText(msg)
        except Exception as e:
            self.log_text_edit.appendPlainText(f"Error saving reports: {e!r}")

    def open_reports_folder(self):
        reports_dir = "reports"
        if os.path.exists(reports_dir):
            os.startfile(reports_dir)  # Opens in Windows Explorer
        else:
            QMessageBox.information(
                self, "No Reports", "No reports folder found."
            )

    # CLOSE --
    def closeEvent(self, event):
        """
        If user clicked the window close button, hide to tray by default.
        If quit was requested from tray, fully stop workers and exit.
        """
        if self.is_quitting:
            # Full shutdown
            self.stop_monitoring()
            if self.worker_thread:
                self.worker_thread.wait()
            self.tray_icon.hide()
            event.accept()
        else:
            # Just hide to tray
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Still running",
                "Network Monitor continues in the system tray.",
                self.icon_green,
                2000,
            )


# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    main_win = NetworkMonitorGUI()
    main_win.show()
    sys.exit(app.exec())
