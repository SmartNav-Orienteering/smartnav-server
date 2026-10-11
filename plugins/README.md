# plugins

`smartnav-plugins`: the built-in event types, written against `smartnav-sdk` exactly as a club's own plugin would be, so they double as examples.

| ID | Rules | Host-only parameters |
| --- | --- | --- |
| `line` | All controls in order; fastest time wins. Missing or out-of-order controls are a mispunch | none |
| `score` | Any controls within the time limit; most points wins, ties to the faster time. Late penalty per started minute over the limit | points per control, default points, late penalty per minute, zero score after N minutes over, finish required |
| `scatter` | The required number of controls in any order, then the finish; fastest time wins | number of controls required, finish required |

Point values and other parameters are set in the admin site and are never sent to the phone. Run the tests with `python -m pytest plugins/tests`.
