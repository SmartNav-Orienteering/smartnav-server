# Installing SmartNav on a Synology NAS

This guide sets up the SmartNav server on a Synology NAS running DSM 7.2 or later, and makes it reachable from participants' phones over HTTPS.

## 1. Check your NAS can run containers

Open **Package Center** and search for **Container Manager**. If it is listed, install it. If it isn't, your model cannot run containers; use a small VPS or a Raspberry Pi instead (the Docker steps are the same).

1 GB of RAM is enough for SmartNav.

## 2. Copy SmartNav to the NAS

1. In **File Station**, create a shared folder or a folder such as `docker/smartnav`.
2. Download this repository from GitHub (green **Code** button > **Download ZIP**), unzip it on your computer, and upload the contents into `docker/smartnav`.
3. In that folder, copy `.env.example` to `.env` and edit it:
   - `SMARTNAV_BASE_URL`: the public address phones will use, for example `https://nav.yourclub.org.au`.

## 3. Start the server

1. Open **Container Manager** > **Project** > **Create**.
2. Name: `smartnav`. Path: the `docker/smartnav` folder. Source: **Use existing docker-compose.yml**.
3. Click **Next**, then **Done**. The first build takes a few minutes.
4. On a computer on the same network, open `http://<NAS address>:8000/admin` and create the owner account.

Optional: try it with sample data. In Container Manager > **Container** > `smartnav` > **Action** > **Open terminal**, create a terminal and run `smartnav demo`.

## 4. Make it reachable from phones (HTTPS)

Phones need to reach the server from the internet over HTTPS (iPhones require HTTPS). Choose one option.

### Option A: Cloudflare Tunnel (recommended)

No router ports are opened, and it works even if your internet provider uses CGNAT. You need a domain name managed by Cloudflare (a free Cloudflare account; domains cost about A$15–25 a year).

1. In the Cloudflare dashboard, go to **Zero Trust** > **Networks** > **Tunnels** > **Create a tunnel** (type Cloudflared).
2. Copy the tunnel token and put it in `.env` as `CLOUDFLARE_TUNNEL_TOKEN=…`.
3. Add a **Public hostname**: subdomain `nav`, your domain, service type `HTTP`, URL `smartnav:8000`.
4. In Container Manager, stop the project, then rebuild it with the tunnel. The simplest way is to edit `docker-compose.yml` and delete the line `profiles: ["tunnel"]` under `cloudflared`, then start the project again.
5. Visit `https://nav.yourdomain` to check.

### Option B: Synology's built-in tools

Free, but it exposes the NAS directly to the internet, so keep DSM up to date.

1. **Control Panel** > **External Access** > **DDNS**: add a free `yourclub.synology.me` address.
2. **Control Panel** > **Security** > **Certificate**: add a Let's Encrypt certificate for that address.
3. **Control Panel** > **Login Portal** > **Advanced** > **Reverse Proxy** > **Create**:
   - Source: HTTPS, hostname `yourclub.synology.me`, port 443.
   - Destination: HTTP, `localhost`, port 8000.
4. On your router, forward port 443 to the NAS.
5. Set `SMARTNAV_BASE_URL=https://yourclub.synology.me` in `.env` and restart the project.

## 5. Back up

Everything SmartNav stores is in `docker/smartnav/data`: the database, every submitted run, and the map images. Tracks are kept indefinitely, so include this folder in **Hyper Backup**, ideally with a copy off-site (USB drive kept elsewhere, or a cloud destination).

## 6. Updating

Download the new version, replace the files in `docker/smartnav` **except** `data` and `.env`, then in Container Manager stop the project and choose **Build** again.

## Adding club plugins

Create `data/plugins.txt` listing your plugin packages (one per line, in pip format, for example `git+https://github.com/yourclub/smartnav-goat.git`). Restart the project; the plugins are installed at start-up and appear as new event types.
