# TAIT Radio Map User Guide
Version 1.0 | 31 October 2026

Install the application on the computer connected to the receiving radio, then use its browser viewer to collect and display positions. This guide covers initial setup, listening and polling, map operation, offline coverage, LAN sharing and recorded files.

The Python companion starts and supervises the selected logger, saves reports and serves the website. Opening a browser does not start Python. Keep the companion terminal open while operating. A LAN viewing computer only needs a browser.

## First run at a glance
1. Extract the complete release ZIP and install the dependencies using section 1 or 2.
2. Connect and power the receiving radio through its CCDI serial data interface.
3. Start the companion and open http://127.0.0.1:8765 on that computer.
4. Open Radio connection, check the serial settings, choose a mode and start.
5. Generate a field-radio report and confirm a fresh timestamp and plausible position.

## Guide contents
Sections 1 and 2 cover Windows and Mac installation. Section 3 covers the common radio setup. Sections 4 and 5 cover Listen and Poll modes. Sections 6 and 7 cover positions, history and map controls. Section 8 covers offline tiles and PDFs. Sections 9 and 10 cover sharing, recordings and backups. Sections 11 and 12 cover troubleshooting. Section 13 covers optional CLI operation and section 14 describes release contents and acceptance checks.

## Release scope
This is a source distribution, not a standalone executable or installed background service. Python and downloadable dependencies are required. Windows is the verified development platform; macOS operation is intended but has not been tested on Mac hardware.

Radio compatibility depends on model, channel and programming. Polling support is not established merely by receiving a direct-send DMR position. Confirm the complete path on the intended radio system before deployment.

Polling follows Tait TN-856-AN version 2.0. Use the radio system's approved documentation for model-specific programming. This is an independent application, not Tait firmware or a radio programming package.

<!-- PAGE -->
# 1 Install on Windows

Extract all files to a writable folder, for example Documents\TaitRadioMap-1.0. Do not run inside the ZIP. Retain the folder structure, including radio-map and both top-level logger scripts.

## Install Python and dependencies
Install a supported 64-bit Python 3 release from https://www.python.org/downloads/. Python 3.12 is the release verification interpreter. The source requires Python 3.10 or newer, but use a supported Python release for a new installation.

Open PowerShell in the extracted folder. Check python --version. If unavailable, try py -3 --version and substitute py -3 for python in the first command below. Use an isolated environment:
~~~text
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-all.txt
~~~

The complete requirements install serial and PDF map support. Internet is needed for the initial download. For a serial-only installation, use requirements.txt instead; PDF import needs the additional libraries later.

These commands use the environment interpreter directly. There is no need to activate a PowerShell script or change execution policy.

## Start the application
~~~text
.\.venv\Scripts\python.exe radio-map\serve.py
~~~
Alternatively, double-click start-windows.cmd after creating the environment. Open http://127.0.0.1:8765 in a browser on that PC. Keep the companion terminal open while logging.

## Connect the interface
Install the USB interface manufacturer's driver if required. Windows Device Manager under Ports helps identify the COM port. The viewer also lists available ports under Radio connection. Use a cable exposing the radio's configured CCDI data interface; a programming cable is not automatically suitable for live data.

Allow incoming Python connections on the intended private network if LAN viewing is required. For local-only operation, add --host 127.0.0.1 to the startup command. Section 9 explains network access.

<!-- PAGE -->
# 2 Install on macOS

Copy the complete extracted release to a writable folder, for example ~/Documents/TaitRadioMap-1.0. Keep the logger scripts beside radio-map. These portability instructions have not been validated on Mac radio hardware.

## Install and start
Install a supported Python 3 release from https://www.python.org/downloads/. In Terminal, check python3 --version, then use the following commands, adjusting the folder path if needed:
~~~text
cd ~/Documents/TaitRadioMap-1.0
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements-all.txt
./.venv/bin/python radio-map/serve.py
~~~

On subsequent starts, use the final command above or run bash start-macos.command from the release folder. Running the launcher through bash avoids dependence on executable permissions preserved by the ZIP extractor. Recreate the environment on each computer; a Windows environment cannot be moved to a Mac.

