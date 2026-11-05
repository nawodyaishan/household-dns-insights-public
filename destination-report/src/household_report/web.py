"""Thin authenticated web boundary: local owner session, read models and commands.

The web layer is deliberately small and boring. It renders stored read models,
verifies request provenance and forwards explicit owner commands. It contains no SQL,
no provider/MCP client, no credential handling and no domain policy:

* reports and inventory arrive as read-model objects from the feature modules;
* analyses start only after an explicit confirmation form whose preview token is
  recomputed and compared locally;
* the only outbound-work entry point is the injected ``runner`` and it is called
  solely from a confirmed POST, never from a page load, refresh, filter or poll.

Loading or refreshing a page performs zero external calls. There are no remote
assets, fonts or scripts: every resource is served from ``/static``.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from starlette.staticfiles import StaticFiles

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

SESSION_COOKIE = "hr_session"
CSRF_FIELD = "csrf"
PUBLIC_PATHS = frozenset({"/login", "/healthz", "/favicon.ico"})
PRESETS = {"24h", "48h", "snapshot", "custom"}
RESUMABLE_STATES = frozenset({"partial", "paused", "queued"})
TERMINAL_STATES = frozenset({"completed", "partial", "failed", "cancelled"})

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; "
        "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Same-origin (not no-referrer): Chrome degrades form ORIGIN to "null" under
    # no-referrer, which would defeat the Origin check below.
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cache-Control": "no-store",
}


class AuthError(RuntimeError):
    """The local owner session or password record is not usable."""


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# -- password record and sessions -------------------------------------------

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str) -> str:
    """Create one owner password record with stdlib scrypt and a random salt."""
    if len(password) < 12:
        raise AuthError("Password must be at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, record: str) -> bool:
    """Constant-time verification of a stored scrypt record."""
    try:
        scheme, n, r, p, salt, expected = record.strip().split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, _unb64(expected))


@dataclass(frozen=True, slots=True)
class Session:
    sid: str
    expires_epoch: int


class OwnerAuth:
    """Stateless signed session plus CSRF derivation; no server-side session table."""

    def __init__(
        self,
        *,
        password_record: str,
        session_key: bytes,
        session_seconds: int = 12 * 3600,
        max_failures: int = 5,
        failure_window_seconds: int = 300,
        failure_delay_seconds: float = 0.4,
    ) -> None:
        if len(session_key) < 32:
            raise AuthError("Session key must be at least 32 bytes")
        if not password_record.startswith("scrypt$"):
            raise AuthError("Password record is not a scrypt record")
        self._record = password_record.strip()
        self._key = session_key
        self._session_seconds = session_seconds
        self._max_failures = max_failures
        self._failure_window = failure_window_seconds
        self._failure_delay = failure_delay_seconds
        self._failures: list[float] = []
        self._lock = threading.Lock()

    def _blocked(self, now: float) -> bool:
        cutoff = now - self._failure_window
        self._failures = [moment for moment in self._failures if moment > cutoff]
        return len(self._failures) >= self._max_failures

    def attempt(self, password: str, *, now: float | None = None) -> str:
        """Return ``ok``, ``bad`` or ``throttled``; no password ever leaves memory."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            if self._blocked(moment):
                return "throttled"
            if verify_password(password, self._record):
                self._failures.clear()
                return "ok"
            self._failures.append(moment)
        if self._failure_delay:
            time.sleep(self._failure_delay)
        return "bad"

    def issue_session(self, *, now: datetime | None = None) -> tuple[str, Session]:
        moment = now or datetime.now(UTC)
        session = Session(
            sid=secrets.token_urlsafe(18),
            expires_epoch=int(moment.timestamp()) + self._session_seconds,
        )
        payload = _b64(
            json.dumps(
                {"sid": session.sid, "exp": session.expires_epoch},
                separators=(",", ":"),
            ).encode()
        )
        signature = _b64(
            hmac.new(self._key, b"session." + payload.encode(), hashlib.sha256).digest()
        )
        return f"v1.{payload}.{signature}", session

    def read_session(self, token: str | None, *, now: datetime | None = None) -> Session | None:
        if not token or not token.startswith("v1."):
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        _, payload, signature = parts
        expected = hmac.new(self._key, b"session." + payload.encode(), hashlib.sha256).digest()
        try:
            if not hmac.compare_digest(_unb64(signature), expected):
                return None
            data = json.loads(_unb64(payload))
            session = Session(sid=str(data["sid"]), expires_epoch=int(data["exp"]))
        except (ValueError, KeyError, TypeError):
            return None
        moment = (now or datetime.now(UTC)).timestamp()
        if session.expires_epoch <= moment:
            return None
        return session

    def csrf_token(self, session: Session) -> str:
        return _b64(hmac.new(self._key, b"csrf." + session.sid.encode(), hashlib.sha256).digest())

    def check_csrf(self, session: Session, submitted: str) -> bool:
        return hmac.compare_digest(self.csrf_token(session), submitted or "")

    def issue_view_token(self, campaign_id: str, *, now_epoch: int) -> str:
        payload = _b64(
            json.dumps(
                {"campaign": campaign_id, "exp": now_epoch + 600}, separators=(",", ":")
            ).encode()
        )
        signature = _b64(
            hmac.new(self._key, b"viewer." + payload.encode(), hashlib.sha256).digest()
        )
        return f"v1.{payload}.{signature}"

    def check_view_token(self, token: str, campaign_id: str, *, now_epoch: int) -> bool:
        try:
            version, payload, signature = token.split(".")
            expected = hmac.new(self._key, b"viewer." + payload.encode(), hashlib.sha256).digest()
            body = json.loads(_unb64(payload))
            return bool(
                version == "v1"
                and hmac.compare_digest(_unb64(signature), expected)
                and body["campaign"] == campaign_id
                and now_epoch < int(body["exp"]) <= now_epoch + 600
            )
        except (ValueError, TypeError, KeyError, UnicodeError):
            return False


