"""``granum`` -- the command line interface.

Every command accepts the same global options, and every option is also readable from an
environment variable. ``granum config show --detail`` reports where each value came
from, which is the fastest way to debug an install inside someone else's infrastructure.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from granum.core.config import OPTIONS, Config, Tier, set_config
from granum.core.url import Url, get_registered_url_aliases, get_url_alias_origins

if TYPE_CHECKING:
    from granum.core.index import Index
    from granum.licensing import Licensing

app = typer.Typer(
    name="granum",
    help="Inspect and improve ML training data sample by sample.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(name="config", help="Inspect and manage Granum configuration.")
app.add_typer(config_app)
thumbnails_app = typer.Typer(
    name="thumbnails", help="Manage the downsampled image copies a dataset publishes."
)
app.add_typer(thumbnails_app)
import_app = typer.Typer(name="import", help="Check and import external datasets.")
app.add_typer(import_app)
app_app = typer.Typer(
    name="app", help="Install Granum as an app: background service at login and a menu launcher."
)
app.add_typer(app_app)
access_app = typer.Typer(name="access", help="Manage authenticated, single-workspace shared access.")
app.add_typer(access_app)
backup_app = typer.Typer(name="backup", help="Create and restore checksummed local project snapshots.")
app.add_typer(backup_app)
integrity_app = typer.Typer(name="integrity", help="Snapshot and verify referenced media bytes.")
app.add_typer(integrity_app)

_STATE: dict[str, object] = {}


def _config() -> Config:
    config = _STATE.get("config")
    if not isinstance(config, Config):
        config = Config.load()
        _STATE["config"] = config
        set_config(config)
    return config


@app.callback()
def main(
    project_root_url: str | None = typer.Option(
        None, "--project-root-url", envvar="GRANUM_PROJECT_ROOT_URL",
        help="Location for reading and writing Granum project data.",
    ),
    log_level: str | None = typer.Option(
        None, "--log-level", envvar="GRANUM_LOG_LEVEL", help="Log level for the Granum logger."
    ),
    config_file: str | None = typer.Option(
        None, "--config-file", help="Use this config file instead of the default locations."
    ),
    no_config_file: bool = typer.Option(
        False, "--no-config-file", help="Ignore config files; use flags and environment only."
    ),
) -> None:
    overrides: dict[str, object] = {}
    if project_root_url:
        overrides["project-root-url"] = project_root_url
    from granum import addons

    addons.activate()
    if log_level:
        overrides["log-level"] = log_level
    config = Config.load(
        overrides=overrides,
        config_file=config_file,
        use_config_files=not no_config_file,
    )
    _STATE["config"] = config
    set_config(config)


@app.command()
def version() -> None:
    """Print the Granum version."""
    from granum import __version__

    typer.echo(f"granum {__version__}")


@app.command("build-info")
def show_build_info() -> None:
    """Print the installed build's provenance, or identify a mutable source checkout."""
    import json

    from granum.build_info import build_info

    typer.echo(json.dumps(build_info(), indent=2))