## Select the serial device
USB serial ports commonly appear as /dev/cu.usbserial-* or /dev/cu.usbmodem-* rather than COM names. Select the device matching the radio interface. Check the manufacturer's driver requirements if it is absent.

To list ports without starting a radio session:
~~~text
./.venv/bin/python -m serial.tools.list_ports
~~~

## Open the viewer
Open http://127.0.0.1:8765 on the Mac running the companion. Other LAN computers use the printed Network viewer address for the Mac. Allow the intended incoming connection through the macOS firewall if prompted. VPN routing and Wi-Fi client isolation can prevent LAN access.

The companion serves the viewer, positions and imported PDF images. Online tiles require internet when not already cached. Keep the companion running for offline use and keep the computer awake while collecting reports. No automatic startup service is installed.

<!-- PAGE -->
# 3 Prepare the initial radio connection

The receiving or base radio connects to the computer. Field radios supply their GPS positions over the radio network. Both serial settings and radio-side reporting configuration must be correct; the application does not program the radios.

## Check the hardware and radio settings
Confirm that the receiving radio exposes the required CCDI data interface. Check baud rate and flow control against its programming. Framing is 8 data bits, no parity and 1 stop bit.

On field radios, confirm GPS/location reporting is enabled, a current fix is available and the report destination, channel and signalling match the receiving system. Test with suitable GPS reception. Programming menus vary by model and firmware; use the radio documentation or the system administrator's verified configuration.

Close programming software, serial terminals, other loggers and any second companion using the same port. Only one process should own the serial connection. First establish reception in Listen mode before testing Poll mode.

## Configure the common options
1. Start the companion and open Radio connection.
2. On the radio PC's 127.0.0.1 page, pairing normally happens automatically. If needed, click Pair / re-pair companion, then Load / refresh ports.
3. Select the port and the radio's actual baud rate. The interface default is 9600; use 19200 if that is the radio's configuration.
4. Select None, XON/XOFF or RTS/CTS flow control to match the radio and cable.
5. Choose the mode and follow section 4 or 5. Starting creates a new recording session.

## Verify a first report
Check the displayed radio identity, coordinates and last-heard time. Live diagnostics shows received records and status messages. An open serial port does not prove that a usable GPS report has arrived.

Set the computer's clock and date correctly. Binary AVL reports carry day/time but omit month/year, which are inferred near reception. Direct-send coordinate text without GPS time uses reception time. Browser timestamps use that browser's local timezone.

Stop the connection before changing its port, speed, flow control or mode.

<!-- PAGE -->
# 4 Listen for position reports

Listen mode receives reports generated by field radios, such as timed AVL reports or supported direct-send location messages. It does not periodically request a new position from every field radio.

## Start listening
1. Open Radio connection and confirm the serial settings from section 3.
2. Select Listen for reports and Start listening.
3. Trigger a known field-radio position report or wait for its configured reporting interval.
4. Confirm a fresh dot and timestamp. Open Live diagnostics if no update appears.
5. Close the options window to return to the map. The connection remains running.

The listener may issue a local serial command to retrieve a buffered SDM after a suitable notification. This reads and clears the receiving radio's SDM buffer; it is not an over-air location poll. Entirely passive operation is available only through the CLI --passive option and may prevent buffered positions being retrieved.

## Interpret radio identities
Compressed TAIT AVL carries a four-digit suffix. A radio configured as 3000030 may therefore appear as 0030, preserving leading zeros. The application does not invent missing digits.

A directly associated DMR SDM notification can supply a full numeric caller ID for supported direct-send text. Reports lacking a usable sender identity may appear as Unknown radio. Full IDs and suffix-only IDs remain separate entries.

A custom name improves readability but does not establish full sender identity or change KML identities. Establish the mapping from your known radio configuration.

## Reports and status messages
Successful supported binary AVL, supported direct-send coordinate text and valid NMEA positions can create points. Busy/idle records, voice/status notifications, empty SDMs and no-fix reports do not themselves contain a usable current position.

