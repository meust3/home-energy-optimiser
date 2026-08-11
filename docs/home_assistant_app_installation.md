# Home Assistant App installation

Version `0.2.1` is installed and collecting successfully on Home Assistant OS 18.1.
Version `0.3.2` packages the experimental administrator-only Ingress dashboard with
improved sparse-data presentation and is a release candidate until the image and
update are verified on that host.

## Publish and install

The repository root contains `repository.yaml` and one App folder,
`home_energy_optimiser/`, so the GitHub repository can be added directly.

1. After review, commit and privately push the release-candidate changes, then
   validate a full image build.
2. Only after that validation, create the immutable tag matching `config.yaml` and
   Docker `APP_SOURCE_REF` (`v0.3.2`).
3. In Home Assistant, open **Settings > Apps > App store**.
4. Open the repository menu, choose **Repositories**, and add
   `https://github.com/meust3/home-energy-optimiser`.
5. Refresh the store and open **Home Energy Optimiser**.
6. Install it, but do not start it yet (or use **Update** for an existing v0.2.1
   installation).
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
8. Open **Energy Optimiser** from the Home Assistant sidebar as an administrator.
9. Confirm Overview loads, the read-only badge is visible, nested Ingress assets
   load, and direct port access is not configured.
10. Check History, Forecasts, Reserve, and Data Quality. Sparse forecasts or reserve
    data must show an empty/unavailable state rather than trigger a calculation.

## Updates and local build

Increment `config.yaml` for every App release, point `APP_SOURCE_REF` at the matching
immutable Git tag, push/tag, then use **Update information** in the App store and
install the offered update. Normal updates require no SSH copying.

For an amd64 build test from a committed/pushed ref:

```powershell
docker build --platform linux/amd64 `
  --build-arg APP_SOURCE_REF=<git-tag-or-commit> `
  --build-arg BUILD_VERSION=<version> `
  --tag home-energy-optimiser:<version> `
  home_energy_optimiser
python tools/test_home_assistant_app_container.py `
  --image home-energy-optimiser:<version> --use-image-files
```

The Dockerfile downloads the canonical application source because Supervisor
builds with the App folder as its context; this avoids duplicating collector code
inside the deployment wrapper.

For the installed v0.2.1 App, publish and apply the reviewed v0.3.2 release candidate
as follows:

1. Create a Home Assistant backup containing the v0.2.1 App and its configuration.
   This is an App rollback artifact, not a PostgreSQL backup.
2. Push the reviewed commit, verify an amd64 image from its commit SHA, then create
   and push tag `v0.3.2` only when that validation passes. Repeat the image build
   from that tag.
3. In **Settings > Apps > App store**, choose **Check for updates** or **Update
   information** from the repository menu.
4. Open **Home Energy Optimiser**, confirm version `0.3.2` is offered, and select
   **Update**. Preserve the existing App configuration.
5. Start the App if Supervisor does not start it automatically, then verify the
   startup and first collection using the checklist above.

## Roll back to v0.2.1

If v0.3.2 fails before real-host validation, stop it and restore the pre-update Home
Assistant backup containing App v0.2.1 and its options. If that backup is unavailable,
publish the immutable `v0.2.1` source through a temporary private/local App repository
and reinstall it with the preserved options. PostgreSQL remains external and is not
removed or rolled back with the App. Confirm exactly one collector resumes and that
the latest observation advances. Do not start a Windows fallback collector at the
same time.
