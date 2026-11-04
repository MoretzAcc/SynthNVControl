# Legacy issues deliberately not carried forward

The predecessor is retained under `old_reference_code/` for behavioral
reference only. The following markers record design decisions in the rewrite.

- **LEGACY-001:** The advertised EEPROM command was unreachable through the
  old validation flow. It is an explicit, confirmed action in this application.
- **LEGACY-002:** One mutable callback state allowed concurrent commands to
  overwrite one another. The transport has one serialized request queue.
- **LEGACY-003:** An empty non-blocking read after 50 ms was treated as a full
  response. Queries now wait for a newline response with a bounded timeout.
- **LEGACY-004:** Port-open errors could terminate the GUI. They are caught and
  shown with platform-specific access guidance.
- **LEGACY-005:** A failed write could leave stale callback state. A request is
  completed or failed atomically by the transport worker.
- **LEGACY-006:** Ports without USB VID/PID were hidden. The device selector
  shows all serial ports.
- **LEGACY-007:** Values only had basic syntax checks. The command schema now
  validates booleans, RF-power bounds, decimal values, and hexadecimal fields.
- **LEGACY-008:** Responses were untyped strings. The application keeps
  normalized values for comparison and JSON exchange; unknown device responses
  remain visible rather than being silently coerced.
- **LEGACY-009:** The connection was never explicitly closed. It is closed
  during normal window shutdown.
- **LEGACY-010:** UI, transport, protocol, and application startup were one
  import-unsafe file. They are separate modules with a console-script entry
  point.

The protocol has an important documented special case: frequency writes use
MHz, while queried frequency values are reported in kHz. The command schema
converts only query responses to MHz before showing or exporting them.