## Stop or change the session
Select Stop connection, wait until stopped, then change settings and start again. Each website session uses new output files, preserving earlier captures and KML. For a clean shutdown, stop the radio connection and then press Ctrl+C in the companion terminal.

<!-- PAGE -->
# 5 Poll radios for their locations

Poll mode sends location requests to listed radio IDs at individual intervals. It implements conventional TAIT CCDI/FFSK AVL polling based on TN-856. Base and field radios must support that method and return replies to the intended dispatcher. DMR direct-send reception alone does not establish polling compatibility.

## Configure the list
1. Stop any listening session on the same port.
2. Open Radio connection, confirm serial settings and select Poll radios for location.
3. Enter one ID and interval in seconds per line, separated by a comma:
~~~text
3000030, 60
3000029, 120
~~~
4. Replace these examples with actual SDM polling identities, which may differ from DMR voice IDs.
5. Select Start polling. Check Live diagnostics, then confirm the reply identity and fresh position time on the map.

The list accepts 1 to 100 targets, nonzero IDs containing 1 to 8 digits and intervals of at least one second. Use intervals suitable for channel capacity. Targets must have unique last four digits because binary replies cannot distinguish duplicate suffixes. Full polling IDs do not make suffix-only replies contain full IDs.

## Understand timing
Only one radio is polled at a time. Initially all targets are due. The poller waits for local prompts and replies, defers during receiver-busy/PTT indications and inserts gaps between polls. Intervals are minimum spacing between starts for each radio, not an exact schedule. Delayed intervals do not produce bursts of catch-up requests.

Valid unsolicited reports are also recorded. A matching no-fix/status reply can complete a request without adding a position. A report without an explicit matching identity may be saved while the poll waits until timeout. Old/no-fix reports are not plotted as current fixes.

## Check compatibility before changing timings
Test one target first. Verify the protocol, target SDM identity and dispatcher return destination if requests time out. Website polling uses the script's default timings and return destination.

The CLI exposes return ID, response timeout, command timeout, key-up lead-in and poll gap; see section 13. These advanced controls are not available in the website options.

<!-- PAGE -->
# 6 Positions and track history

The left legend shows radio identity, last-heard time and the chosen coordinates. Larger labelled dots show latest fixes. Small dots show earlier reports; coloured lines form tracks within recording sessions.

## Find and inspect radios
Search by ID or custom name. Click a legend name/ID to centre the map. Click a point for report time, identity, coordinates and available description. Hover an earlier dot for its timestamp. Use the right-hand zoom controls and the fit button to frame visible radios.

Checkboxes hide or show each radio's dots, labels and tracks. Hide all and Show all change the group together. Hidden radios remain in the dataset and can be shown again.

## Custom names and colours
Click the pencil beside a radio. Enter its name, choose the points and track colour, then Save changes. The colour applies to the legend indicator, latest dot, report dots and tracks.

Clear name removes the saved name while preserving the saved colour. Default colour followed by Save changes restores the automatic colour. Cancel discards the draft. Names are limited to 40 characters. These preferences belong to the browser and do not modify the radio or KML.

## History window
The slider offers Latest only; 5, 15 and 30 minutes; 1, 3, 6, 12 and 24 hours; 3 and 7 days; and All history. The window runs backward from the newest report in the dataset, not the current computer time. The history panel shows that anchor. Latest markers remain visible even when older than the selected track window.

Separate KML sessions are not connected by a line. Combining files removes identical ID/time/coordinate duplicates in the viewer. Stationary reports can overlap. A latest marker is the last recorded fix, not proof the radio is still there.

## Panel layout
Panels contains visibility controls for Radio legend, Track history and Map status. Use Larger/Compact and the history panel's resize corner to change its size. Reset layout restores default panel visibility and sizing. Expand Panels → Maps for map controls.

Names, colours, visibility and the history setting persist per browser/origin. Other viewers may use different choices.

<!-- PAGE -->
# 7 Map appearance and grid references

Open Panels → Maps for map name, style, coordinates, grid lines, PDFs and cache controls. Collapse Maps or Panels to recover map space.

## Name and base style
Enter a Map name and Save name to replace TAIT in the header and browser title. Blank restores TAIT. The limit is 40 characters. This label does not rename radios or change KML.

