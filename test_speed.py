import sys, importlib
sys.path.insert(0, r'D:\Github\Documents\Wifi Test')
mod = importlib.import_module('NetworkMonitorGUI')
settings = {
    'interval_s': 1.0,
    'target_ips': ['8.8.8.8'],
    'speedtest_enabled': True,
    'speedtest_interval_min': 30,
    'latency_threshold_ms':150,
    'wifi_threshold_percent':50,
}
worker = mod.NetworkWorker(settings)
# Replace signal emit to print
try:
    # Bound PyQt signal object has an emit method we can override
    worker.log_message.emit = lambda s: print('LOG:', s)
except Exception as e:
    print('Could not monkeypatch signal emit:', e)

worker._run_speed_test_task()
print('Queue size:', worker.speed_test_result_queue.qsize())
if not worker.speed_test_result_queue.empty():
    print('Result:', worker.speed_test_result_queue.get())
