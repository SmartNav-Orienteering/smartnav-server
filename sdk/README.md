# sdk

`smartnav-sdk` is the small, stable package that event-type plugins depend on. It will contain:

- Base classes for an event type: validate the course, detect punches (default provided), score a run, rank results
- Data types: `Course`, `Track`, `Punch`, `Result`
- A test harness for running a plugin against sample tracks

Plugins register themselves through the Python entry point group `smartnav.event_types`, so the server finds them automatically once installed.

No code yet.