Map styles are Standard, Humanitarian, OpenTopoMap, Greyscale and Dark. Greyscale and Dark filter Standard tiles while preserving radio colours. Providers differ in detail, coverage and zoom availability. Changing style preserves position data and the map view. Attribution remains visible at the map edge.

## Coordinate display
Choose latitude/longitude or MGRS at 6, 8 or 10 digits, corresponding to 100 m, 10 m or 1 m precision. This changes legend and popup readouts; stored positions and KML remain WGS84 latitude/longitude. More digits do not improve GPS accuracy.

MGRS means Military Grid Reference System. Read the zone, latitude band and 100 km square with the numerical reference. Compare with a paper map using the appropriate datum and grid. Outside supported UTM latitudes, coordinate readouts fall back to latitude/longitude.

## Grid lines
Choose Off, Latitude / longitude, or WGS84 UTM / MGRS grid. Angular spacing adapts to the current view.

The metric grid appears at zoom level 8 or closer, between 80°S and 84°N. It uses the view centre's UTM zone and adapts among 100 m, 1 km, 10 km and 100 km spacing. Labels show full easting and northing in metres.

This centre-zone UTM overlay is compatible with WGS84 UTM/MGRS reference work; it is not a multi-zone MGRS atlas. At zone boundaries, read the displayed zone notice and check the paper map's zone and datum. Coordinate format and grid lines are separate choices.

## Browser preferences
Map name, style, coordinate format and grid selection are saved per browser/origin. localhost, 127.0.0.1 and a LAN IP may have different preferences even when they reach the same companion. Clearing browser storage can reset these choices.

<!-- PAGE -->
# 8 Offline tiles and PDF maps

The local/LAN viewer and Leaflet assets are bundled. Offline coverage comes from retained tiles or an imported geospatial PDF. Keep the companion running; initial dependency installation still needs downloads unless supplied separately.

## Tile cache
Panels → Maps → Map tile cache shows stored image bytes, tile count and the limit. Default is 250 MB. Set 10 to 10000 MB and choose Save cache limit. Oldest-used tiles are evicted when needed. SQLite metadata adds small disk overhead beyond image bytes.

Only tiles requested during normal viewing are retained. Other areas and zoom levels may be absent offline. There is no bulk area-download or prefetch option. Clear map cache removes tiles, not radio recordings or imported PDF maps. LAN viewers must pair before changing this shared cache.

## Import and use a PDF
1. Install the PDF dependencies and restart the companion if they were added after startup.
2. Open Panels → Maps → Offline PDF maps. Pair through Radio connection if needed.
3. Set PDF page and Map frame / viewport, numbered from 1. Start with 1 and 1.
4. Choose Import geospatial PDF and select a file up to 50 MB. Wait for conversion.
5. Select the map, use Fit PDF map and check alignment against known locations.
6. Adjust opacity. Enable PDF only (no online tiles) to suppress online base tiles, including on subsequent reloads.

Supported PDFs contain ISO geospatial viewport metadata, matching control points and a recognised CRS. Reversed and partly off-page frames are handled. Plain scans, legacy LGIDict GeoPDFs, rotated pages, encrypted files and date-line/polar maps are unsupported. Export an unrotated ISO geospatial PDF from GIS software when needed.

## Storage and quality
Images are limited to 4096 pixels on the longest edge; deep zoom becomes pixelated. Images and metadata persist on the radio PC and are shared with LAN viewers. Storage is separate from the tile-cache budget.

Delete PDF map removes that imported map for all viewers. The original PDF is not retained or modified; keep it separately. The Puckapunyal East Special PDF was successfully checked with page 1/frame 1, but is not included in the release. Use local/LAN viewing offline; opening the private hosted website still needs internet.

<!-- PAGE -->
# 9 Share the map with other viewers

One companion and radio session feed multiple LAN browsers. Viewing computers need no Python or second serial connection. Keep the radio PC powered, awake and network-connected.

