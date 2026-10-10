# plugins

Built-in event types, written against `smartnav-sdk` exactly as a club's own plugin would be, so they double as examples:

- `line`: ordered controls, fastest time wins
- `score`: points per control, time limit in minutes, late penalty per started minute
- `scatter`: a required number of controls in any order, then the finish; fastest time wins

The point values and other parameters for each event are set on the host and are never sent to the phone. See `docs/contract-v1.md`.

No code yet.
