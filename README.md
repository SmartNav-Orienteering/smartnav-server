# SmartNav Server

SmartNav lets orienteering clubs run GPS-checked navigation events on their own low-cost server, instead of paying for a commercially hosted service.

The system has two parts:

1. **The host** (this repository) manages events, publishes course packages, receives participants' tracks and produces results.
2. **A minimalist smartphone app** (iOS and Android) that downloads a course, records the track, beeps at controls and uploads the run.

Participants always navigate with a paper map. The phone only detects punches and times the run. All scoring happens on the host, so new rules never need an app update.

## Event types

Scoring is done by plugins. The first release will include:

| Event type | Summary |
| --- | --- |
| `line` | Visit all controls in a fixed order; fastest time wins |
| `score` | Visit any controls within a time limit (typically 60 minutes); most points wins, with late penalties per started minute |
| `scatter` | Visit a set number of controls in any order and return to the finish; fastest time wins |

Clubs can write their own event types as Python plugins.

## Repository layout

| Folder | Contents |
| --- | --- |
| `docs/` | Specifications, starting with the [app–server contract](docs/contract-v1.md) |
| `server/` | The host application (Python, FastAPI, SQLite) |
| `sdk/` | `smartnav-sdk`: the small package plugin authors depend on |
| `plugins/` | Built-in event types (`line`, `score`, `scatter`), written against the SDK |

## Status

Early design. The app–server contract (v1) is drafted; server code has not started yet. Open design questions are tracked as GitHub Issues.

## Licence

MIT. See [LICENSE](LICENSE).