## Read-only LAN viewing
1. Start the companion. It listens on IPv4 interfaces by default and prints Network viewer URLs, for example http://192.168.1.20:8765.
2. Start listening or polling once on the radio PC.
3. On another LAN computer, open that printed network address. 127.0.0.1 on another computer refers to that computer itself.
4. Positions load without pairing and refresh every five seconds. Existing PDF maps can also be selected without a key.

The read-only feed is available to computers that can reach the listener. Use the intended local network. This is not an internet relay or hosted position database. Do not forward the companion port to the internet.

## Pair for control
Radio start/stop, port discovery, diagnostics, cache changes and PDF import/deletion require the companion key. Open Radio connection, use the radio PC's network address, enter its terminal key and choose Pair / re-pair companion.

These controls operate the same shared radio process. Pairing a viewer does not start a second radio connection. The key changes on companion restart. Replace old keys and pair again. Forget pairing removes that browser's pairing without stopping the session. On the local 127.0.0.1 or localhost page, pairing is normally automatic.

## Hosted website
If the owner provides access to the separately hosted private website, it can open KML snapshots or pair with a reachable companion. On another LAN computer, use the radio PC's LAN address. Browser local-network permissions or HTTPS-to-HTTP restrictions may prevent this; use the directly served LAN page instead. Pairing does not grant access to the private hosted site itself.

## Restrict access or change port
Use --host 127.0.0.1 at startup for local-only access. Use --port 8766 to change the port and follow the new printed URL. LAN connectivity also depends on firewall, routing, Wi-Fi isolation and VPN settings. The release installs neither firewall rules nor an automatic service.

<!-- PAGE -->
# 10 Recordings and data management

Website sessions create files under radio-map/runtime. Closing a browser does not stop recording. Stopping the radio or companion ends collection but retains files.

## Saved files
| Item | Purpose |
| radio-... .kml | Timestamped points and per-radio tracks for a session |
| radio-...-capture.txt | Original received serial bytes for diagnosis and replay |
| radio-...-events.txt | Timestamped receive/transmit events and status |
| radio-...-radios.json | A polling session's saved target list |
| map-cache.sqlite | Shared map tile cache |
| pdf-maps | Imported PDF images and metadata |

The live viewer includes saved radio-*.kml sessions in runtime. Default startup also loads root polled_locations.kml and trip2.kml when present. Missing default legacy files are ignored. Use --kml followed by specific paths to watch selected files; missing explicitly requested files are reported.

## KML snapshots
Open KML selects one or more browser-local snapshots rather than watching them. Each file is limited to 50 MB and needs timestamped Point placemarks. A line-only KML has no per-point timestamps. Use the footer refresh button to return to live local/LAN updates. KML can also be opened in Google Earth or another compatible application, whose refresh behaviour is separate.

## Clear and restore display history
Panels → Clear history & radios hides points, tracks and radios through the newest dataset timestamp. Files are preserved, recording continues and newer reports reappear. Restore saved data removes that cutoff. This is browser-local and does not clear other viewers.

## Backups and upgrades
Stop the radio and companion before backing up or moving runtime. Keep the complete runtime folder and original PDFs. Browser-stored names, colours and preferences are separate and are not included in that folder.

Extract upgrades into a fresh folder and recreate the environment. Copy stopped runtime data if wanted. Do not run old and new companions on the same serial or HTTP port. To stop displaying older sessions, archive their KML outside runtime while stopped and keep related captures/events together. Keep the original release ZIP and checksum for rollback.

<!-- PAGE -->
# 11 Troubleshoot the radio connection

## Viewer unavailable
Confirm the companion is running and use its printed URL. Opening a bookmark does not start Python. If the port is in use, stop the intended previous companion or choose another --port. Do not create competing processes for one radio.

## No port or access denied
Refresh ports after attaching the cable. Check the USB driver and operating-system device list. Close programming software, serial terminals and other loggers. Confirm the cable exposes the correct CCDI interface. Install pyserial into the environment used by the companion, not another Python installation.

## Running but no position
Check serial speed/flow control, GPS fix, report destination, channel and payload format. Trigger one known report. In Live diagnostics, distinguish the receive notification from its retrieved SDM. Busy/idle/voice/status records and no-fix messages do not create current positions.

