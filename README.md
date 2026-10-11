# SmartNav Server

SmartNav lets orienteering clubs run GPS-checked navigation events on their own low-cost server, instead of paying for a commercially hosted service.

The system has two parts:

1. **The host** (this repository) manages events, publishes course packages, receives participants' tracks and produces results.
2. **A minimalist smartphone app** (iOS and Android, not yet built) that downloads a course, records the track, beeps at controls and uploads the run.

Participants always navigate with a paper map. The phone only detects punches and times the run. All scoring happens on the host, so new rules never need an app update.

## What the server does

- **Admin site** (`/admin`): owner and delegate logins; folders and series; create, edit, publish, archive and delete events; import controls from KML/KMZ and a map image from KMZ; host-only scoring settings; QR code for the paper map; review tools to accept or deny controls, correct names, disqualify and rescore; CSV export; change log.
- **App API** (`/v1/…`): the contract in [docs/contract-v1.md](docs/contract-v1.md). Interactive API docs are at `/v1/docs`.
- **Public results site** (`/`): results per event and class, series standings, track maps over the club map with replay, and a GPX upload page for runs recorded on a watch.

### Event types

| Event type | Summary |
| --- | --- |
| `line` | Visit all controls in a fixed order; fastest time wins |
| `score` | Visit any controls within a time limit (typically 60 minutes); most points wins, with late penalties per started minute |
| `scatter` | Visit a set number of controls in any order and return to the finish; fastest time wins |

Clubs can add their own event types as Python plugins. See [sdk/README.md](sdk/README.md).

### Rules built in

- A participant can run an event as often as they like. Only their **first run** is ranked, in the event results and the series. Later runs are listed as unranked repeats.
- Runs are matched to the same person **by name only** (ignoring case, accents and extra spaces). Organisers can correct a misspelt name.
- No manual punching. Doubtful controls are flagged for the organiser, who accepts or denies them.
- Tracks are kept indefinitely and are public.
- Year of birth is used only to work out the age class and is never published.

## Running it

### With Docker (recommended, including Synology)

```
cp .env.example .env        # then edit SMARTNAV_BASE_URL
docker compose up -d
```

Open `http://<this machine>:8000/admin` and create the owner account. All data is kept in the `data` folder; back it up.

To make the server reachable from phones over HTTPS, see **[docs/install-synology.md](docs/install-synology.md)**, which covers Cloudflare Tunnel and Synology's built-in reverse proxy.

### On a Windows desktop (for trying it out)

Install Python 3.12 from python.org (tick **Add python.exe to PATH**), then double-click **`start-windows.bat`**. The first run installs SmartNav and offers to add sample data; after that it starts straight away and opens the admin site at http://localhost:8000/admin. Close the window to stop the server. A desktop is fine for testing, but phones need an always-on HTTPS server for real events.

### Without Docker

Python 3.11 or later:

```
python -m venv venv
venv/bin/pip install ./sdk ./plugins ./server
SMARTNAV_BASE_URL=http://localhost:8000 venv/bin/smartnav serve
```

### Try it with sample data

```
smartnav demo          # creates a sample series with three events and simulated runs
```

(In Docker: `docker compose exec smartnav smartnav demo`.) Delete the demo events from the admin site when you have finished.

### Other commands

| Command | Does |
| --- | --- |
| `smartnav create-owner --email you@club.org --name "Your Name"` | Create an owner account from the command line |
| `smartnav reset-password --email you@club.org` | Reset a forgotten password |
| `smartnav rescore EVENT_ID` | Rescore every run of an event |
| `smartnav plugins` | List installed event types |

### Settings

| Environment variable | Meaning |
| --- | --- |
| `SMARTNAV_BASE_URL` | Public HTTPS address, e.g. `https://nav.yourclub.org.au`. Used in QR codes and by the app |
| `SMARTNAV_DATA_DIR` | Folder for the database, runs and map images (default `./data`, `/data` in Docker) |
| `SMARTNAV_SECRET_KEY` | Secret for login cookies. Generated and saved in the data folder if not set |

## Repository layout

| Folder | Contents |
| --- | --- |
| `docs/` | Specifications and guides, starting with the [app–server contract](docs/contract-v1.md) |
| `server/` | The host application (Python, FastAPI, SQLite) |
| `sdk/` | `smartnav-sdk`: the small package plugin authors depend on |
| `plugins/` | Built-in event types (`line`, `score`, `scatter`), written against the SDK |

## Development

```
python -m venv venv
venv/bin/pip install -e ./sdk -e ./plugins -e "./server[test]"
venv/bin/python -m pytest server/tests plugins/tests
```

## Status

First working version of the server. The phone app is not built yet; the API it will use is complete and tested with simulated runs.

Known limits in this version: no rate limiting on uploads; the map image is shown unrotated if the KMZ overlay is rotated; background map tiles come from OpenStreetMap when no club map is imported.

## Licence

MIT. See [LICENSE](LICENSE). Bundles [Leaflet](https://leafletjs.com) (BSD-2-Clause).
