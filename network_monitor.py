import argparse
import csv
import datetime
import os
import platform
import signal
import subprocess
import sys
import threading
import time
import queue
from collections import deque
from statistics import mean

# --- Dependency Check ---
# Try to import dependencies and provide friendly error messages if they are missing.
try:
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    dependencies_installed = True
except ImportError:
    print("WARNING: 'pandas' and 'matplotlib' are not installed.")
    print("Graph generation will be skipped. To enable it, run:")
    print("pip install pandas matplotlib")
    dependencies_installed = False

try:
    import speedtest
except ImportError:
    print("WARNING: 'speedtest-cli' is not installed.")
    print("Speed tests will be disabled. To enable them, run:")
    print("pip install speedtest-cli")
    speedtest = None

# --- Constants ---
PING_TARGETS = ['8.8.8.8', '1.1.1.1']  # Primary and fallback targets
CSV_LOG_FILE = 'network_log.csv'
READABLE_LOG_FILE = 'network_readable.log'
GRAPH_FILE = 'network_stability_report.png'
CSV_HEADER = ['timestamp', 'latency_ms', 'jitter_ms', 'packet_loss', 'event', 'download_mbps', 'upload_mbps']

def get_ping_command():
    """Returns the appropriate ping command for the current operating system."""
    system = platform.system().lower()
    if system == "windows":
        # -n 1: Send 1 echo request.
        # -w 5000: Wait 5000ms (5s) for a reply.
        return ["ping", "-n", "1", "-w", "5000"]
    else: # Linux, macOS
        # -c 1: Send 1 packet.
        # -W 5: Wait 5 seconds for a reply.
        return ["ping", "-c", "1", "-W", "5"]

def ping_host(host, command):
    """
    Pings a host and returns the latency in ms.
    Returns None if the ping fails (timeout, unreachable, etc.).
    """
    try:
        # Execute the ping command
        output = subprocess.check_output(command + [host], stderr=subprocess.STDOUT, universal_newlines=True)
        
        # Parse output for latency
        if platform.system().lower() == "windows":
            for line in output.splitlines():
                if "time=" in line.lower():
                    return float(line.lower().split("time=")[1].split("ms")[0])
        else: # Linux, macOS
            for line in output.splitlines():
                if "rtt min/avg/max" in line:
                    parts = line.split("=")[1].split("/")[1]  # avg latency
                    return float(parts)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # CalledProcessError means ping failed (e.g., host unreachable)
        # FileNotFoundError means ping command doesn't exist
        return None

def run_speed_test(log_queue):
    """
    Runs a speed test and logs the results. Executed in a separate thread.
    """
    if not speedtest:
        log_queue.put({'type': 'readable', 'message': "Speed test skipped: speedtest-cli not installed."})
        return

    log_queue.put({'type': 'readable', 'message': "🚀 Starting speed test..."})
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        st.download()
        st.upload()
        results = st.results.dict()

        download_mbps = results['download'] / 1_000_000
        upload_mbps = results['upload'] / 1_000_000
        ping_ms = results['ping']

        log_queue.put({
            'type': 'csv',
            'data': {
                'download_mbps': round(download_mbps, 2),
                'upload_mbps': round(upload_mbps, 2),
                'event': 'Speed Test'
            }
        })
        log_queue.put({'type': 'readable', 'message': f"🚀 Speed Test Results: DL {download_mbps:.2f} Mbps / UL {upload_mbps:.2f} Mbps / Ping {ping_ms:.2f} ms"})

    except Exception as e:
        log_queue.put({'type': 'readable', 'message': f"❌ Speed test failed: {e}"})
        log_queue.put({'type': 'csv', 'data': {'event': 'Speedtest Failed'}})