No supported location can mean a non-location message, unsupported payload or configuration mismatch. The phrase alone does not prove a field-radio fault. Retain the corresponding raw capture and event log for investigation.

## Polling timeouts
Confirm conventional CCDI/FFSK AVL polling support, actual SDM identities and the dispatcher return destination. Receiving direct-send DMR coordinates or knowing a voice ID is not enough. Test a single target with a generous interval before expanding the list. Busy states and response waits extend scheduling.

## Shortened IDs
Compressed AVL carries only four digits; 3000030 may appear as 0030. Full IDs and suffix-only IDs remain separate entries. Leading zeros matter. Custom names help identify known units but do not add verified digits to reports.

## Pairing fails
After restarting the companion, enter its new key. Use the radio PC's address, not another PC's loopback. Refresh old browser tabs after updates. Changing a key input invalidates the old pairing until Pair / re-pair companion succeeds.

## Diagnostic material
Record the time, mode, settings and complete error. Keep the session's capture/events and relevant radio configuration. Stop and copy files before sharing. Captures and KML can include identities and precise locations; share them only with the intended support recipient.

<!-- PAGE -->
# 12 Troubleshoot maps and offline use

## Missing tiles or blank background
Try Standard style and check internet connectivity. The cache contains only retained views at their requested zoom levels. Offline zoom into a different level may be blank. If PDF only is enabled, select an imported map and use Fit PDF map, or disable PDF only when online tiles are wanted.

Unavailable uncached tiles return HTTP 503. Radio positions can still update because collection is independent of map downloads. Use a stored PDF for defined offline sheet coverage. Providers can have outages and zoom limits.

## Connection aborted tracebacks
Version 1.0 handles expected browser disconnects, including Windows 10053, without printing a traceback or sending a second response. Browsers cancel requests on pan, zoom, navigation and reload. Restart the updated companion if an older process still prints them. Genuine application faults remain visible.

## PDF import errors
Install requirements-maps.txt in the companion environment and restart. Check file size, page and frame. Plain scans lack georeferencing; unsupported formats must be exported as unrotated ISO geospatial PDFs.

Invalid map viewport bounds now means an invalid, zero-sized or fully off-page frame. Reversed/partly off-page frames are supported. Inconsistent control points means the geographic mapping cannot be fitted reliably. Keep the source PDF for review rather than guessing its placement.

## Blurred or shifted PDF
The maximum 4096-pixel edge limits deep zoom. Check page/frame, datum and known locations. Opacity helps compare with online mapping. Metadata consistency checks do not certify the source map's survey accuracy.

## Different settings on other PCs
Names, colours, map name/style, coordinates, grids, visibility, history window and clear-history cutoff are browser-local. Storage is separated by origin, including localhost, 127.0.0.1 and a LAN IP. Shared recordings, PDF files and cache remain on the companion.

## LAN access fails
Use the correct printed LAN address/port. Check that startup was not restricted to loopback, then check firewall rules, VPN routing and Wi-Fi client isolation. Read-only viewing needs no key; control requires pairing. There is no internet relay service.

<!-- PAGE -->
# 13 Optional command line operation

The standalone scripts support replay, chosen output files and advanced polling settings. Stop any website session on the same serial port first. Commands below are for Windows from the release root. On Mac, replace .\.venv\Scripts\python.exe with ./.venv/bin/python and use the Mac serial device.

## Listen and record
~~~text
.\.venv\Scripts\python.exe tait_to_kml.py --port COM3 --baud 9600 --output trip.kml --raw-log capture.txt --event-log events.txt --verbose
~~~
Use actual settings and optional --flow-control xonxoff or rtscts. --passive disables automatic local SDM retrieval and may prevent buffered positions being read.

## Poll configuration
Edit radios.example.json. The release example uses 3000030 every 60 seconds and 3000029 every 120 seconds. Replace these with the intended system. Preview without opening a port or writing files:
~~~text
.\.venv\Scripts\python.exe tait_poll_to_kml.py --config radios.example.json --dry-run
~~~
Start polling:
~~~text
.\.venv\Scripts\python.exe tait_poll_to_kml.py --config radios.example.json --port COM3 --baud 9600 --output polled_locations.kml
~~~
CLI options include --return-id for an explicit eight-digit SDM response destination, --response-timeout (default 15 seconds), --command-timeout (5 seconds), --poll-gap (2 seconds), --lead-in-ms (200 milliseconds) and --once. The website does not expose these advanced options. Consult --help for syntax.

