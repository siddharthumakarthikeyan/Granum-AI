"""``granum`` -- the command line interface.

Every command accepts the same global options, and every option is also readable from an
environment variable. ``granum config show --detail`` reports where each value came
from, which is the fastest way to debug an install inside someone else's infrastructure.
"""

from __future__ import annotations

import typer

from granum.core.config import OPTIONS, Config, Tier, set_config
from granum.core.url import Url, get_registered_url_aliases, get_url_alias_origins

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


@app.command()
def service(
    host: str = typer.Option("127.0.0.1", "--host", help="Address to bind to."),
    port: int = typer.Option(8000, "--port", help="Port to bind to."),
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
) -> None:
    """Start the Object Service and the dashboard.

    It reads your data locally and serves it to the dashboard. Nothing is uploaded.
    """
    import uvicorn

    from granum.core.index import Index, set_index
    from granum.service.app import create_app
    from granum.service.cache import ByteCache

    config = _config()
    index = Index(config=config)
    typer.echo(f"granum: indexing {config.project_root} ...")
    index.refresh()
    typer.echo(f"granum: {len(index.entries())} objects found")
    if watch:
        index.start(reindex_interval)
    set_index(index)

    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if not loopback:
        typer.echo(
            f"granum: WARNING binding to {host} exposes your data to the network. The service has no "
            "authentication yet: anyone who can reach this port can read and change projects.",
            err=True,
        )
    hosts = list(allow_host) + ([] if loopback or host in {"0.0.0.0", "::"} else [host])
    application = create_app(
        index=index,
        config=config,
        cache=ByteCache(max_bytes=cache_size, ttl_seconds=cache_timeout),
        allowed_hosts=hosts,
        allowed_origins=list(allow_origin) or None,
        data_roots=list(data_root) or None,
    )
    shown = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    address = f"http://{shown}:{port}"
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
        uvicorn.run(application, host=host, port=port, log_level="warning")
    finally:
        index.stop()


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


if __name__ == "__main__":
    app()
