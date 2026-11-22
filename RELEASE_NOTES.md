# Version 1.2

Released 23 November 2026.

- Update the illustrated user guide and installation documentation for the current panel layout.
- Add a saved Show waypoint names option.
- Add individual radio deletion with a compact trashcan icon and restore support.
- Match Poll, Edit and Delete button styles and heights.
- Show response age and conditional Last Position Received with elapsed age.
- Preserve Leaflet script bytes on Windows for its integrity check.

- Track last heard from received radio responses, including no-fix reports, and show GPS status separately from the last known position.
- Add named waypoint groups under Panels â†’ Waypoints. Place a waypoint by clicking the map or entering decimal latitude and longitude or a full WGS84 MGRS reference.
- Show or hide groups, locate individual points, and import or export waypoint groups as CSV.
- Add Poll to the Radio positions list. On-demand requests use the active Poll radios session and its configured radio IDs.
- Continue companion startup when the computer hostname cannot be resolved.

# Version 1.0

Initial packaged release of the current TAIT Radio Map application.

- Listen for supported TAIT/NMEA position reports or poll a configured ID list.
- Save timestamped KML, raw capture and event logs.
- Share read-only positions with LAN viewers through one companion.
- Search, hide/show, name and colour radios; select track-history windows.
- Configure map styles, MGRS readouts and coordinate grid overlays.
- Retain viewed map tiles with a size limit and clear controls.
- Import supported ISO geospatial PDFs for offline map display.
- Handle reversed/off-page PDF frames and expected browser socket cancellations.
- Include Windows/Mac launchers and illustrated Word installation/user guide.

This is a source release with external Python dependencies. Mac hardware and
model-specific polling compatibility require local acceptance testing.
