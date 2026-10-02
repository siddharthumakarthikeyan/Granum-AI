"""HTTP API of the licence server. Public endpoints serve the app and the download form;
``/v1/admin/*`` serve the website's own backend (payments, account page) and need the
admin token."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .service import LicenceService, Refused


class EmailRequest(BaseModel):
    email: str = Field(max_length=254)
    source: str = Field("website", max_length=40)


class DownloadRequest(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field("", max_length=12)
    os: str = Field("", max_length=20)
    name: str = Field("", max_length=120)
    company: str = Field("", max_length=120)


class QuoteRequest(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field("", max_length=120)
    company: str = Field("", max_length=160)
    plan: str = Field("Enterprise", max_length=40)
    computers: int | None = Field(None, ge=1, le=100_000)
    message: str = Field("", max_length=4000)
    #: Hidden on the page; people leave it empty, form-filling bots do not.
    website: str = Field("", max_length=200)


class ActivateRequest(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=12)
    machine: str = Field(max_length=40)
    app_version: str = Field("", max_length=40)


class KeyRequest(BaseModel):
    key: str = Field(max_length=20_000)
    app_version: str = Field("", max_length=40)


class GrantRequest(BaseModel):
    email: str
    plan: str = Field(max_length=80)
    days: float | None = None
    machines: int = Field(1, ge=1, le=1000)
    max_projects: int | None = Field(None, ge=1)
    customer: str | None = None
    note: str = ""


class ExtendRequest(BaseModel):
    lid: str
    days: float = Field(gt=0)


class LidRequest(BaseModel):
    lid: str
    machine: str | None = None


def create_app(service: LicenceService, *, admin_token: str = "", site: dict[str, Any] | None = None) -> FastAPI:
    """``site`` is what the web pages read: download links, version, contact address."""
    app = FastAPI(title="Granum licence server", docs_url=None, redoc_url=None, openapi_url=None)
    site = site or {}

    def publication() -> dict[str, Any]:
        import re
        from urllib.parse import urlsplit

        def https(value: str) -> bool:
            try:
                url = urlsplit(value)
                return url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
            except ValueError:
                return False

        release = site.get("release") or {}
        checksums = site.get("checksums") or {}
        manifests = site.get("manifests") or {}
        ready = (release.get("qualified") is True and release.get("channel") == "unrestricted-alpha"
                 and bool(re.fullmatch(r"[0-9a-f]{40,64}", release.get("source_revision", "")))
                 and bool(site.get("version")))
        downloads = {name: url for name, url in (site.get("downloads") or {}).items()
                     if ready and name in ("windows", "linux") and https(url)
                     and re.fullmatch(r"[0-9a-fA-F]{64}", checksums.get(name, "")) and https(manifests.get(name, ""))}
        return {"version": site.get("version"), "downloads": downloads,
                "release": {"channel": "unrestricted-alpha", "source_revision": release.get("source_revision"), "qualified": bool(downloads)},
                "checksums": {name: checksums[name] for name in downloads},
                "manifests": {name: manifests[name] for name in downloads}}

    @app.exception_handler(Refused)
    async def refused(_request: Request, exc: Refused) -> JSONResponse:
        return JSONResponse({"detail": exc.message, "code": exc.code}, exc.status)

    def admin(authorization: str | None) -> None:
        expected = f"Bearer {admin_token}"
        if not admin_token or not hmac.compare_digest(authorization or "", expected):
            raise Refused(401, "admin token required", "auth")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/v1/site")
    def site_config() -> dict[str, Any]:
        """What the pages show: the version, whether downloads are up, how to get in touch."""
        published = publication()
        return {"version": published["version"], "contact": site.get("contact"), "release": published["release"],
            "downloads": {name: name in published["downloads"] for name in ("windows", "linux")}}

    @app.post("/v1/download/code")
    def download_code(request: EmailRequest = Body(...)) -> dict[str, Any]:
        """The download form, step one: email a code to prove the address is real."""
        return service.send_code(request.email, "download")

    @app.post("/v1/download")
    def download(request: DownloadRequest = Body(...)) -> dict[str, Any]:
        """Step two: with the right code, record the email and give the installer links."""
        service.download(request.email, request.code, request.os, name=request.name, company=request.company)
        return publication()

    @app.post("/v1/quote")
    def quote(request: QuoteRequest = Body(...)) -> dict[str, Any]:
        """The website's buy / request-a-quote form: stored, and emailed to the contact address."""
        if request.website:
            return {"ok": True}
        return service.quote(request.email, name=request.name, company=request.company, computers=request.computers,
                             message=request.message, plan=request.plan, notify=site.get("contact") or "")

    @app.post("/v1/register")
    def register(request: EmailRequest = Body(...)) -> dict[str, Any]:
        """The download form: remember who downloaded."""
        service.register(request.email, request.source)
        return {"ok": True}

    @app.post("/v1/login/code")
    def login_code(request: EmailRequest = Body(...)) -> dict[str, Any]:
        return service.send_code(request.email)

    @app.post("/v1/activate")
    def activate(request: ActivateRequest = Body(...)) -> dict[str, Any]:
        return service.activate(request.email, request.code, request.machine, request.app_version)

    @app.post("/v1/refresh")
    def refresh(request: KeyRequest = Body(...)) -> dict[str, Any]:
        return service.refresh(request.key, request.app_version)

    @app.post("/v1/deactivate")
    def deactivate(request: KeyRequest = Body(...)) -> dict[str, Any]:
        return service.deactivate(request.key)

    # -- the website's backend -------------------------------------------------------

    @app.post("/v1/admin/grant")
    def grant(request: GrantRequest = Body(...), authorization: str | None = Header(None)) -> dict[str, Any]:
        admin(authorization)
        return service.grant(request.email, plan=request.plan, days=request.days, machines=request.machines,
                             max_projects=request.max_projects, customer=request.customer, note=request.note)

    @app.post("/v1/admin/extend")
    def extend(request: ExtendRequest = Body(...), authorization: str | None = Header(None)) -> dict[str, Any]:
        admin(authorization)
        service.extend(request.lid, request.days)
        return {"ok": True}

    @app.post("/v1/admin/revoke")
    def revoke(request: LidRequest = Body(...), authorization: str | None = Header(None)) -> dict[str, Any]:
        admin(authorization)
        service.revoke(request.lid)
        return {"ok": True}

    @app.post("/v1/admin/free-machine")
    def free_machine(request: LidRequest = Body(...), authorization: str | None = Header(None)) -> dict[str, Any]:
        admin(authorization)
        service.free_machine(request.lid, request.machine or "")
        return {"ok": True}

    @app.get("/v1/admin/account")
    def account(email: str = Query(...), authorization: str | None = Header(None)) -> dict[str, Any]:
        admin(authorization)
        return service.account(email)

    return app