def log_to_files(log_queue, stop_event):
    """
    A dedicated thread to handle writing to log files.
    """
    with open(CSV_LOG_FILE, 'w', newline='') as csvfile, open(READABLE_LOG_FILE, 'w') as readablefile:
        csv_writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADER)
        csv_writer.writeheader()
        csvfile.flush()

        while not stop_event.is_set() or not log_queue.empty(): # Process queue even after stop is set
            try:
                log_entry = log_queue.get(timeout=1)
                
                if log_entry['type'] == 'csv':
                    timestamp = datetime.datetime.now().isoformat()
                    full_data = {'timestamp': timestamp, 'latency_ms': '', 'jitter_ms': '', 'packet_loss': '', 'event': '', 'download_mbps': '', 'upload_mbps': ''}
                    full_data.update(log_entry['data'])
                    csv_writer.writerow(full_data)
                    csvfile.flush()

                elif log_entry['type'] == 'readable':
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                    readablefile.write(f"{timestamp} – {log_entry['message']}\n")
                    readablefile.flush()
                    print(f"{timestamp} – {log_entry['message']}")

            except queue.Empty:
                continue

def generate_graphs():
    """
    Generates and saves graphs from the network log file.
    """
    if not dependencies_installed:
        print("\nSkipping graph generation because dependencies are not installed.")
        return

    print("\nGenerating network stability report...")
    try:
        df = pd.read_csv(CSV_LOG_FILE, parse_dates=['timestamp'])
        if df.empty:
            print("Log file is empty. No report to generate.")
            return

        # Prepare data
        df_ping = df[df['latency_ms'].notna()].copy()
        df_speed = df[df['event'] == 'Speed Test'].copy()
        df_loss = df[df['packet_loss'] == 1.0].copy()

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(15, 15), sharex=True)
        fig.suptitle('Network Stability Report', fontsize=16)
        date_format = DateFormatter("%H:%M:%S")

        # Plot 1: Latency and Jitter
        ax1.set_title('Latency and Jitter over Time')
        ax1.plot(df_ping['timestamp'], df_ping['latency_ms'], label='Latency (ms)', color='blue', alpha=0.8)
        ax1.plot(df_ping['timestamp'], df_ping['jitter_ms'], label='Jitter (ms)', color='orange', alpha=0.7, linestyle='--')
        ax1.set_ylabel('Milliseconds (ms)')
        
        # Mark packet loss on the latency graph
        if not df_loss.empty:
            # Plot a single dummy point for the legend, then draw lines
            ax1.plot([], [], color='red', linestyle='--', alpha=0.5, label='Packet Loss')
            for t in df_loss['timestamp']:
                ax1.axvline(x=t, color='red', linestyle='--', alpha=0.5)
        
        # Create a unique legend
        handles, labels = ax1.get_legend_handles_labels() # This is now correct
        ax1.legend(handles, labels)
        ax1.grid(True)

        # Plot 2: Speed Test Results
        ax2.set_title('Internet Speed over Time')
        if not df_speed.empty:
            ax2.plot(df_speed['timestamp'], df_speed['download_mbps'], label='Download (Mbps)', color='green', marker='o')
            ax2.plot(df_speed['timestamp'], df_speed['upload_mbps'], label='Upload (Mbps)', color='purple', marker='o')
        ax2.set_ylabel('Mbps')
        ax2.legend()
        ax2.grid(True)

        # Plot 3: Disconnect Events
        ax3.set_title('Disconnection Events')
        if not df_loss.empty:
             ax3.plot(df_loss['timestamp'], [1] * len(df_loss), linestyle='None', marker='x', color='red', markersize=10, label='Disconnect Event')
        ax3.set_xlabel('Time')
        ax3.set_yticks([])
        ax3.legend()
        ax3.grid(True)
        
        # Format x-axis
        ax3.xaxis.set_major_formatter(date_format)
        plt.xticks(rotation=45)
        
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.savefig(GRAPH_FILE)
        print(f"Report saved to {GRAPH_FILE}")

    except Exception as e:
        print(f"Could not generate graph: {e}")

