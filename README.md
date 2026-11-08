# TAIT Radio Map version 1.0

Extract the entire folder. Python and downloaded packages are required; this is
not a standalone executable. The full operator guide is in docs.

## Windows
Open PowerShell in this folder:

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements-all.txt
    .\.venv\Scripts\python.exe radio-map\serve.py

If python is unavailable, use py -3 for the first command. Later starts can use
start-windows.cmd. Keep the terminal running and open http://127.0.0.1:8765.

## macOS
Open Terminal in this folder:

    python3 -m venv .venv
    ./.venv/bin/python -m pip install --upgrade pip
    ./.venv/bin/python -m pip install -r requirements-all.txt
    ./.venv/bin/python radio-map/serve.py

Later starts can use bash start-macos.command. Mac hardware is not validated.

## Radio connection
Configure a suitable CCDI data cable/interface and matching baud/flow control.
Open Radio connection, select the port and choose Listen for reports or Poll
radios for location. Polling requires compatible conventional TAIT AVL support
and correct SDM identities/dispatch return address. Stop before changing modes.
Follow the Word guide for first-fix verification and all feature instructions.

## LAN and offline use
The companion prints network viewer addresses. LAN read-only viewing needs no
key; control and map-file/cache changes need its printed companion key. The key
changes each restart. Use --host 127.0.0.1 for local-only access. Do not forward
the companion port to the internet. Other LAN viewers only need a browser.
PDF maps and retained tiles can be used offline while the companion is running.
Only viewed tiles are cached. No bulk map download is provided.

## Release and data
No user recordings, cached tiles, operational PDFs, credentials or environment
are included. New sessions create radio-map/runtime. Stop before backup/upgrade.
Browser names, colours and preferences are per browser/origin.
RELEASE.json identifies the source snapshot; SHA256SUMS.txt lists file hashes.
VALIDATION.txt records checks and platform limits. THIRD_PARTY_NOTICES.txt and
radio-map/dist/vendor contain dependency notices.
