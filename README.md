# Network Monitor GUI

A comprehensive network monitoring application with a graphical user interface for Windows. This tool monitors network connectivity, performs speed tests, tracks system metrics, and generates detailed reports.

## Features

- **Real-time Network Monitoring**: Continuous monitoring of network connectivity and latency
- **Speed Testing**: Automated internet speed tests using Ookla CLI
- **System Metrics**: CPU, memory, and disk usage tracking
- **Interactive Graphs**: Real-time visualization using PyQtGraph
- **Data Logging**: CSV logging of all metrics and test results
- **Report Generation**: HTML and JSON reports with charts and summaries
- **Standalone Executable**: No installation required - runs as a single EXE file
- **Background Operation**: Can run minimized and log data continuously

## Screenshots

*(Add screenshots here when available)*

## Requirements

### For Development
- Python 3.7+
- PyQt6
- pyqtgraph
- pandas
- numpy
- matplotlib
- plotly
- psutil
- speedtest-cli
- numba
- requests

### For Running the Standalone EXE
- Windows 10/11 (64-bit)
- No additional dependencies required

## Installation

### Option 1: Standalone EXE (Recommended)
1. Download the latest `NetworkMonitor_build2.exe` from the releases
2. Run the executable directly - no installation needed

### Option 2: From Source
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/network-monitor-gui.git
   cd network-monitor-gui
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # On Windows
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the application:
   ```bash
   python NetworkMonitorGUI.py
   ```

## Usage

### GUI Application
1. Launch `NetworkMonitorGUI.py` or the standalone EXE
2. Configure monitoring settings:
   - Set monitoring interval
   - Choose speed test frequency
   - Select metrics to track
3. Click "Start Monitoring" to begin
4. View real-time graphs and logs
5. Generate reports using the "Generate Report" button

### Command Line Version
```bash
python NetworkMonitor.py --help
```

### Speed Test Only
```bash
python test_speed.py
```

## Building the Standalone EXE

To build your own standalone executable:

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```

2. Build the EXE:
   ```bash
   python -m PyInstaller --clean --noconfirm NetworkMonitorGUI.spec
   ```

3. The executable will be created in the `dist/` folder

### Creating an Installer
Use Inno Setup with the provided `NetworkMonitorGUI.iss` script:
1. Install [Inno Setup](https://jrsoftware.org/isinfo.php)
2. Open `NetworkMonitorGUI.iss`
3. Compile the installer

## Project Structure

```
├── NetworkMonitorGUI.py      # Main GUI application
├── NetworkMonitor.py         # Command-line version
├── test_speed.py            # Speed test utility
├── NetworkMonitorGUI.spec   # PyInstaller configuration
├── NetworkMonitorGUI.iss    # Inno Setup installer script
├── rthooks/
│   └── fix_pandas_numba.py   # Runtime hook for PyInstaller
├── reports/                 # Generated reports
├── dist/                    # Built executables
└── tools/
    └── download_ookla_cli.py # Ookla CLI downloader
```

## Configuration

The application can be configured through the GUI or by modifying the source code constants:

- `MONITORING_INTERVAL`: How often to check network status (seconds)
- `SPEED_TEST_INTERVAL`: How often to run speed tests (minutes)
- `LOG_FILE`: Path to the CSV log file
- `REPORT_DIR`: Directory for generated reports

## Troubleshooting

### Common Issues

**EXE crashes on startup**
- Ensure you're using the correct architecture (64-bit)
- Check Windows Event Viewer for error details

**Speed test fails**
- Ensure internet connection is stable
- Check if Ookla CLI is accessible
- Verify firewall/antivirus isn't blocking the application

**Graphs not displaying**
- Ensure PyQt6 and pyqtgraph are properly installed
- Check for OpenGL compatibility issues

**High CPU usage**
- Increase monitoring intervals in the settings
- Run in background mode when not actively monitoring

### Logs and Debugging
- Check `network_log.csv` for data logging
- Look in `reports/` folder for generated reports
- Enable debug logging by modifying the source code

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Commit your changes: `git commit -am 'Add new feature'`
5. Push to the branch: `git push origin feature-name`
6. Submit a pull request

### Development Setup
```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
python -m pytest

# Build documentation
# (if applicable)
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- Charts powered by [PyQtGraph](http://www.pyqtgraph.org/)
- Speed tests using [Ookla Speedtest CLI](https://www.speedtest.net/apps/cli)
- System monitoring with [psutil](https://psutil.readthedocs.io/)

## Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Check the troubleshooting section above
- Review existing issues for similar problems

---

**Note**: This application is for educational and personal use. Always respect network usage policies and terms of service when running automated tests.