@app.command()
def service(
    host: str = typer.Option("127.0.0.1", "--host", help="Address to bind to."),
    port: int | None = typer.Option(None, "--port", help="Port to bind to. Defaults to config (8000)."),
    reindex_interval: float = typer.Option(
        None, "--scan-interval", help="Seconds between index scans. Defaults to config."
    ),
    cache_size: int = typer.Option(
        256 * 1024 * 1024, "--cache-size", help="In-memory media cache size, in bytes."
    ),
    cache_timeout: float = typer.Option(
        300.0, "--cache-timeout", help="Media cache entry lifetime, in seconds."
    ),
    watch: bool = typer.Option(
        True, "--watch/--no-watch", help="Re-scan project locations in the background."
    ),
    allow_host: list[str] = typer.Option(
        [], "--allow-host", help="Extra Host header value to accept, e.g. a machine name. Repeatable."
    ),
    allow_origin: list[str] = typer.Option(
        [], "--allow-origin", help="Extra browser origin allowed to call the API. Repeatable."
    ),
    data_root: list[str] = typer.Option(
        [], "--data-root", help="Folder datasets may be imported from. Repeatable. Defaults to config."
    ),
    open_browser: bool = typer.Option(
        False, "--open", help="Open the dashboard in a web browser once the service is up."
    ),
    auth_file: Path | None = typer.Option(None, "--auth-file", help="Owner-only shared-access user registry; enables authenticated mode."),
    tls_cert: Path | None = typer.Option(None, "--tls-cert", help="TLS certificate for direct network access."),
    tls_key: Path | None = typer.Option(None, "--tls-key", help="TLS private key for direct network access."),
) -> None:
    """Start the Object Service and the dashboard.

    It reads your data locally and serves it to the dashboard. Nothing is uploaded.
    """
    import uvicorn

    from granum.core.index import Index, set_index
    from granum.service.app import create_app
    from granum.service.auth import SharedAccess, is_loopback
    from granum.service.cache import ByteCache

    loopback = is_loopback(host)
    if not loopback and (auth_file is None or tls_cert is None or tls_key is None):
        raise typer.BadParameter("Network binding requires --auth-file, --tls-cert and --tls-key. Otherwise bind to loopback behind a TLS proxy.")
    if (tls_cert is None) != (tls_key is None):
        raise typer.BadParameter("Provide both --tls-cert and --tls-key.")
    try:
        access = SharedAccess.from_file(auth_file) if auth_file else None
    except (OSError, ValueError, KeyError) as exc:
        raise typer.BadParameter(f"Invalid access configuration: {exc}") from exc
    config = _config()
    port = port or int(config.get("service.port"))
    index = Index(config=config)
    typer.echo(f"granum: indexing {config.project_root} ...")
    index.refresh()
    typer.echo(f"granum: {len(index.entries())} objects found")
    if watch:
        index.start(reindex_interval)
    set_index(index)

    hosts = list(allow_host) + ([] if loopback or host in {"0.0.0.0", "::"} else [host])
    licensing = _service_licensing(index, str(config.get("licence.server") or ""))
    application = create_app(
        index=index,
        config=config,
        cache=ByteCache(max_bytes=cache_size, ttl_seconds=cache_timeout),
        allowed_hosts=hosts,
        allowed_origins=list(allow_origin) or None,
        data_roots=list(data_root) or None,
        licensing=licensing,
        access=access,
    )
    shown = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    address = f"{'https' if tls_cert else 'http'}://{shown}:{port}"
    if access:
        typer.echo("granum: authenticated shared workspace; all accounts can read all projects. HTTPS is required.")
    from granum.service.app import _dashboard_dir

    if _dashboard_dir() is None:
        typer.echo(
            "granum: the dashboard is not built, so only the API is served. "
            "Build it with: cd web && npm ci && npm run build",
            err=True,
        )
    typer.echo(f"granum: dashboard on {address}  (API docs at /docs)")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(address)).start()
    try:
        uvicorn.run(application, host=host, port=port, log_level="warning",
                ssl_certfile=str(tls_cert) if tls_cert else None, ssl_keyfile=str(tls_key) if tls_key else None,
                proxy_headers=loopback, forwarded_allow_ips="127.0.0.1,::1")
    finally:
        licensing.stop()
        index.stop()


