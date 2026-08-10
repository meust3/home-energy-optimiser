# Home Assistant App installation

These are release-candidate instructions. The App has not yet completed its first
installation and operational validation on the real HAOS NUC, and version `0.2.0`
has not been tagged or published.

## Publish and install

The repository root contains `repository.yaml` and one App folder,
`home_energy_optimiser/`, so the GitHub repository can be added directly.

1. After review, push the release-candidate commit and validate a full image build.
2. Create the immutable tag matching `config.yaml` and the Docker
   `APP_SOURCE_REF` (planned as `v0.2.0`).
3. In Home Assistant, open **Settings > Apps > App store**.
4. Open the repository menu, choose **Repositories**, and add
   `https://github.com/meust3/home-energy-optimiser`.
5. Refresh the store and open **Home Energy Optimiser**.
6. Install it, but do not start it yet.
7. Enter the configuration below, save, enable **Start on boot** and **Watchdog**,
   then start the App.

Required values (password deliberately omitted):

```yaml
db_host: <Synology LAN DNS name or address>
db_port: 55432
db_name: home_energy
db_user: energy_app
timezone: Australia/Brisbane
health_max_observation_age_seconds: 900
```

Set `db_password` in the App configuration UI. Do not paste it into logs or
documentation. No Home Assistant token is entered; Supervisor supplies one at
runtime.

## First-start verification

1. Confirm startup logs show backend PostgreSQL, the expected host, port, database,
   and username but no password or full URL.
2. Confirm the schema check reports revision `20260810_01` and the read-only Home
   Assistant readiness check passes.
3. Wait through the next clock-aligned five-minute boundary.
4. Confirm a `Saved slot ... No command was issued` log entry appears.
5. From another trusted machine configured with `energy_readonly`, run
   `python tools/check_database.py` and `python tools/inspect_history.py --limit 5`.
6. Confirm the newest PostgreSQL slot advances and there is only one collector.
7. Confirm Watchdog remains enabled and no SQLite database appears in App data.

## Updates and local build

Increment `config.yaml` for every App release, point `APP_SOURCE_REF` at the matching
immutable Git tag, push/tag, then use **Update information** in the App store and
install the offered update. Normal updates require no SSH copying.

For an amd64 build test from a committed/pushed ref:

```powershell
docker build --platform linux/amd64 `
  --build-arg APP_SOURCE_REF=<git-tag-or-commit> `
  --build-arg BUILD_VERSION=<version> `
  home_energy_optimiser
```

The Dockerfile downloads the canonical application source because Supervisor
builds with the App folder as its context; this avoids duplicating collector code
inside the deployment wrapper.
