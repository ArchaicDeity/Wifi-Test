import os
import sys
import urllib.request
import zipfile

URL = 'https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-win64.zip'
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
EXTRAS = os.path.join(ROOT, 'extras')
OUT_ZIP = os.path.join(EXTRAS, 'ookla_speedtest_win64.zip')

os.makedirs(EXTRAS, exist_ok=True)

print('Downloading', URL)
with urllib.request.urlopen(URL) as resp:
    if resp.status != 200:
        print('Download failed, status', resp.status)
        sys.exit(2)
    data = resp.read()
    with open(OUT_ZIP, 'wb') as f:
        f.write(data)

print('Downloaded to', OUT_ZIP)

# Extract speedtest.exe
with zipfile.ZipFile(OUT_ZIP, 'r') as z:
    members = z.namelist()
    # Try to find an exe inside the zip
    exe_candidates = [m for m in members if m.lower().endswith('.exe')]
    if not exe_candidates:
        print('No .exe found in archive; contents:', members)
        sys.exit(3)
    # Prefer a file named speedtest.exe
    chosen = None
    for m in exe_candidates:
        if os.path.basename(m).lower() == 'speedtest.exe':
            chosen = m
            break
    if not chosen:
        chosen = exe_candidates[0]

    out_path = os.path.join(EXTRAS, 'speedtest.exe')
    print('Extracting', chosen, '->', out_path)
    with z.open(chosen) as source, open(out_path, 'wb') as target:
        target.write(source.read())

print('Extraction complete. Executable at', os.path.join('extras', 'speedtest.exe'))
print('You can now re-run PyInstaller to include the binary in the bundle.')