# -- configuration and read-model ports -------------------------------------


@dataclass(frozen=True, slots=True)
class WebConfig:
    allowed_hosts: tuple[str, ...]
    public_url: str
    session_seconds: int = 12 * 3600
    max_body_bytes: int = 65_536
    failure_delay_seconds: float = 0.4
    shared_control: bool = False


class ReportReads(Protocol):
    def snapshots(self) -> list[dict[str, object]]: ...

    def report(
        self,
        *,
        preset: str = "24h",
        snapshot_id: str | None = None,
        start_local: str | None = None,
        end_local: str | None = None,
        attributions: Mapping[object, str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, object] | None: ...

    def gaming_projection(self, *, snapshot_id: str | None = None) -> dict[str, object] | None: ...

    def usage_summary(
        self, *, dispatch_day: str | None, analysis_id: str | None = None
    ) -> dict[str, object]: ...

    def gaming_export(
        self, *, snapshot_id: str, basis: str, group: str, role: str
    ) -> dict[str, object]: ...


class InventoryReads(Protocol):
    def devices(self) -> dict[str, object]: ...

    def edit_device(
        self, device_key: str, *, display_name: str | None, category: str | None
    ) -> dict[str, object]: ...


class AnalysisCommands(Protocol):
    def preview(self, **kwargs: object) -> object: ...

    def start(self, **kwargs: object) -> tuple[str, bool]: ...

    def reanalyze(self, analysis_id: str, *, nonce: str) -> str: ...

    def status(self, analysis_id: str) -> dict[str, object]: ...

    def research_coverage(self, domain_rows: Mapping[str, int], **kwargs: object) -> object: ...

    def first_time_page(self, coverage: Mapping[str, object], **kwargs: object) -> object: ...

    def coverage_summary(self, coverage: Mapping[str, object]) -> object: ...

    def history(self, *, limit: int = 10) -> list[dict[str, object]]: ...

    def limits(self) -> dict[str, int]: ...

    def live_run_manifest_template(self) -> dict[str, object]: ...


class CampaignReads(Protocol):
    def list_status(self) -> list[dict[str, object]]: ...

    def start(self, *, days: int, retention_days: int) -> dict[str, object]: ...

    def extend(self, hours: int, campaign_id: str | None = None) -> dict[str, object]: ...

    def finish_early(self, campaign_id: str | None = None) -> dict[str, object]: ...


class CampaignReportReads(Protocol):
    store: object

    def request(
        self, campaign_id: str, *, day: str | None = None, hours: int | None = None
    ) -> str: ...

    def job_status(self, job_id: str) -> dict[str, object]: ...

    def get(self, report_id: str) -> dict[str, object]: ...

    def export_json(
        self, report_id: str, *, basis: str = "all", group: str = "", role: str = ""
    ) -> dict[str, object]: ...

    def export_csv(
        self, report_id: str, *, basis: str = "all", group: str = "", role: str = ""
    ) -> str: ...

    def review_association(
        self,
        campaign_id: str,
        *,
        hostname: str,
        group_id: str,
        group_label: str,
        group_kind: str,
        review_note: str,
        author: str = "owner",
    ) -> dict[str, object]: ...


AI = Mapping[str, object]

#: A confirmed POST hands work to the composition root; it returns immediately.
JobRunner = Callable[[str, bool], None]


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _jsonable(value: object) -> object:
    return json.loads(json.dumps(value, default=str))


def create_app(
    *,
    auth: OwnerAuth,
    config: WebConfig,
    reports: ReportReads,
    inventory: InventoryReads,
    analysis: AnalysisCommands,
    runner: JobRunner,
    ai: AI,
    campaigns: CampaignReads | None = None,
    campaign_reports: CampaignReportReads | None = None,
    collector: Callable[[], dict[str, object]] | None = None,
    timezone: str = "UTC",
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Assemble the local application; wiring stays in ``app``."""
    zone = ZoneInfo(timezone)
    moment = clock or (lambda: datetime.now(UTC))
    allowed_hosts = tuple(host.lower() for host in config.allowed_hosts)
    public_origin = config.public_url.rstrip("/")
    allowed_origins = {public_origin} | {
        f"{public_origin.split('://', 1)[0]}://{host}" for host in allowed_hosts
    }
    viewer_hits: dict[str, list[float]] = {}
    global_hits: list[float] = []
    viewer_lock = threading.Lock()

    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(("html", "xml")),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def local_time(value: object, fmt: str = "%Y-%m-%d %H:%M") -> str:
        if not value:
            return "not recorded"
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), tz=UTC)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            parsed = parsed.astimezone(UTC) if parsed.tzinfo is None else parsed
        return parsed.astimezone(zone).strftime(fmt)

    def utc_time(value: object) -> str:
        if not value:
            return "not recorded"
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), tz=UTC)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            parsed = parsed.astimezone(UTC) if parsed.tzinfo is None else parsed
        return parsed.strftime("%Y-%m-%d %H:%M:%SZ")

    def thousands(value: object) -> str:
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)

    environment.filters["local_time"] = local_time
    environment.filters["utc_time"] = utc_time
    environment.filters["thousands"] = thousands

    def render(
        request: Request, name: str, *, status_code: int = 200, **context: object
    ) -> HTMLResponse:
        session: Session | None = getattr(request.state, "session", None)
        base = {
            "page": context.pop("page", ""),
            "csrf": auth.csrf_token(session) if session and not config.shared_control else "",
            "shared_control": config.shared_control,
            "ai": ai,
            "timezone": timezone,
            "snapshot_count": len(reports.snapshots()),
            "generated_utc": utc_time(moment()),
            "collector": collector() if collector else None,
        }
        base.update(context)
        template = environment.get_template(name)
        response = HTMLResponse(template.render(**base), status_code=status_code)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    app = FastAPI(
        title="Household destination report",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        def finalise(response: Response) -> Response:
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)
            return response

        host = (request.headers.get("host") or "").lower()
        if host not in allowed_hosts:
            return finalise(PlainTextResponse("Unrecognised Host header", status_code=400))
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") not in allowed_origins:
            return finalise(PlainTextResponse("Cross-origin request refused", status_code=403))
        fetched_site = request.headers.get("sec-fetch-site")
        if fetched_site not in {None, "same-origin", "none"}:
            return finalise(PlainTextResponse("Cross-site request refused", status_code=403))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if config.shared_control and origin != public_origin:
                return finalise(PlainTextResponse("Same-origin action required", status_code=403))
            declared = request.headers.get("content-length")
            if declared is None:
                return finalise(
                    PlainTextResponse("A sized request body is required", status_code=411)
                )
            try:
                length = int(declared)
            except ValueError:
                return finalise(PlainTextResponse("Invalid Content-Length", status_code=400))
            if length > config.max_body_bytes:
                return finalise(PlainTextResponse("Request body too large", status_code=413))
        path = request.url.path
        if config.shared_control:
            if path in {"/login", "/logout"}:
                return finalise(PlainTextResponse("Not found", status_code=404))
            request.state.session = None
            return finalise(await call_next(request))
        session = auth.read_session(request.cookies.get(SESSION_COOKIE), now=moment())
        request.state.session = session
        if (
            path in PUBLIC_PATHS
            or path.startswith("/static/")
            or (
                (path == "/household" or path.startswith("/household/"))
                and not path.startswith("/household/owner")
            )
        ):
            return finalise(await call_next(request))
        if session is None:
            if request.method == "GET":
                return finalise(RedirectResponse(f"/login?next={quote(path)}", status_code=303))
            return finalise(PlainTextResponse("Sign in required", status_code=403))
        return finalise(await call_next(request))

    def session_of(request: Request) -> Session:
        session = getattr(request.state, "session", None)
        if session is None:  # pragma: no cover - the guard already refuses
            raise HTTPException(status_code=403, detail="Sign in required")
        return session

    def require_csrf(request: Request, submitted: str) -> None:
        if config.shared_control:
            return  # The shared profile requires exact Origin on every mutation in middleware.
        if not auth.check_csrf(session_of(request), submitted):
            raise HTTPException(status_code=403, detail="Confirmation token is invalid")

    def cookie_secure(request: Request) -> bool:
        if config.public_url.startswith("https://"):
            return True
        return request.url.scheme == "https"

    # -- authentication ----------------------------------------------------
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/") -> Response:
        if auth.read_session(request.cookies.get(SESSION_COOKIE), now=moment()) is not None:
            return RedirectResponse(_safe_next(next), status_code=303)
        return render(request, "login.html", page="login", next_path=_safe_next(next), error=None)

    @app.post("/login")
    async def login(request: Request) -> Response:
        form = await request.form()
        next_path = _safe_next(str(form.get("next") or "/"))
        outcome = auth.attempt(str(form.get("password") or ""))
        if outcome != "ok":
            status = 429 if outcome == "throttled" else 401
            return render(
                request,
                "login.html",
                status_code=status,
                page="login",
                next_path=next_path,
                error=(
                    "Too many attempts; wait a few minutes."
                    if outcome == "throttled"
                    else "That password did not match."
                ),
            )
        token, _session = auth.issue_session(now=moment())
        response = RedirectResponse(next_path, status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=config.session_seconds,
            httponly=True,
            samesite="strict",
            secure=cookie_secure(request),
            path="/",
        )
        return response

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/household", response_class=HTMLResponse)
    def household_landing(request: Request) -> Response:
        campaign = visible_campaign()
        return render(
            request,
            "household.html",
            page="household",
            campaign=campaign,
            token=auth.issue_view_token(
                str(campaign["campaign_id"]), now_epoch=int(moment().timestamp())
            )
            if campaign
            else "",
        )

    def visible_campaign(campaign_id: str | None = None) -> dict[str, object] | None:
        if campaigns is None or campaign_reports is None:
            return None
        now = int(moment().timestamp())
        for campaign in campaigns.list_status():
            if campaign_id is not None and campaign["campaign_id"] != campaign_id:
                continue
            end = int(campaign["utc_bounds"][1])
            if now < end + int(campaign["retention_days"]) * 86400:
                return campaign
        return None

    def visible_job(job_id: str) -> dict[str, object]:
        if campaign_reports is None:
            raise HTTPException(status_code=404, detail="Report unavailable")
        try:
            status = campaign_reports.job_status(job_id)
        except (ValueError, KeyError, RuntimeError):
            raise HTTPException(status_code=404, detail="Report unavailable") from None
        if visible_campaign(str(status["campaign_id"])) is None:
            raise HTTPException(status_code=404, detail="Report unavailable")
        return status

    @app.post("/household/generate", status_code=202)
    async def household_generate(request: Request) -> Response:
        campaign = visible_campaign()
        if campaign is None or campaign_reports is None:
            raise HTTPException(status_code=404, detail="Campaign unavailable")
        if request.headers.get("origin", "").rstrip("/") != public_origin:
            raise HTTPException(status_code=403, detail="Same-origin request required")
        form = await request.form()
        if set(form) - {"view_token", "day", "hours"}:
            raise HTTPException(status_code=400, detail="Unsupported report input")
        day = str(form.get("day") or "")
        if len(day) > 10:
            raise HTTPException(status_code=400, detail="Invalid day")
        hours_raw = str(form.get("hours") or "")
        hours: int | None
        if not hours_raw:
            hours = None
        elif hours_raw in {"24", "48"}:
            hours = int(hours_raw)
        else:
            raise HTTPException(status_code=400, detail="Unsupported period")
        if not auth.check_view_token(
            str(form.get("view_token") or ""),
            str(campaign["campaign_id"]),
            now_epoch=int(moment().timestamp()),
        ):
            raise HTTPException(status_code=403, detail="Invalid request token")
        now = time.monotonic()
        viewer = request.client.host if request.client else "unknown"
        with viewer_lock:
            if len(viewer_hits) > 256:
                viewer_hits.clear()  # Global limiter remains; bound memory under spoofed clients.
            recent = [tick for tick in viewer_hits.get(viewer, ()) if tick > now - 60]
            global_hits[:] = [tick for tick in global_hits if tick > now - 60]
            if len(recent) >= 10 or len(global_hits) >= 60:
                raise HTTPException(
                    status_code=429, detail="Retry after 60 seconds", headers={"Retry-After": "60"}
                )
            recent.append(now)
            viewer_hits[viewer] = recent
            global_hits.append(now)
        try:
            job_id = campaign_reports.request(
                str(campaign["campaign_id"]), day=day or None, hours=hours
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Day or period is not available") from None
        except RuntimeError:
            raise HTTPException(
                status_code=429, detail="Report queue is full", headers={"Retry-After": "60"}
            ) from None
        return JSONResponse(
            {"job_id": job_id, "state": visible_job(job_id)["state"]}, status_code=202
        )

    @app.get("/household/jobs/{job_id}")
    def household_job(job_id: str) -> dict[str, object]:
        return visible_job(job_id)

    def visible_report(report_id: str) -> dict[str, object]:
        if campaign_reports is None:
            raise HTTPException(status_code=404, detail="Report unavailable")
        try:
            payload = campaign_reports.get(report_id)
        except (ValueError, KeyError, RuntimeError):
            raise HTTPException(status_code=404, detail="Report unavailable") from None
        if visible_campaign(str(payload["campaign_id"])) is None:
            raise HTTPException(status_code=404, detail="Report unavailable")
        return payload

    @app.get("/household/reports/{report_id}", response_class=HTMLResponse)
    def household_report(
        request: Request, report_id: str, basis: str = "all", group: str = "", role: str = ""
    ) -> Response:
        payload = visible_report(report_id)
        if basis not in {"all", "known_list", "model"} or len(group) > 64 or len(role) > 64:
            raise HTTPException(status_code=400, detail="Unknown filter")
        entries = [
            item
            for item in payload["entries"]
            if (
                basis == "all"
                or (basis == "known_list" and item["known_list_match"])
                or (basis == "model" and item["model_proposal"])
            )
            and (not group or item["group"]["group_id"] == group)
            and (not role or (item.get("analysis") or {}).get("role", "unknown") == role)
        ]
        return render(
            request,
            "household_report.html",
            page="household",
            projection=payload,
            entries=entries,
            report_id=report_id,
            basis=basis,
            group=group,
            role=role,
        )

    @app.get("/household/reports/{report_id}/export.{format}")
    def household_export(
        report_id: str, format: str, basis: str = "all", group: str = "", role: str = ""
    ) -> Response:
        visible_report(report_id)
        if campaign_reports is None or format not in {"csv", "json"}:
            raise HTTPException(status_code=404, detail="Export unavailable")
        if basis not in {"all", "known_list", "model"} or len(group) > 64 or len(role) > 64:
            raise HTTPException(status_code=400, detail="Unknown filter")
        if format == "json":
            response = JSONResponse(
                campaign_reports.export_json(report_id, basis=basis, group=group, role=role)
            )
        else:
            response = Response(
                campaign_reports.export_csv(report_id, basis=basis, group=group, role=role),
                media_type="text/csv; charset=utf-8",
            )
        response.headers["Content-Disposition"] = (
            f'attachment; filename="household-report.{format}"'
        )
        return response

    @app.get("/household/owner", response_class=HTMLResponse)
    def household_owner(request: Request) -> Response:
        return render(
            request,
            "household_owner.html",
            page="household",
            campaigns=campaigns.list_status() if campaigns else [],
        )

    @app.post("/household/owner/review")
    async def household_owner_review(request: Request) -> Response:
        # Rule promotion is an owner research privilege; shared LAN controls cannot
        # promote model proposals into the reviewed gaming rule set.
        if config.shared_control:
            raise HTTPException(
                status_code=403, detail="Owner review is unavailable on shared control"
            )
        if campaign_reports is None:
            raise HTTPException(status_code=404, detail="Owner review unavailable")
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        campaign_id = str(form.get("campaign_id") or "")
        hostname = str(form.get("hostname") or "")
        try:
            rule = campaign_reports.review_association(
                campaign_id,
                hostname=hostname,
                group_id=str(form.get("group_id") or ""),
                group_label=str(form.get("group_label") or ""),
                group_kind=str(form.get("group_kind") or ""),
                review_note=str(form.get("review_note") or ""),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        return JSONResponse({"rule_id": rule["rule_id"], "namespace": rule["namespace"]})

    @app.post("/household/owner/{action}")
    async def household_owner_action(request: Request, action: str) -> Response:
        if campaigns is None or action not in {"start", "extend", "finish"}:
            raise HTTPException(status_code=404, detail="Owner action unavailable")
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        try:
            if action == "start":
                result = campaigns.start(
                    days=int(str(form.get("days") or "3")),
                    retention_days=int(str(form.get("retention_days") or "7")),
                )
            elif action == "extend":
                result = campaigns.extend(int(str(form.get("hours") or "0")))
            else:
                result = campaigns.finish_early()
        except (ValueError, RuntimeError):
            raise HTTPException(status_code=400, detail="Campaign action unavailable") from None
        return JSONResponse({"campaign_id": result["campaign_id"], "state": result["state"]})

    # -- reports -----------------------------------------------------------
    def build_report(
        request: Request,
        *,
        preset: str,
        snapshot: str,
        start: str,
        end: str,
        household_only: bool = False,
    ) -> tuple[dict[str, object] | None, str | None]:
        try:
            args: dict[str, object] = {
                "preset": preset,
                "snapshot_id": snapshot or None,
                "start_local": start or None,
                "end_local": end or None,
                "now": moment(),
            }
            if household_only:
                args["attributions"] = {}
            return reports.report(**args), None
        except ValueError as error:
            return None, str(error)

    def filter_entries(
        report: Mapping[str, object],
        *,
        query: str,
        category: str,
        service_only: bool,
    ) -> dict[str, object]:
        needle = query.strip().lower()
        selected = []
        for entry in report["destinations"]:
            classification = entry["classification"]
            if needle and needle not in str(entry["domain"]).lower():
                continue
            if category and classification.get("category") != category:
                continue
            if service_only and not classification.get("likely_service"):
                continue
            selected.append(entry)
        return {
            "destinations": selected,
            "query": query.strip(),
            "category": category,
            "service_only": service_only,
            "matched_domains": len(selected),
            "matched_rows": sum(int(entry["query_count"]) for entry in selected),
            "total_domains": len(report["destinations"]),
            "total_rows": int(report["summary"]["destination_rows"]),
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        preset: str = "24h",
        snapshot: str = "",
        start: str = "",
        end: str = "",
        q: str = "",
        category: str = "",
        service_only: bool = False,
        limit: int = 200,
    ) -> Response:
        if preset not in PRESETS:
            preset = "24h"
        limit = max(10, min(limit, 1000))
        report, error = build_report(
            request, preset=preset, snapshot=snapshot, start=start, end=end
        )
        if report is None:
            return render(
                request,
                "report.html",
                page="report",
                report=None,
                view=None,
                sections=None,
                snapshots=reports.snapshots(),
                preset=preset,
                snapshot=snapshot,
                start=start,
                end=end,
                q=q,
                category=category,
                service_only=service_only,
                limit=limit,
                categories=[],
                error=error,
            )
        view = filter_entries(report, query=q, category=category, service_only=service_only)
        sections = {"service": [], "provider": [], "unresolved": []}
        for entry in view["destinations"]:
            classification = entry["classification"]
            if classification.get("likely_service"):
                sections["service"].append(entry)
            elif classification.get("provider"):
                sections["provider"].append(entry)
            else:
                sections["unresolved"].append(entry)
        categories = sorted(
            {
                str(entry["classification"].get("category") or "unknown")
                for entry in report["destinations"]
            }
        )
        return render(
            request,
            "report.html",
            page="report",
            report=report,
            view=view,
            sections=sections,
            snapshots=reports.snapshots(),
            preset=preset,
            snapshot=snapshot,
            start=start,
            end=end,
            q=q,
            category=category,
            service_only=service_only,
            limit=limit,
            categories=categories,
            error=error,
        )

    @app.get("/diagnostics/report.json")
    def download_report(
        request: Request,
        preset: str = "24h",
        snapshot: str = "",
        start: str = "",
        end: str = "",
    ) -> Response:
        report, error = build_report(
            request, preset=preset, snapshot=snapshot, start=start, end=end
        )
        if report is None:
            raise HTTPException(status_code=404, detail=error or "No observations")
        response = JSONResponse(_jsonable(report))
        response.headers["Content-Disposition"] = 'attachment; filename="report.json"'
        return response

    # -- gaming projection -------------------------------------------------
    def gaming_context(
        request: Request,
        *,
        snapshot: str = "",
        basis: str = "all",
        group: str = "",
        role: str = "",
        usage_analysis: str = "",
        expected_fingerprint: str = "",
        status_code: int = 200,
    ) -> dict[str, object]:
        snapshots = reports.snapshots()
        selected_snapshot = snapshot or (str(snapshots[0]["snapshot_id"]) if snapshots else "")
        projection = None
        error = None
        if selected_snapshot:
            try:
                projection = reports.gaming_projection(snapshot_id=selected_snapshot)
            except ValueError:
                error = "This snapshot is unavailable for the gaming view. Reload or choose a supported snapshot."
        stale = bool(
            projection
            and expected_fingerprint
            and expected_fingerprint != projection["fingerprint"]
        )
        if basis not in {"all", "known_list", "model"}:
            basis = "all"
        history = analysis.history(limit=10)
        run_ids = {str(item.get("analysis_id")) for item in history}
        selected_run = usage_analysis if usage_analysis in run_ids else ""
        day = moment().astimezone(UTC).date().isoformat()
        usage = reports.usage_summary(
            dispatch_day=None if selected_run else day,
            analysis_id=selected_run or None,
        )
        entries = list(projection.get("entries", ())) if projection else []
        if basis == "known_list":
            entries = [item for item in entries if item["known_list_match"]]
        elif basis == "model":
            entries = [item for item in entries if item["model_proposal"]]
        groups = sorted(
            {
                str(item["group"]["group_id"]): str(item["group"]["group_label"])
                for item in entries
            }.items()
        )
        if group and group not in {group_id for group_id, _ in groups}:
            group = ""
        if group:
            entries = [item for item in entries if item["group"]["group_id"] == group]
        roles = {
            "downloads_updates",
            "launcher",
            "authentication",
            "telemetry",
            "discovery_connectivity",
            "gameplay_matchmaking",
            "shared_infrastructure",
            "unknown",
        }
        if role not in roles:
            role = ""
        if role:
            entries = [
                item
                for item in entries
                if (item.get("analysis") or {}).get("role", "unknown") == role
            ]
        return {
            "projection": projection,
            "error": error,
            "snapshots": snapshots,
            "selected_snapshot": selected_snapshot,
            "entries": entries,
            "basis": basis,
            "group": group,
            "role": role,
            "groups": groups,
            "roles": sorted(roles),
            "usage": usage,
            "usage_day": day,
            "history": history,
            "usage_analysis": selected_run,
            "stale": stale,
            "status_code": status_code,
        }

    def render_gaming(request: Request, **kwargs: object) -> Response:
        context = gaming_context(request, **kwargs)
        status_code = int(context.pop("status_code", 200))
        return render(request, "gaming.html", page="gaming", status_code=status_code, **context)

    @app.get("/gaming", response_class=HTMLResponse)
    def gaming_page(
        request: Request,
        snapshot: str = "",
        basis: str = "all",
        group: str = "",
        role: str = "",
        usage_analysis: str = "",
    ) -> Response:
        return render_gaming(
            request,
            snapshot=snapshot,
            basis=basis,
            group=group,
            role=role,
            usage_analysis=usage_analysis,
        )

    @app.post("/gaming/filter", response_class=HTMLResponse)
    async def gaming_filter(request: Request) -> Response:
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        expected_fingerprint = str(form.get("fingerprint") or "")
        expected_fingerprint = str(form.get("expected_fingerprint") or expected_fingerprint)
        snapshots = reports.snapshots()
        snapshot_id = str(form.get("snapshot") or "")
        if not snapshot_id and snapshots:
            snapshot_id = str(snapshots[0]["snapshot_id"])
        if snapshot_id:
            try:
                current_projection = reports.gaming_projection(snapshot_id=snapshot_id)
            except ValueError:
                current_projection = None
            if current_projection is None:
                raise HTTPException(status_code=404, detail="Snapshot is unavailable")
            if expected_fingerprint != current_projection["fingerprint"]:
                return render_gaming(
                    request,
                    snapshot=snapshot_id,
                    basis=str(form.get("basis") or "all"),
                    group=str(form.get("group") or ""),
                    role=str(form.get("role") or ""),
                    usage_analysis=str(form.get("usage_analysis") or ""),
                    expected_fingerprint=expected_fingerprint,
                    status_code=409,
                )
        return render_gaming(
            request,
            snapshot=snapshot_id,
            basis=str(form.get("basis") or "all"),
            group=str(form.get("group") or ""),
            role=str(form.get("role") or ""),
            usage_analysis=str(form.get("usage_analysis") or ""),
            expected_fingerprint=str(form.get("fingerprint") or ""),
        )

    @app.post("/gaming/export.{format}")
    async def gaming_export(request: Request, format: str) -> Response:
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        if format not in {"csv", "json"}:
            raise HTTPException(status_code=404, detail="Unknown export format")
        snapshot_id = str(form.get("snapshot") or "")
        basis = str(form.get("basis") or "all")
        group = str(form.get("group") or "")
        role = str(form.get("role") or "")
        expected = str(form.get("fingerprint") or "")
        if not snapshot_id:
            raise HTTPException(status_code=404, detail="Snapshot is unavailable")
        try:
            document = reports.gaming_export(
                snapshot_id=snapshot_id, basis=basis, group=group, role=role
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Snapshot is unavailable") from None
        if expected != document["metadata"]["fingerprint"]:
            return render_gaming(
                request,
                snapshot=snapshot_id,
                basis=basis,
                group=group,
                role=role,
                expected_fingerprint=expected,
                status_code=409,
            )
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if format == "json":
            response = JSONResponse(_jsonable(document), headers=headers)
            response.headers["Content-Disposition"] = (
                'attachment; filename="gaming-destinations.json"'
            )
            return response
        output = io.StringIO(newline="")
        fields = [
            "domain",
            "group_id",
            "group_label",
            "group_kind",
            "query_count",
            "first_query_utc",
            "last_query_utc",
            "known_list_match",
            "model_proposal",
            "rule_id",
            "saved_state",
            "saved_role",
            "proposed_service",
            "unknown_reason_code",
            "analysis_id",
            "analysis_created_utc",
            "household_scope",
            "export_schema_version",
            "snapshot_id",
            "window_start_utc",
            "window_end_utc",
            "timezone",
            "namespace_revision",
            "namespace_sha256",
            "fingerprint",
            "filter_basis",
            "filter_group",
            "filter_role",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        metadata = document["metadata"]
        window = metadata["window"]
        for row in document["rows"]:
            flattened = dict(row)
            flattened.update(
                {
                    "export_schema_version": metadata["export_schema_version"],
                    "snapshot_id": metadata["snapshot_id"],
                    "window_start_utc": window["start_utc"],
                    "window_end_utc": window["end_utc"],
                    "timezone": window["timezone"],
                    "namespace_revision": metadata["namespace_revision"],
                    "namespace_sha256": metadata["namespace_sha256"],
                    "fingerprint": metadata["fingerprint"],
                    "filter_basis": metadata["filters"]["basis"],
                    "filter_group": metadata["filters"]["group"],
                    "filter_role": metadata["filters"]["role"],
                }
            )
            for key, value in flattened.items():
                if isinstance(value, str) and value.lstrip(" \t\r\n\x00\x1b").startswith(
                    ("=", "+", "-", "@")
                ):
                    flattened[key] = "'" + value
            writer.writerow(flattened)
        response = Response(
            output.getvalue(), media_type="text/csv; charset=utf-8-sig", headers=headers
        )
        response.headers["Content-Disposition"] = 'attachment; filename="gaming-destinations.csv"'
        return response

    # -- inventory ---------------------------------------------------------
    @app.get("/inventory", response_class=HTMLResponse)
    def inventory_view(request: Request, saved: str = "") -> Response:
        return render(
            request,
            "inventory.html",
            page="inventory",
            data=inventory.devices(),
            error=None,
            saved=saved,
        )

    @app.post("/inventory/{device_key:path}")
    async def inventory_edit(request: Request, device_key: str) -> Response:
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        display_name = str(form.get("display_name") or "")
        category = str(form.get("category") or "").strip().lower()
        try:
            inventory.edit_device(
                device_key,
                display_name=display_name or None,
                # "unknown" is the form's no-choice sentinel, so clearing a
                # category must not record an explicit manual "unknown".
                category=None if category in {"", "unknown"} else category,
            )
        except ValueError as error:
            return render(
                request,
                "inventory.html",
                page="inventory",
                data=inventory.devices(),
                error=str(error),
                saved=None,
            )
        return RedirectResponse(f"/inventory?saved={quote(device_key)}", status_code=303)

    # -- analyses ----------------------------------------------------------
    def preview_context(
        report: Mapping[str, object],
        *,
        preset: str,
        snapshot: str,
        start: str,
        end: str,
        scope: str = "",
    ) -> dict[str, object]:
        domains = {
            str(entry["domain"]): int(entry["query_count"]) for entry in report["destinations"]
        }
        # Reverse lookups are retained locally but are never candidates; listing them
        # here keeps the preview's accounting complete (candidates + exclusions).
        domains.update(
            {
                str(entry["domain"]): int(entry["query_count"])
                for entry in report.get("reverse_lookups", ())
            }
        )
        revision = report.get("classification_cache_revision")
        policy_revision = int(revision) if isinstance(revision, int) else 1
        try:
            preview = analysis.preview(
                period_digest=str(report["period_digest"]),
                domain_rows=domains,
                provider=ai.get("provider"),
                model_id=ai.get("model"),
                config_fingerprint=ai.get("fingerprint"),
                policy_revision=policy_revision,
            )
        except ValueError as error:
            return {"error": str(error), "preview": None}
        return {
            "error": None,
            "preview": preview.as_dict(),
            "period": report["window"],
            "params": {
                "preset": preset,
                "snapshot": snapshot,
                "start": start,
                "end": end,
                "scope": scope,
            },
        }

    @app.get("/analysis", response_class=HTMLResponse)
    def analysis_home(request: Request) -> Response:
        return render(
            request,
            "analysis.html",
            page="analysis",
            history=analysis.history(limit=10),
            limits=analysis.limits(),
            live_manifest=analysis.live_run_manifest_template(),
            error=None,
        )

    @app.get("/analysis/preview", response_class=HTMLResponse)
    def analysis_preview(
        request: Request,
        preset: str = "24h",
        snapshot: str = "",
        start: str = "",
        end: str = "",
        scope: str = "",
    ) -> Response:
        if preset not in PRESETS:
            preset = "24h"
        report, error = build_report(
            request,
            preset=preset,
            snapshot=snapshot,
            start=start,
            end=end,
            household_only=scope == "gaming",
        )
        if report is None:
            return render(
                request,
                "analysis_preview.html",
                page="analysis",
                preview=None,
                params=None,
                period=None,
                error=error or "No observations in that period",
                limits=analysis.limits(),
            )
        context = preview_context(
            report, preset=preset, snapshot=snapshot, start=start, end=end, scope=scope
        )
        return render(
            request,
            "analysis_preview.html",
            page="analysis",
            preview=context.get("preview"),
            params=context.get("params"),
            period=context.get("period"),
            error=context.get("error"),
            limits=analysis.limits(),
        )

    @app.get("/analysis/coverage", response_class=HTMLResponse)
    def analysis_coverage(
        request: Request,
        preset: str = "24h",
        snapshot: str = "",
        start: str = "",
        end: str = "",
        scope: str = "",
        offset: int = 0,
    ) -> Response:
        """Local research coverage and the next first-time worklist page (R15/R16).

        A pure local read model: no external call is made, nothing is selected
        and nothing is started. The shared LAN profile never sees owner research
        pages at all.
        """
        if config.shared_control:
            raise HTTPException(
                status_code=403, detail="Owner research is unavailable on shared control"
            )
        if preset not in PRESETS:
            preset = "24h"
        report, error = build_report(
            request,
            preset=preset,
            snapshot=snapshot,
            start=start,
            end=end,
            household_only=scope == "gaming",
        )
        if report is None:
            return render(
                request,
                "analysis_coverage.html",
                page="analysis",
                summary=None,
                page_of_names=None,
                params=None,
                period=None,
                error=error or "No observations in that period",
                limits=analysis.limits(),
            )
        domains = {
            str(entry["domain"]): int(entry["query_count"]) for entry in report["destinations"]
        }
        domains.update(
            {
                str(entry["domain"]): int(entry["query_count"])
                for entry in report.get("reverse_lookups", ())
            }
        )
        try:
            coverage = analysis.research_coverage(domains)
            summary = analysis.coverage_summary(coverage)
            page_of_names = analysis.first_time_page(coverage, offset=max(0, offset))
        except (TypeError, ValueError) as caught:
            summary = None
            page_of_names = None
            error = error or str(caught)
        return render(
            request,
            "analysis_coverage.html",
            page="analysis",
            summary=summary,
            page_of_names=page_of_names,
            params={
                "preset": preset,
                "snapshot": snapshot,
                "start": start,
                "end": end,
                "scope": scope,
                "offset": max(0, offset),
            },
            period=report["window"],
            error=error,
            limits=analysis.limits(),
        )

    @app.post("/analyses")
    async def start_analysis(request: Request) -> Response:
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        submitted_token = str(form.get("preview_token") or "")
        preset = str(form.get("preset") or "24h")
        snapshot = str(form.get("snapshot") or "")
        start = str(form.get("start") or "")
        end = str(form.get("end") or "")
        scope = "gaming" if str(form.get("scope") or "") == "gaming" else ""
        if preset not in PRESETS:
            raise HTTPException(status_code=400, detail="Unsupported period")
        if not ai.get("enabled"):
            raise HTTPException(
                status_code=409, detail="Analysis is disabled until a provider is configured"
            )
        report, error = build_report(
            request,
            preset=preset,
            snapshot=snapshot,
            start=start,
            end=end,
            household_only=scope == "gaming",
        )
        if report is None:
            raise HTTPException(status_code=404, detail=error or "No observations")
        context = preview_context(
            report, preset=preset, snapshot=snapshot, start=start, end=end, scope=scope
        )
        preview = context.get("preview")
        if context.get("error") or not isinstance(preview, Mapping):
            raise HTTPException(status_code=409, detail=str(context.get("error")))
        if not hmac.compare_digest(str(preview["preview_token"]), submitted_token):
            raise HTTPException(
                status_code=409,
                detail="The preview no longer matches; review the updated preview again",
            )
        analysis_id, created = analysis.start(
            period_digest=str(preview["period_digest"]),
            candidates=preview["candidates"],
            provider=preview["provider"],
            model_id=preview["model_id"],
            config_fingerprint=preview["config_fingerprint"],
            policy_revision=preview["policy_revision"],
            preview_token=str(preview["preview_token"]),
        )
        if created:
            runner(analysis_id, False)
        return RedirectResponse(f"/analysis/{quote(analysis_id)}", status_code=303)

    @app.get("/analysis/{analysis_id}", response_class=HTMLResponse)
    def analysis_status(request: Request, analysis_id: str) -> Response:
        try:
            status = analysis.status(analysis_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Unknown analysis") from None
        items = []
        for item in status["items"]:
            result = None
            if item.get("result_json"):
                try:
                    result = json.loads(str(item["result_json"]))
                except json.JSONDecodeError:
                    result = None
            items.append({**item, "result": result})
        state = str(status["state"])
        return render(
            request,
            "analysis_status.html",
            page="analysis",
            status=status,
            items=items,
            state=state,
            resumable=state in RESUMABLE_STATES,
            terminal=state in TERMINAL_STATES,
            nonce=secrets.token_urlsafe(12),
            limits=analysis.limits(),
        )

    @app.get("/api/analysis/{analysis_id}")
    def analysis_status_json(request: Request, analysis_id: str) -> Response:
        try:
            status = analysis.status(analysis_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Unknown analysis") from None
        payload = {
            "analysis_id": status["analysis_id"],
            "state": status["state"],
            "summary": status["summary"],
            "usage": status["usage"],
            "items": [
                {
                    "item_id": item["item_id"],
                    "domain": item["domain"],
                    "state": item["state"],
                    "result": json.loads(item["result_json"]) if item.get("result_json") else None,
                }
                for item in status["items"]
            ],
        }
        return JSONResponse(_jsonable(payload))

    @app.post("/analysis/{analysis_id}/resume")
    async def resume_analysis(request: Request, analysis_id: str) -> Response:
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        status = analysis.status(analysis_id)
        if str(status["state"]) not in RESUMABLE_STATES:
            raise HTTPException(status_code=409, detail="This analysis cannot be resumed")
        runner(analysis_id, True)
        return RedirectResponse(f"/analysis/{quote(analysis_id)}", status_code=303)

    @app.post("/analysis/{analysis_id}/reanalyze")
    async def reanalyze(request: Request, analysis_id: str) -> Response:
        form = await request.form()
        require_csrf(request, str(form.get(CSRF_FIELD) or ""))
        nonce = str(form.get("nonce") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", nonce):
            raise HTTPException(status_code=400, detail="A local confirmation nonce is required")
        created = analysis.reanalyze(analysis_id, nonce=nonce)
        runner(created, False)
        return RedirectResponse(f"/analysis/{quote(created)}", status_code=303)

    @app.get("/diagnostics/analysis/{analysis_id}.json")
    def download_analysis(request: Request, analysis_id: str) -> Response:
        try:
            status = analysis.status(analysis_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Unknown analysis") from None
        response = JSONResponse(_jsonable(status))
        response.headers["Content-Disposition"] = (
            f'attachment; filename="analysis-{analysis_id[:12]}.json"'
        )
        return response

    return app


__all__ = [
    "AuthError",
    "OwnerAuth",
    "Session",
    "WebConfig",
    "create_app",
    "hash_password",
    "verify_password",
]