@backup_app.command("create")
def backup_create(project: str, output: Path = typer.Option(..., "--output")) -> None:
    """Back up a stopped local project, including media and recorded model weights."""
    import json

    from granum.core.backup import backup_project
    from granum.errors import GranumError

    try:
        typer.echo(json.dumps(backup_project(project, output, root=_config().project_root), indent=2))
    except (GranumError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@backup_app.command("restore")
def backup_restore(archive: Path, name: str | None = typer.Option(None, "--name"),
                   max_gib: int = typer.Option(100, "--max-gib", min=1, max=10000)) -> None:
    """Verify a snapshot, relocate references, and publish under a new project name."""
    import json

    from granum.core.backup import restore_project
    from granum.errors import GranumError

    try:
        typer.echo(json.dumps(restore_project(archive, root=_config().project_root, name=name, max_bytes=max_gib * 1024**3), indent=2))
    except (GranumError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@integrity_app.command("snapshot")
def integrity_snapshot(project: str, output: Path = typer.Option(..., "--output")) -> None:
    """Record SHA-256 identities of every image referenced by a project's versions."""
    import json

    from granum.core.index import Index
    from granum.core.integrity import media_manifest
    from granum.core.objects.table import Table
    from granum.core.storage import locked
    from granum.errors import GranumError

    try:
        with locked(Url(output)):
            if output.exists() or output.is_symlink():
                raise typer.BadParameter("choose a new manifest path; integrity baselines are never overwritten")
            index = Index(config=_config())
            index.refresh(force=True)
            manifest = media_manifest(Table.from_url(e.url) for e in index.tables(project) if e.type_name == "table")
            if not manifest["files"]:
                raise typer.BadParameter("no image references found for this project")
            Url(output).write_text(json.dumps(manifest, indent=2))
    except (GranumError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Recorded {len(manifest['files'])} media identities.")


@integrity_app.command("verify")
def integrity_verify(manifest: Path) -> None:
    """Report changed and missing media without modifying the baseline or the data."""
    import json

    from granum.core.integrity import verify_media
    from granum.errors import GranumError

    try:
        result = verify_media(json.loads(manifest.read_text()))
    except (GranumError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, indent=2))
    if not result["ok"]:
        raise typer.Exit(1)


@access_app.command("add-user")
def access_add_user(
    name: str,
    file: Path = typer.Option(..., "--file", help="Access registry (outside project data and backups)."),
    role: str = typer.Option("viewer", "--role", help="viewer, annotator, reviewer or admin"),
) -> None:
    """Add/update one account. Password input is hidden and never passed on the command line."""
    import json

    from granum.service.auth import ROLES, SharedAccess, password_hash

    if role not in ROLES:
        raise typer.BadParameter(f"role must be one of {ROLES}")
    users = SharedAccess.from_file(file).users if file.exists() else {}
    password = typer.prompt("Password (12+ characters)", hide_input=True, confirmation_prompt=True)
    try:
        users[name] = {"role": role, "password_hash": password_hash(password)}
        SharedAccess(users)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    file.parent.mkdir(parents=True, exist_ok=True)
    # Owner-only from creation, not just after sensitive data has been written.
    from granum.core.storage import atomic_bytes

    atomic_bytes(file, json.dumps({"version": 1, "users": users}, indent=2).encode(), mode=0o600)
    typer.echo(f"Updated {name} ({role}). Restart the service to apply changes/revocations.")


@import_app.command("coco")
def import_coco_command(
    sources: list[str] = typer.Argument(
        ..., help="Annotation files as SPLIT=PATH (e.g. train=data/train/_annotations.coco.json)."
    ),
    project: str = typer.Option(..., "--project", "-p", help="Project to import into."),
    media: str = typer.Option("full", "--media", help="Check image files: full, sample or none."),
    choose: list[str] = typer.Option(
        [], "--choose", help="Resolve a finding as CODE=OPTION, overriding its default. Repeatable."
    ),
    dataset: str | None = typer.Option(
        None, "--dataset", help="Dataset the splits go into. Defaults to the folder holding the split folders."
    ),
    check_only: bool = typer.Option(False, "--check-only", help="Report findings without importing."),
    fail_on: str = typer.Option(
        "block", "--fail-on", help="Exit non-zero at this severity or worse: block, warn or never."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
) -> None:
    """Preflight a COCO dataset, then import it with the chosen resolutions."""
    import json as _json

    from granum.importing import PreflightError, Source, import_coco, run_preflight

    _config()
    parsed_sources = []
    for item in sources:
        split, sep, path = item.partition("=")
        if not sep:
            split, path = Url(item).parent.name or "train", item
        parsed_sources.append(Source(split=split, annotations=path))
    resolutions = {}
    for item in choose:
        code, sep, option = item.partition("=")
        if not sep:
            typer.echo(f"error: --choose expects CODE=OPTION, got {item!r}", err=True)
            raise typer.Exit(2)
        resolutions[code] = option

    try:
        report = run_preflight(parsed_sources, media=media)
    except PreflightError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    body = report.to_dict()
    if as_json:
        typer.echo(_json.dumps(body, indent=1))
    else:
        marks = {"block": "BLOCK", "warn": "WARN ", "info": "info "}
        typer.echo(f"preflight: {body['summary']['images']} images, {body['summary']['boxes']} boxes -> {report.verdict}")
        for finding in body["findings"]:
            choice = resolutions.get(finding["code"], finding["default"])
            suffix = f"  [{finding['code']} = {choice}]" if finding["options"] else f"  [{finding['code']}]"
            typer.echo(f"  {marks[finding['severity']]} {finding['count']:>7} {finding['unit']:<10} {finding['title']}{suffix}")

    order = {"pass": 0, "info": 0, "warn": 1, "block": 2}
    threshold = {"never": 3, "warn": 1, "block": 2}.get(fail_on)
    if threshold is None:
        typer.echo("error: --fail-on must be block, warn or never", err=True)
        raise typer.Exit(2)
    if check_only:
        raise typer.Exit(1 if order[report.verdict] >= threshold else 0)
    try:
        result = import_coco(report, project_name=project, resolutions=resolutions, dataset_name=dataset)
    except PreflightError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    for table in result.tables:
        typer.echo(f"imported {table['dataset_name']}/{table['split']}: {table['rows']} images, {table['boxes']} boxes -> {table['url']}")
    for effect, count in sorted(result.effects.items()):
        typer.echo(f"  {effect.replace('_', ' ')}: {count}")
    typer.echo(f"report saved to {result.report_url}")


@thumbnails_app.command("create")
def thumbnails_create(
    targets: list[str] = typer.Argument(..., help="Table or Run URLs."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Regenerate existing thumbnails."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without writing."),
) -> None:
    """Publish thumbnails for the images a Table or Run references.

    Point it at a table and everything is derived: which images, and where the
    thumbnails belong. A Run URL stands for every input Table it references.
    """
    from granum.core.objects.base import read_object_payload
    from granum.core.objects.run import Run
    from granum.core.objects.table import Table
    from granum.service import thumbnails as thumbs

    _config()
    totals = {"written": 0, "skipped": 0, "failed": 0, "images": 0}
    for target in targets:
        url = Url(target)
        try:
            payload = read_object_payload(url)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"error: {target}: {exc}", err=True)
            raise typer.Exit(1) from exc

        if payload.get("type") == "run":
            result = thumbs.create_for_run(
                Run.from_url(url), overwrite=overwrite, dry_run=dry_run
            )
        else:
            result = thumbs.create_for_table(
                Table.from_url(url), overwrite=overwrite, dry_run=dry_run
            )
        for key in totals:
            totals[key] += result[key]
        typer.echo(f"{target}: {result['written']} written, {result['skipped']} up to date")

    verb = "would write" if dry_run else "wrote"
    typer.echo(
        f"{verb} {totals['written']} thumbnails for {totals['images']} images "
        f"({totals['skipped']} up to date, {totals['failed']} failed)"
    )


def _local_project_root(config: Config) -> Path:
    root = config.project_root
    if root.scheme not in ("", "file"):
        typer.echo(f"error: the app needs a local project root, not {root}", err=True)
        raise typer.Exit(1)
    return Path(root.path).expanduser()


def _pin_project_root(config: Config, root: Path) -> str | None:
    """Record the project root in the user config, so the service, the launcher and every
    terminal agree on where data lives even if the environment changes later."""
    from granum.core.config import user_config_url

    if config.provenance("project-root-url").tier is Tier.USER:
        return None
    target = user_config_url()
    existing = target.read_text() if target.exists() else ""
    lines = [line for line in existing.splitlines() if not line.startswith("project-root-url:")]
    lines.append(f"project-root-url: {root}")
    target.parent.mkdir()
    target.write_text("\n".join(lines) + "\n")
    return str(target)


@app_app.command("install")
def app_install(
    port: int | None = typer.Option(None, "--port", help="Port for the dashboard. Defaults to config (8000)."),
    autostart: bool = typer.Option(True, "--autostart/--no-autostart", help="Start Granum in the background at login."),
    launcher: bool = typer.Option(True, "--launcher/--no-launcher", help="Add Granum to the application menu."),
) -> None:
    """Install or update the background service and launcher. Project data is never changed."""
    from granum.cli import desktop

    config = _config()
    root = _local_project_root(config)
    port = port or int(config.get("service.port"))
    pinned = _pin_project_root(config, root)
    if pinned:
        typer.echo(f"project root {root} saved in {pinned}")
    try:
        steps = desktop.install(port, root, autostart=autostart, launcher=launcher)
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    for step in steps:
        typer.echo(step)
    if autostart and desktop.has_systemd():
        up = desktop.ensure_running(port, root)
        typer.echo(f"dashboard {'running' if up else 'starting'} on {desktop.url_for(port)}")


@app_app.command("uninstall")
def app_uninstall() -> None:
    """Remove the background service and launcher. Projects and model weights are kept."""
    from granum.cli import desktop

    for step in desktop.uninstall():
        typer.echo(step)
    typer.echo(f"your data is untouched in {_config().project_root}")


@app_app.command("status")
def app_status() -> None:
    """Show whether Granum is installed and running, and where its data lives."""
    from granum.cli import desktop

    config = _config()
    root = _local_project_root(config)
    port = int(config.get("service.port"))
    paths = desktop.AppPaths.for_user()
    service = "not installed"
    if paths.unit.exists():
        service = desktop.systemctl("is-active", desktop.UNIT_NAME).stdout.strip() if desktop.has_systemd() else "installed"
    projects = root / "projects"
    count = sum(1 for p in projects.iterdir() if p.is_dir()) if projects.is_dir() else 0
    rows = [
        ("dashboard", f"{desktop.url_for(port)} ({'up' if desktop.is_up(port) else 'down'})"),
        ("service", f"{service}  {paths.unit if paths.unit.exists() else ''}".rstrip()),
        ("launcher", str(paths.desktop) if paths.desktop.exists() else "not installed"),
        ("projects", f"{count} in {root}"),
        ("model weights", str(desktop.training_dir(root))),
        ("service log", str(paths.state / "service.log")),
    ]
    for name, value in rows:
        typer.echo(f"{name:<14} {value}")


@app.command("open")
def open_dashboard(
    browser: bool = typer.Option(False, "--browser", help="Open in the web browser instead of the Granum window."),
    no_window: bool = typer.Option(False, "--no-window", help="Only make sure the service is running."),
) -> None:
    """Open Granum in its own window, starting the service in the background first if needed."""
    import webbrowser

    from granum.cli import desktop

    config = _config()
    root = _local_project_root(config)
    port = int(config.get("service.port"))
    if desktop.needs_install(port):
        # First launch of the self-contained app, or a newer download: set it up as an app.
        _pin_project_root(config, root)
        try:
            for step in desktop.install(port, root):
                typer.echo(step)
        except RuntimeError as exc:
            typer.echo(f"granum: could not install the background service ({exc}); starting it for this session", err=True)
    # The first start after installing on Windows can take half a minute while the virus
    # scanner reads every new file.
    if not desktop.ensure_running(port, root, wait=90.0 if os.name == "nt" else 20.0):
        message = f"Granum did not start; see {desktop.AppPaths.for_user().state / 'service.log'}"
        typer.echo(f"error: {message}", err=True)
        desktop.show_error(message)
        raise typer.Exit(1)
    address = desktop.url_for(port)
    typer.echo(f"granum: dashboard on {address}")
    if no_window:
        return
    desktop.log_launch_environment()
    if not browser and desktop.window_available():
        try:
            desktop.open_window(port)
            if os.name == "nt":
                desktop.stop_if_idle(port)
            return
        except Exception as exc:  # noqa: BLE001 - any window failure falls back to the browser
            typer.echo(f"granum: the Granum window could not open ({exc}); opening the browser instead", err=True)
    elif not browser and (runner := desktop.installed_runner()) is not None:
        typer.echo(f"granum: opening the window with the installed app ({runner[0]})", err=True)
        os.environ["GRANUM_HANDED_OVER"] = "1"
        os.execv(runner[0], [*runner, "open"])
    elif not browser and os.name == "nt":
        from granum.cli import window as qt_window

        typer.echo(f"granum: the Granum window cannot run on this system ({qt_window.load_error}); "
                   "opening the browser instead", err=True)
        webbrowser.open(address)
        detail = f"\n\nTechnical detail: {qt_window.load_error}" if qt_window.load_error else ""
        # After the browser, since the dialog waits for the person to close it.
        desktop.show_error(
            "Granum runs in your web browser on this PC.\n\n"
            "Its own window needs Windows components this edition of Windows does not have, so "
            "Granum opens in your default browser instead. Everything works the same there." + detail,
            icon="info", once="window-unavailable.txt",
        )
        return
    elif not browser:
        typer.echo(
            "granum: no window toolkit or display was found (the window needs pywebview and WebKitGTK, "
            "or the Granum app); opening the browser instead",
            err=True,
        )
    webbrowser.open(address)


@config_app.command("show")
def config_show(
    target: str | None = typer.Argument(None, help="Show one option in full."),
    detail: bool = typer.Option(False, "--detail", help="Include where each value came from."),
    fmt: str = typer.Option("table", "-f", "--format", help="table or yaml."),
) -> None:
    """Show the resolved configuration."""
    config = _config()

    if target:
        if target not in OPTIONS:
            typer.echo(f"unknown option {target!r}", err=True)
            raise typer.Exit(2)
        option = OPTIONS[target]
        item = config.provenance(target)
        typer.echo(f"{option.name}")
        typer.echo(f"  value       {item.value}")
        typer.echo(f"  source      {item.source} (tier {Tier(item.tier).name.lower()})")
        typer.echo(f"  default     {option.default}")
        typer.echo(f"  env var     {option.env_var}")
        typer.echo(f"  {option.help}")
        return

    if fmt == "yaml":
        typer.echo(config.to_yaml(), nl=False)
        return

    width = max(len(name) for name in OPTIONS)
    for item in config.show():
        line = f"{item.name:<{width}}  {item.value}"
        if detail:
            line += f"    [{item.source}]"
        typer.echo(line)

    aliases = get_registered_url_aliases()
    if aliases:
        origins = get_url_alias_origins()
        typer.echo("\naliases")
        for token, path in sorted(aliases.items()):
            suffix = f"    [{origins.get(token, '')}]" if detail else ""
            typer.echo(f"  <{token}>  {path}{suffix}")


@config_app.command("path")
def config_path(
    all_files: bool = typer.Option(False, "--all", help="List every loaded config file."),
) -> None:
    """Print the config file path, friendly for scripting."""
    from granum.core.config import user_config_url

    config = _config()
    files = config.loaded_files()
    if all_files:
        if not files:
            typer.echo("(no config files loaded)")
            return
        for tier, url in files:
            typer.echo(f"{Tier(tier).name.lower():<8} {url}")
        return
    for tier, url in files:
        if tier is Tier.USER:
            typer.echo(str(url))
            return
    typer.echo(str(user_config_url()))


@config_app.command("validate")
def config_validate() -> None:
    """Check the current configuration and report any problems."""
    problems = _config().validate()
    if not problems:
        typer.echo("configuration is valid")
        return
    for problem in problems:
        typer.echo(f"error: {problem}", err=True)
    raise typer.Exit(1)


@config_app.command("project-root")
def config_project_root(
    path: str | None = typer.Argument(None, help="Set the project root to this location."),
) -> None:
    """Get or set the project root."""
    config = _config()
    if path is None:
        typer.echo(str(config.project_root))
        return
    from granum.core.config import CONFIG_FILENAME, user_config_url

    target = user_config_url()
    existing = ""
    if target.exists():
        existing = target.read_text()
    lines = [line for line in existing.splitlines() if not line.startswith("project-root-url:")]
    lines.append(f"project-root-url: {Url(path)}")
    target.write_text("\n".join(lines) + "\n")
    typer.echo(f"project-root-url set to {Url(path)} in {target} ({CONFIG_FILENAME})")


def _service_licensing(index: Index, server_url: str) -> Licensing:
    """This computer's licence, beating in the background while the service runs.

    The newest object in the projects is a clock mark: a clock behind it was turned back.

    Licensing is switched off in this build (``granum.licensing.manager.ENFORCED``), so what
    this returns is unrestricted: nothing here starts, writes or asks the server anything, and
    the service never announces itself as read-only.
    """
    from granum.licensing import Licensing, set_licensing
    from granum.licensing.token import parse_time

    def latest_seen() -> float | None:
        times = [parse_time(e.created) for e in index.entries() if getattr(e, "created", None)]
        return max((t for t in times if t), default=None)

    server = None
    if server_url:
        from granum.licensing.client import LicenceServer

        server = LicenceServer(server_url)
    licensing = Licensing(latest_seen=latest_seen, server=server)
    set_licensing(licensing)
    licensing.start()
    status = licensing.status()
    if status["mode"] != "full":
        typer.echo(f"granum: read-only. {status['reason']}", err=True)
    return licensing


if __name__ == "__main__":
    app()