class NetworkMonitor:
    def __init__(self, interval, speedtest_interval):
        self.interval = interval
        self.speedtest_interval = speedtest_interval
        self.ping_command = get_ping_command()

        # State
        self.latencies = deque(maxlen=20)
        self.is_disconnected = False
        self.disconnect_start_time = None
        self.last_speed_test_time = 0

        # Threading
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        self.log_thread = threading.Thread(target=log_to_files, args=(self.log_queue, self.stop_event))
        self.speed_test_thread = None

    def _log(self, msg_type, message=None, data=None):
        """Helper to queue log messages."""
        entry = {'type': msg_type}
        if message:
            entry['message'] = message
        if data:
            entry['data'] = data
        self.log_queue.put(entry)

    def _check_connection(self):
        """Pings hosts and updates connection state."""
        latency = None
        target_ip = None

        for target in PING_TARGETS:
            latency = ping_host(target, self.ping_command)
            if latency is not None:
                target_ip = target
                break
        
        if latency is not None:
            if self.is_disconnected:
                outage_duration = time.time() - self.disconnect_start_time
                self._log('readable', message=f"✅ Reconnected after {outage_duration:.2f} seconds.")
                self._log('csv', data={'event': f'Reconnected after {outage_duration:.2f}s'})
                self.is_disconnected = False
            
            jitter = abs(latency - self.latencies[-1]) if self.latencies else 0
            self.latencies.append(latency)
            
            self._log('readable', message=f"Ping to {target_ip}: {latency:.2f}ms (Jitter: {jitter:.2f}ms)")
            self._log('csv', data={'latency_ms': latency, 'jitter_ms': round(jitter, 2), 'packet_loss': 0.0})
        else:
            if not self.is_disconnected:
                self.is_disconnected = True
                self.disconnect_start_time = time.time()
                self._log('readable', message="❌ DISCONNECTED")
            
            self._log('csv', data={'packet_loss': 1.0, 'jitter_ms': '', 'event': 'Disconnected'})

    def _check_and_run_speedtest(self):
        """Schedules a speed test if the interval has passed."""
        if self.speedtest_interval <= 0 or self.is_disconnected:
            return

        now = time.time()
        if (now - self.last_speed_test_time) / 60 >= self.speedtest_interval:
            if self.speed_test_thread is None or not self.speed_test_thread.is_alive():
                self.last_speed_test_time = now
                self.speed_test_thread = threading.Thread(target=run_speed_test, args=(self.log_queue,))
                self.speed_test_thread.start()

    def run(self):
        """Main monitoring loop."""
        self.log_thread.start()
        self._log('readable', message=f"Starting network monitor. Ping interval: {self.interval}s. Speed test interval: {self.speedtest_interval} min.")

        while not self.stop_event.is_set():
            self._check_connection()
            self._check_and_run_speedtest()
            self.stop_event.wait(self.interval) # Use wait instead of sleep

    def stop(self):
        """Stops the monitor gracefully."""
        print("\nShutting down and generating report...")
        self.stop_event.set()
        if self.speed_test_thread and self.speed_test_thread.is_alive():
            print("Waiting for speed test to finish...")
            self.speed_test_thread.join()
        
        # Wait for the log thread to process all remaining messages
        self.log_thread.join()
        print("Cleanup complete. Exiting.")

def main():
    parser = argparse.ArgumentParser(description="Continuously monitor network stability.")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between pings (default: 2.0).")
    parser.add_argument("--speedtest", type=int, default=0, help="Minutes between speed tests (default: 0, disabled).")
    parser.add_argument("--generate-report", action="store_true", help="Generate report from existing logs and exit.")
    args = parser.parse_args()
    if args.generate_report:
        generate_graphs()
        sys.exit(0)

    monitor = NetworkMonitor(interval=args.interval, speedtest_interval=args.speedtest)
    
    def signal_handler(sig, frame):
        monitor.stop()

    signal.signal(signal.SIGINT, signal_handler)
    
    monitor.run()
    generate_graphs() # Generate report after run() completes

if __name__ == "__main__":
    main()
