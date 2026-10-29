"""Admin-managed compute plugins. Catalogue trust is configured on the service host."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from granum.compute import PluginError, PluginManager
from granum.service.auth import principal


class PluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")


class InstallRequest(PluginRequest):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class ComputeRequest(PluginRequest):
    table: str
    inputs: dict[str, str] = Field(max_length=20)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=30)
    prefix: str = Field("computed", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")


def register_compute(app: Any, *, table_at: Any, jobs: Any, index: Any, config: Any) -> None:
    manager = PluginManager(str(config.project_root))
    app.state.compute = manager

    @app.get("/api/compute")
    def catalogue(refresh: bool = False) -> dict[str, Any]:
        actor = principal.get()
        return {**manager.catalogue(refresh=refresh), "installed": manager.list_installed(),
                "can_manage": actor is None or actor.role == "admin"}

    @app.get("/api/compute/jobs")
    def history() -> list[dict[str, Any]]:
        return [job.to_dict() for job in sorted(jobs.all(), key=lambda j: j.started, reverse=True) if job.kind.startswith("compute-")]

    @app.post("/api/compute/install")
    def install(request: InstallRequest) -> dict[str, Any]:
        try:
            manager.available(request.plugin, request.revision)
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jobs.start("compute-install", lambda job: manager.install(request.plugin, request.revision, job), durable=True).to_dict()

    @app.post("/api/compute/uninstall")
    def uninstall(request: PluginRequest) -> dict[str, Any]:
        try:
            manager.installed(request.plugin)
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jobs.start("compute-uninstall", lambda job: manager.uninstall(request.plugin, job), durable=True).to_dict()

    @app.post("/api/compute/check")
    def check(request: PluginRequest) -> dict[str, Any]:
        try:
            manager.installed(request.plugin)
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jobs.start("compute-check", lambda job: manager.check(request.plugin, job), durable=True).to_dict()

    @app.post("/api/compute/run")
    def run(request: ComputeRequest) -> dict[str, Any]:
        source = table_at(request.table)
        try:
            manager.preflight(request.plugin, source, request.inputs, request.parameters, request.prefix)
        except PluginError as exc:
            raise HTTPException(400, str(exc)) from exc

        def work(job: Any) -> Any:
            result = manager.run(request.plugin, source, request.inputs, request.parameters, request.prefix, job)
            index.refresh(force=True)
            return result

        return jobs.start("compute-run", work, durable=True).to_dict()