## Append and replay
Existing KML is refused without --append. Appending preserves earlier session folders and starts a new session. Raw/event logs append when specified. Use one writer per output file. Replaying the same capture with append can duplicate file points.

Replay without hardware:
~~~text
.\.venv\Scripts\python.exe tait_to_kml.py --input capture.txt --output replay.kml --reference-date 2026-10-31
~~~
Replace the reference date with the capture date for binary messages lacking month/year. Notification-only captures contain no positions to recover. To watch CLI output live, start the companion with --kml trip.kml while leaving its own radio session stopped.

<!-- PAGE -->
# 14 Release contents and acceptance checks

RELEASE.json records version, date and source revision. SHA256SUMS.txt lists checksums of packaged files; the separate archive checksum identifies the ZIP. No live captures, positions, cache database, operational PDFs, credentials, virtual environment or source-control metadata are included.

## Package layout
| Item | Purpose |
| README_FIRST.md | Quick installation and startup |
| VERSION and RELEASE.json | Version number and source revision |
| requirements-all.txt | Core and optional PDF dependency entry point |
| start-windows.cmd and start-macos.command | Launch through the local environment |
| tait_to_kml.py and tait_poll_to_kml.py | Standalone receiver and poller |
| radio-map | Companion, browser assets and PDF dependencies |
| tests and radio-map/tests | Logger, poller, companion and browser-logic tests |
| docs | Word guide and editable text source |

## Verification scope
VALIDATION.txt records release test results, interpreter and dependency versions. Serial tests use simulated IO and do not certify all TAIT hardware or programming. Mac hardware has not been tested. Node.js is required only for browser-logic tests, not normal operation. Python, dependency wheels and radio drivers are not embedded.

## Acceptance check on the intended system
1. Confirm a fresh, correctly placed report from a known radio in Listen mode.
2. If polling is required, confirm a matched reply from one target before adding others.
3. Confirm that the sender identity/suffix and timestamp are understood.
4. Open a second LAN viewer if sharing is required.
5. Check required cached views or a stored PDF without internet, keeping the companion running.
6. Stop cleanly and confirm KML, capture and event files exist.

## Further references
Python downloads: https://www.python.org/downloads/
Virtual environments: https://docs.python.org/3/library/venv.html
Port listing: https://pyserial.readthedocs.io/en/latest/tools.html

# 15 Waypoints and on demand radio polls

## Create and view waypoint groups

Open Panels → Waypoints. Enter a group name and select Add group. Select a group to see its waypoints. Use Show group on map to control its purple markers. Select Locate beside a waypoint to centre the map on it.

Enter a waypoint name and choose Latitude / longitude for decimal degrees, or MGRS (WGS84) for a full grid reference such as 55H CU 32838 09126. MGRS places the marker at the centre of the grid square. To choose a location visually, select Pick on map and click the map. Select Add waypoint to save.

Use Edit or Delete beside a waypoint to manage it. Groups are stored in the browser that created them. Export a CSV to share them or move them to another browser.

## Import and export waypoint CSV files

Select Export CSV to download all waypoint groups. To import, select Import CSV and choose a file up to 2 MB. Use the headers group,name,latitude,longitude for decimal degrees or group,name,mgrs for full WGS84 MGRS references.

Import adds new groups or merges rows into groups with the same name. A waypoint with the same name and coordinates in that group is skipped.

## Request a fresh radio position

In Radio connection, start a Poll radios for location session with the radio’s full ID in the poll list. In Radio positions, select Poll beside the radio. A four-digit AVL suffix is matched against the configured poll list.

The companion queues the request behind an active poll and respects channel busy, PTT and minimum poll spacing. A queued request does not confirm a reply. Check Last heard for a new report or open Radio connection → Live diagnostics to see the poll and any timeout.
