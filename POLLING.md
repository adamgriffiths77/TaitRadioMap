# TAIT location polling

`tait_poll_to_kml.py` is separate from the existing receiver. Keep
`tait_to_kml.py` beside it: it imports the parsers and KML writer without
executing or changing the original logger. Python 3.10+ and the same
`requirements.txt` are used.

Edit `radios.example.json` to list the radios and the interval for each radio
in seconds. For example, 3000030 every 60 seconds and 3000029 every 120 seconds
are included. IDs are padded to eight digits for the TAIT SDM address; make
sure these match the field radios' programmed SDM identities. They are not
necessarily the same as DMR voice IDs.

Preview commands without transmitting or writing files:

```powershell
python tait_poll_to_kml.py --config radios.example.json --dry-run
```

Run continuously:

```powershell
python tait_poll_to_kml.py --config radios.example.json --port COM3 --baud 9600 --output polled_locations.kml --raw-log polled_capture.txt --event-log polled_events.txt --verbose
```

Add `--append` to resume an existing KML, or `--once` to poll each radio once
and exit after responses/timeouts. Press Ctrl+C to stop continuous polling.
Use the correct port, baud and optional `--flow-control xonxoff` or `rtscts`.
The serial port must be available; stop the original logger before using the
poller on that same port. Use separate output/log filenames for each program.

The poller uses the TN-856 conventional CCDI/FFSK GPS polling command. Both
the base and field radios must be programmed to support and respond to it.
Receiving DMR direct-send location text does not itself establish support for
this polling method. Hardware compatibility must be tested on your channel and
radio programming; this script has only been tested with simulated serial IO.

By default the field radio returns its report to its programmed dispatch
address. Set `--return-id 03001042` (replace with your base's actual SDM ID)
to request an explicit return address instead. `--lead-in-ms 200` controls
key-up delay (20 ms increments, up to 5100 ms).

Only one radio is polled at a time. The script synchronizes with a local model
query, waits for command prompts, retrieves buffered SDMs, defers new RF polls
while receiver-busy or PTT indications are active, and leaves a configurable
`--poll-gap 2` seconds between polls/after busy clears. It waits up to
`--response-timeout 15` seconds for a matching location/status response;
`--command-timeout 5` controls local serial-command timeouts. A command timeout
requires a fresh prompt before further commands. It does not retry immediately.

Intervals are minimum spacing between starts of polls to the same radio.
Initially all radios are due. Busy channels, other radios, and response waits
can delay a poll. Missed intervals do not accumulate into a burst of catch-up
requests. Increase intervals or response timeout to suit your radio network.

Outputs match the receiver: valid KML, per-radio tracks, timestamped points,
radio-ID placemark names, raw RX bytes, and timestamped RX/TX events. Logs
always append. Existing KML requires `--append`; previous content is retained
in separate sessions. Binary AVL names remain the transmitted four-digit
suffix. Configured poll targets are not used to invent a fuller sender ID.
Duplicate suffixes in the configured list are rejected because binary reports
cannot distinguish them. Direct-send DMS and NMEA are also decoded; only a
response with an explicit matching identity completes a poll early. Other
valid incoming locations are saved without being attributed to the poll target.
Raw NMEA with no sender ID may be saved as Unknown radio and leave the poll
waiting until timeout. A no-fix/status report completes a matching poll but
adds no KML point. Old data is not plotted as a current position.

Protocol source: Tait TN-856-AN version 2.0, sections 6–9:
https://manuals.plus/m/a1c43b0265ae124ba80e0813c7d015acb182ce45073a70f972c1a5c5ceb26016.pdf
