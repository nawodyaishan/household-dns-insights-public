"""Authenticated web boundary: auth, CSRF/Origin/Host, rendering and commands.

All service calls are in-process. The fake runner records requests, so any page view
that accidentally queued work would fail the test. No network, provider, MCP or host
poll is used.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from test_campaign_store import VALID_RULE, Clock, namespace_file

from household_report.analysis import AnalysisService
from household_report.campaign import CampaignService
from household_report.campaign_reporting import CampaignReportService
from household_report.contracts import AttemptBudget
from household_report.inventory import InventoryService
from household_report.reporting import ReportService
from household_report.storage import open_store
from household_report.web import OwnerAuth, WebConfig, create_app, hash_password

BASE = 1_792_728_000  # 2026-10-23 04:00:00 UTC
PASSWORD = "correct horse battery staple"

BUDGET = AttemptBudget(
    per_analysis_requests=8,
    per_day_requests=40,
    per_analysis_tokens=100_000,
    per_day_tokens=400_000,
    per_analysis_exa=8,
    per_day_exa=40,
)

ROWS = [
    {
        "id": 1,
        "timestamp": BASE + 30,
        "type": 1,
        "status": 2,
        "domain": "www.example.com",
        "client": "192.168.1.1",
        "forward": "1.2.3.4",
        "additional_info": None,
        "list_id": 0,
        "reply_type": 5,
        "ede": None,
        "reply_time": 0.02,
        "dnssec": 0,
    },
    {
        "id": 2,
        "timestamp": BASE + 60,
        "type": 1,
        "status": 2,
        "domain": "api.example.org",
        "client": "192.168.1.1",
        "forward": "1.2.3.5",
        "additional_info": None,
        "list_id": 0,
        "reply_type": 5,
        "ede": None,
        "reply_time": 0.03,
        "dnssec": 0,
    },
    {
        "id": 3,
        "timestamp": BASE + 90,
        "type": 1,
        "status": 2,
        "domain": "cdn.example.net",
        "client": "192.168.1.23",
        "forward": "1.2.3.6",
        "additional_info": None,
        "list_id": 0,
        "reply_type": 5,
        "ede": None,
        "reply_time": 0.01,
        "dnssec": 0,
    },
]

SNAPSHOT = {
    "schema_version": 2,
    "start_epoch": BASE,
    "end_epoch": BASE + 3600,
    "captured_utc": "2026-10-23T05:00:00Z",
    "retained_rows": 3,
    "oldest_epoch": float(BASE),
    "newest_epoch": float(BASE + 90),
    "window_count": len(ROWS),
    "observations": ROWS,
}


def presence_envelope() -> dict[str, object]:
    body = {
        "apiVersion": 133,
        "wifiGetClients": {
            "clients": [
                {
                    "name": "device-a",
                    "macAddress": "aa:bb:cc:dd:ee:01",
                    "ipAddress": "192.168.1.23",
                    "iface": "RF_5GHZ",
                    "role": "CLIENT",
                }
            ]
        },
    }
    return {
        "start": "2026-10-23T04:00:05Z",
        "end": "2026-10-23T04:00:05Z",
        "endpoint": "dish",
        "tail": [],
        "returncode": 0,
        "stdout": json.dumps(body),
        "stderr": "",
    }


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = open_store(self.root / "app.sqlite3")
        self.addCleanup(self.store.close)
        self.store.import_snapshot(SNAPSHOT, datasource="test")
        self.inventory = InventoryService(self.store)
        poll = self.root / "presence-00.json"
        poll.write_text(json.dumps(presence_envelope()))
        self.inventory.import_poll_file(poll)
        self.reports = ReportService(
            self.store,
            timezone="UTC",
            attribution_source=self.inventory.attributions,
        )
        self.analysis = AnalysisService(self.store, budget=BUDGET)
        self.runner_calls: list[tuple[str, bool]] = []
        self.auth = OwnerAuth(
            password_record=hash_password(PASSWORD),
            session_key=b"k" * 32,
            failure_delay_seconds=0.0,
        )
        self.ai = {
            "enabled": True,
            "provider": "groq",
            "model": "test-model",
            "free_only": True,
            "exa_enabled": True,
            "fingerprint": "fingerprint",
            "spend": {
                "paid_mode": False,
                "provider_price_per_million": None,
                "exa_price_per_operation": None,
                "currency_ceiling_run": None,
                "currency_ceiling_day": None,
                "exa_currency_ceiling_run": None,
                "exa_currency_ceiling_day": None,
            },
        }
        self.client = TestClient(self.app())
        self.addCleanup(self.client.close)

    def app(self):
        return create_app(
            auth=self.auth,
            config=WebConfig(
                allowed_hosts=("testserver",),
                public_url="http://testserver",
                max_body_bytes=4096,
            ),
            reports=self.reports,
            inventory=self.inventory,
            analysis=self.analysis,
            runner=lambda analysis_id, allow_resume: self.runner_calls.append(
                (analysis_id, allow_resume)
            ),
            ai=self.ai,
            timezone="UTC",
        )

    def login(self) -> None:
        response = self.client.post(
            "/login", data={"password": PASSWORD, "next": "/"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303, response.text)

    def csrf(self, path: str = "/inventory") -> str:
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        match = re.search(r'name="csrf" value="([^"]+)"', page.text)
        self.assertIsNotNone(match, "no CSRF field on the page")
        return match.group(1)


class AuthTests(WebTestCase):
    def test_default_page_shows_stale_collector_while_web_is_healthy(self):
        self.client = TestClient(
            create_app(
                auth=self.auth,
                config=WebConfig(
                    allowed_hosts=("testserver",),
                    public_url="http://testserver",
                    max_body_bytes=4096,
                ),
                reports=self.reports,
                inventory=self.inventory,
                analysis=self.analysis,
                runner=lambda analysis_id, allow_resume: None,
                ai=self.ai,
                timezone="UTC",
                collector=lambda: {
                    "state": "stale_heartbeat",
                    "label": "Collector heartbeat is stale",
                    "detail": "No bridge heartbeat for 1000s.",
                    "last_bridge_epoch_utc": None,
                    "last_capture_epoch_utc": None,
                    "last_import_epoch_utc": None,
                    "consecutive_failures": 0,
                    "report_bounds_utc": None,
                    "report_rules_revision": None,
                },
            )
        )
        self.login()
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Collector heartbeat is stale", page.text)

    def test_default_page_reports_unavailable_timer_without_status_file(self):
        self.client = TestClient(
            create_app(
                auth=self.auth,
                config=WebConfig(
                    allowed_hosts=("testserver",),
                    public_url="http://testserver",
                    max_body_bytes=4096,
                ),
                reports=self.reports,
                inventory=self.inventory,
                analysis=self.analysis,
                runner=lambda analysis_id, allow_resume: None,
                ai=self.ai,
                timezone="UTC",
                collector=lambda: {
                    "state": "unavailable",
                    "label": "Timer state unavailable",
                    "detail": "No fresh host status file.",
                    "last_bridge_epoch_utc": None,
                    "last_capture_epoch_utc": None,
                    "last_import_epoch_utc": None,
                    "consecutive_failures": None,
                    "report_bounds_utc": None,
                    "report_rules_revision": None,
                },
            )
        )
        self.login()
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Timer state unavailable", page.text)

    def test_unauthenticated_page_redirects_to_login(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?next="))

    def test_shared_lan_mode_opens_existing_views_but_requires_same_origin_for_actions(self):
        self.ai = dict(self.ai, enabled=False, provider=None, exa_enabled=False)
        self.client = TestClient(
            create_app(
                auth=self.auth,
                config=WebConfig(
                    allowed_hosts=("testserver",),
                    public_url="http://testserver",
                    shared_control=True,
                ),
                reports=self.reports,
                inventory=self.inventory,
                analysis=self.analysis,
                runner=lambda analysis_id, allow_resume: self.runner_calls.append(
                    (analysis_id, allow_resume)
                ),
                ai=self.ai,
                timezone="UTC",
            )
        )
        for path in ("/", "/gaming", "/inventory", "/analysis"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertNotEqual(self.client.get("/diagnostics/report.json").status_code, 303)
        self.assertNotIn("/login", self.client.get("/").text)
        self.assertEqual(self.client.get("/login", follow_redirects=False).status_code, 404)
        for headers in (
            {},
            {"origin": "http://evil.test"},
            {"origin": "http://testserver", "sec-fetch-site": "cross-site"},
        ):
            self.assertEqual(
                self.client.post(
                    "/inventory/example", data={"label": "bad"}, headers=headers
                ).status_code,
                403,
            )
        self.assertEqual(self.client.get("/", headers={"host": "evil.test"}).status_code, 400)
        response = self.client.post(
            "/gaming/filter", data={}, headers={"origin": "http://testserver"}
        )
        self.assertNotEqual(response.status_code, 403, response.text)
        self.assertEqual(
            self.client.post(
                "/analyses", data={}, headers={"origin": "http://testserver"}
            ).status_code,
            409,
        )
        self.assertEqual(self.runner_calls, [])

    def test_static_assets_are_public_but_pages_are_not(self):
        self.assertEqual(self.client.get("/static/app.css").status_code, 200)
        self.assertEqual(self.client.get("/inventory", follow_redirects=False).status_code, 303)

    def test_wrong_password_is_rejected_and_throttled(self):
        for _ in range(5):
            response = self.client.post("/login", data={"password": "wrong"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post("/login", data={"password": "wrong"}).status_code, 429)
        self.assertEqual(self.client.post("/login", data={"password": PASSWORD}).status_code, 429)

    def test_login_sets_http_only_strict_cookie(self):
        response = self.client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Path=/", cookie)

    def test_logout_clears_the_session(self):
        self.login()
        page = self.client.get("/")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)
        self.assertIsNotNone(csrf, page.text[:600])
        csrf = csrf.group(1)
        response = self.client.post("/logout", data={"csrf": csrf}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 303)

    def test_open_redirect_is_refused(self):
        response = self.client.post(
            "/login",
            data={"password": PASSWORD, "next": "https://evil.example/"},
            follow_redirects=False,
        )
        self.assertEqual(response.headers["location"], "/")


class HouseholdAccessTests(WebTestCase):
    def test_public_route_is_explicit_and_legacy_routes_stay_owner_only(self):
        self.assertEqual(self.client.get("/household", follow_redirects=False).status_code, 200)
        for path in ("/", "/gaming", "/inventory", "/diagnostics/report.json", "/analysis"):
            self.assertEqual(self.client.get(path, follow_redirects=False).status_code, 303)
        self.assertEqual(
            self.client.get("/household/unknown", follow_redirects=False).status_code, 404
        )

    def test_anonymous_landing_hides_owner_navigation(self):
        page = self.client.get("/household")
        self.assertIn('href="/household"', page.text)
        for link in ('href="/gaming"', 'href="/inventory"', 'href="/analysis"'):
            self.assertNotIn(link, page.text)
        self.login()
        self.assertIn('href="/gaming"', self.client.get("/household").text)


class PublicCampaignTests(WebTestCase):
    def app(self):
        if not hasattr(self, "campaigns"):
            self.clock = Clock(BASE)
            rules = self.root / "rules.json"
            rules.write_bytes(namespace_file([VALID_RULE]))
            self.campaigns = CampaignService(
                self.store, now=self.clock, namespace_path=rules, timezone="UTC"
            )
            self.campaign_id = self.campaigns.start(days=3, retention_days=7)["campaign_id"]
            self.frozen = CampaignReportService(self.store, now=self.clock)
        return create_app(
            auth=self.auth,
            config=WebConfig(
                allowed_hosts=("testserver",),
                public_url="http://testserver",
                max_body_bytes=4096,
                shared_control=getattr(self, "shared_control", False),
            ),
            reports=self.reports,
            inventory=self.inventory,
            analysis=self.analysis,
            runner=lambda *args: self.fail("Public requests must never dispatch AI"),
            ai={"enabled": False},
            timezone="UTC",
            campaigns=self.campaigns,
            campaign_reports=self.frozen,
            clock=lambda: __import__("datetime").datetime.fromtimestamp(
                self.clock.epoch, __import__("datetime").UTC
            ),
        )

    def seed(self):
        self.store.register_source_generation(generation_id="public-gen", identity="synthetic")
        self.clock.epoch = BASE + 3600 + 120
        chunk = self.campaigns.claim_capture_work(generation_id="public-gen", limit=1)[0]
        self.campaigns.ack_capture(
            chunk["chunk_id"], token=chunk["lease_token"], digest="a" * 64, path="synthetic.json"
        )
        self.campaigns.mark_import_pending(chunk["chunk_id"])
        snapshot = {
            "schema_version": 2,
            "read_state": "ok",
            "source_generation": "public-gen",
            "start_epoch": BASE,
            "end_epoch": BASE + 3600,
            "window_count": 2,
            "retained_rows": 2,
            "oldest_epoch": BASE - 3600,
            "captured_utc": "2026-10-23T05:00:00Z",
            "observations": [
                {
                    "id": 1,
                    "timestamp": BASE + 20,
                    "type": 1,
                    "status": 2,
                    "domain": "play.games.example",
                    "client": "private-client",
                    "reply_type": 4,
                },
                {
                    "id": 2,
                    "timestamp": BASE + 25,
                    "type": 1,
                    "status": 2,
                    "domain": "unrelated.private.example",
                    "client": "private-client",
                    "reply_type": 4,
                },
            ],
        }
        self.store.import_campaign_capture(
            self.campaign_id,
            chunk_id=chunk["chunk_id"],
            generation_id="public-gen",
            artifact_digest=hashlib.sha256(
                json.dumps(snapshot, sort_keys=True).encode()
            ).hexdigest(),
            snapshot=snapshot,
            reconciled=False,
        )

    def test_shared_lan_campaign_actions_are_visible_and_confirmed(self):
        self.shared_control = True
        self.client = TestClient(self.app())
        self.addCleanup(self.client.close)
        page = self.client.get("/household/owner")
        self.assertEqual(page.status_code, 200)
        self.assertIn("data-confirm=", page.text)
        self.assertEqual(self.client.post("/household/owner/finish", data={}).status_code, 403)
        self.clock.epoch += 60
        response = self.client.post(
            "/household/owner/finish", data={}, headers={"origin": "http://testserver"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "finalizing")

    def test_public_generation_requires_signed_token_origin_and_same_campaign(self):
        self.seed()
        page = self.client.get("/household")
        self.assertEqual(page.status_code, 200)
        token = re.search(r'name="view_token" value="([^"]+)"', page.text).group(1)
        for data, headers in (
            ({"view_token": "invalid"}, {"origin": "http://testserver"}),
            ({"view_token": token}, {}),
            ({"view_token": token}, {"origin": "http://evil.example"}),
        ):
            self.assertEqual(
                self.client.post("/household/generate", data=data, headers=headers).status_code, 403
            )
        response = self.client.post(
            "/household/generate",
            data={"view_token": token},
            headers={"origin": "http://testserver"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            self.client.post(
                "/household/generate",
                data={"view_token": token},
                headers={"origin": "http://testserver"},
            ).json()["job_id"],
            response.json()["job_id"],
        )

    def test_frozen_public_report_and_exports_are_allowlisted_and_expire(self):
        self.seed()
        job = self.frozen.request(self.campaign_id)
        self.frozen.run_next(self.campaign_id)
        report_id = self.frozen.job_status(job)["report_id"]
        for path in (
            f"/household/reports/{report_id}",
            f"/household/reports/{report_id}/export.json",
            f"/household/reports/{report_id}/export.csv",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("play.games.example", response.text)
            self.assertNotIn("unrelated.private.example", response.text)
            self.assertNotIn("private-client", response.text)
        self.clock.epoch = BASE + 72 * 3600 + 7 * 86400 + 1
        self.assertEqual(self.client.get(f"/household/reports/{report_id}").status_code, 404)
        self.assertEqual(
            self.client.get(f"/household/reports/{report_id}/export.json").status_code, 404
        )
        self.assertEqual(self.client.get(f"/household/jobs/{job}").status_code, 404)

    def test_public_filter_and_download_use_same_frozen_subset(self):
        self.seed()
        job = self.frozen.request(self.campaign_id)
        self.frozen.run_next(self.campaign_id)
        report_id = self.frozen.job_status(job)["report_id"]
        page = self.client.get(f"/household/reports/{report_id}?basis=model")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("play.games.example", page.text)
        data = self.client.get(f"/household/reports/{report_id}/export.json?basis=model").json()
        self.assertEqual(data["rows"], [])
        self.assertIn("eligible_rows", data["counts"])
        csv = self.client.get(f"/household/reports/{report_id}/export.csv?basis=model")
        self.assertNotIn("play.games.example", csv.text)

    def test_owner_controls_are_protected_and_require_csrf(self):
        self.assertEqual(
            self.client.get("/household/owner", follow_redirects=False).status_code, 303
        )
        self.assertEqual(
            self.client.post(
                "/household/owner/finish", data={}, headers={"origin": "http://testserver"}
            ).status_code,
            403,
        )
        self.login()
        page = self.client.get("/household/owner")
        self.assertEqual(page.status_code, 200)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        self.assertEqual(
            self.client.post(
                "/household/owner/extend",
                data={"hours": "48"},
                headers={"origin": "http://testserver"},
            ).status_code,
            403,
        )
        result = self.client.post(
            "/household/owner/extend",
            data={"csrf": csrf, "hours": "48"},
            headers={"origin": "http://testserver"},
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            self.campaigns.status(self.campaign_id)["utc_bounds"][1], BASE + 120 * 3600
        )

    def test_generate_accepts_trailing_24h_and_48h_periods(self):
        self.seed()
        token = re.search(
            r'name="view_token" value="([^"]+)"', self.client.get("/household").text
        ).group(1)
        for hours in ("24", "48"):
            response = self.client.post(
                "/household/generate",
                data={"view_token": token, "hours": hours},
                headers={"origin": "http://testserver"},
            )
            self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            self.client.post(
                "/household/generate",
                data={"view_token": token, "hours": "12"},
                headers={"origin": "http://testserver"},
            ).status_code,
            400,
        )

    def test_ordinary_flows_make_zero_external_calls(self):
        self.seed()
        # The app's runner fails on any dispatch, so reaching these ordinary
        # refresh/report/export routes proves no external call was made.
        for path in ("/", "/gaming", "/household", "/inventory"):
            self.assertIn(self.client.get(path).status_code, (200, 303), path)
        job = self.frozen.request(self.campaign_id)
        self.frozen.run_next(self.campaign_id)
        report_id = self.frozen.job_status(job)["report_id"]
        for suffix in ("", "/export.json", "/export.csv"):
            self.assertEqual(
                self.client.get(f"/household/reports/{report_id}{suffix}").status_code, 200, suffix
            )

    def test_ai_off_refuses_analysis_start_without_any_dispatch(self):
        self.seed()
        self.ai = dict(self.ai, enabled=False, provider=None, exa_enabled=False)
        self.client = TestClient(self.app())
        self.addCleanup(self.client.close)
        self.login()
        csrf = re.search(
            r'name="csrf" value="([^"]+)"', self.client.get("/household/owner").text
        ).group(1)
        response = self.client.post(
            "/analyses",
            data={"csrf": csrf, "preview_token": "x", "preset": "snapshot"},
            headers={"origin": "http://testserver"},
        )
        self.assertEqual(response.status_code, 409)

    def test_owner_review_route_requires_auth_and_csrf_and_denies_shared(self):
        self.seed()
        self.assertEqual(
            self.client.post(
                "/household/owner/review", data={}, headers={"origin": "http://testserver"}
            ).status_code,
            403,
        )
        self.login()
        page = self.client.get("/household/owner")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        self.assertEqual(
            self.client.post(
                "/household/owner/review",
                data={"hostname": "x.test"},
                headers={"origin": "http://testserver"},
            ).status_code,
            403,
        )
        result = self.client.post(
            "/household/owner/review",
            data={
                "csrf": csrf,
                "campaign_id": self.campaign_id,
                "hostname": "lobby.example.net",
                "group_id": "game-two",
                "group_label": "Game Two",
                "group_kind": "game",
                "review_note": "Owner-verified.",
            },
            headers={"origin": "http://testserver"},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["namespace"], "lobby.example.net")
        # Shared LAN control cannot promote rules, even same-origin.
        self.shared_control = True
        self.client = TestClient(self.app())
        self.addCleanup(self.client.close)
        self.assertEqual(
            self.client.post(
                "/household/owner/review", data={}, headers={"origin": "http://testserver"}
            ).status_code,
            403,
        )

    def test_public_queue_is_bounded_and_rate_limited(self):
        self.seed()
        token = re.search(
            r'name="view_token" value="([^"]+)"', self.client.get("/household").text
        ).group(1)
        for n in range(10):
            self.store.create_job(
                job_id=f"existing-{n}",
                campaign_id=self.campaign_id,
                kind="report",
                dedup_key=f"other-{n}",
            )
        response = self.client.post(
            "/household/generate",
            data={"view_token": token},
            headers={"origin": "http://testserver"},
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "60")
        self.assertEqual(len(self.store.pending_jobs(self.campaign_id, kind="report")), 10)

    def test_public_and_malicious_direct_analysis_posts_never_dispatch_provider(self):
        self.assertEqual(
            self.client.post(
                "/analyses", data={"preview_token": "x"}, headers={"origin": "http://testserver"}
            ).status_code,
            403,
        )
        self.login()
        csrf = re.search(
            r'name="csrf" value="([^"]+)"', self.client.get("/household/owner").text
        ).group(1)
        response = self.client.post(
            "/analyses",
            data={"csrf": csrf, "preview_token": "x", "preset": "snapshot"},
            headers={"origin": "http://testserver"},
        )
        self.assertEqual(response.status_code, 409)

    def test_public_token_expires_and_host_fetch_metadata_are_enforced(self):
        self.seed()
        token = re.search(
            r'name="view_token" value="([^"]+)"', self.client.get("/household").text
        ).group(1)
        self.clock.advance(601)
        for headers in (
            {"origin": "http://testserver"},
            {"origin": "http://testserver", "host": "evil.example"},
            {"origin": "http://testserver", "sec-fetch-site": "cross-site"},
        ):
            response = self.client.post(
                "/household/generate", data={"view_token": token}, headers=headers
            )
            self.assertIn(response.status_code, (400, 403))
        self.assertEqual(
            self.store._conn.execute(
                "SELECT count(*) FROM local_jobs WHERE kind='report'"
            ).fetchone()[0],
            0,
        )

    def test_expired_campaign_rejects_direct_report_export_and_generation(self):
        self.seed()
        job = self.frozen.request(self.campaign_id)
        self.frozen.run_next(self.campaign_id)
        report = self.frozen.job_status(job)["report_id"]
        token = re.search(
            r'name="view_token" value="([^"]+)"', self.client.get("/household").text
        ).group(1)
        self.clock.epoch = BASE + 72 * 3600 + 7 * 86400 + 1
        self.assertEqual(
            self.client.post(
                "/household/generate",
                data={"view_token": token},
                headers={"origin": "http://testserver"},
            ).status_code,
            404,
        )
        for suffix in ("", "/export.csv", "/export.json"):
            self.assertEqual(
                self.client.get(f"/household/reports/{report}{suffix}").status_code, 404
            )
        self.assertNotIn("play.games.example", self.client.get("/household").text)


class RequestProvenanceTests(WebTestCase):
    def test_host_header_must_be_allowlisted(self):
        response = self.client.get("/login", headers={"host": "evil.example"})
        self.assertEqual(response.status_code, 400)

    def test_cross_origin_post_is_refused(self):
        response = self.client.post(
            "/login",
            data={"password": PASSWORD},
            headers={"origin": "http://evil.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_same_origin_post_is_accepted_but_null_origin_is_refused(self):
        accepted = self.client.post(
            "/login",
            data={"password": PASSWORD},
            headers={"origin": "http://testserver"},
            follow_redirects=False,
        )
        self.assertEqual(accepted.status_code, 303)
        refused = self.client.post(
            "/login",
            data={"password": PASSWORD},
            headers={"origin": "null"},
        )
        self.assertEqual(refused.status_code, 403)

    def test_body_cap_is_enforced(self):
        response = self.client.post("/login", data={"password": "x" * 10_000})
        self.assertEqual(response.status_code, 413)

    def test_security_headers_are_present(self):
        response = self.client.get("/login")
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "same-origin")


class ReportViewTests(WebTestCase):
    def test_dashboard_renders_stored_observations_locally(self):
        self.login()
        response = self.client.get("/?preset=snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertIn("www.example.com", response.text)
        self.assertIn("api.example.org", response.text)
        self.assertIn("classification", response.text.lower())
        self.assertEqual(self.runner_calls, [])
        # No remote asset or link may be emitted by the page.
        self.assertNotRegex(response.text, r'(?:src|href)="https?://')
        self.assertNotIn("http://evil", response.text)

    def test_dashboard_shows_saved_model_proposal_and_reconciled_role_coverage(self):
        analysis_id, _ = self.analysis.create(
            period_digest="a" * 64,
            selected_item_ids=["www.example.com"],
            candidates=[{"item_id": "www.example.com", "domain": "www.example.com"}],
            provider="groq",
            model_id="test-model",
            config_fingerprint="fingerprint",
            policy_revision=1,
        )
        self.analysis.checkpoint(
            analysis_id,
            "www.example.com",
            outcome="done",
            result={
                "source": "model",
                "service": "Example Launcher",
                "provider": "Example Inc",
                "role": "downloads_updates",
                "category": "software",
                "confidence": "medium",
                "verification_state": "ai_grounded",
                "supporting_spans": [
                    {
                        "source_id": "s1",
                        "source_url": "https://docs.example/downloads",
                        "source_sha256": "b" * 64,
                        "start": 0,
                        "end": 28,
                        "text": "Example launcher downloads <script>alert(1)</script>",
                    }
                ],
            },
        )
        self.analysis.finish_with_summary(analysis_id, state="completed")
        attempts_before = self.store.count_attempts(analysis_id)
        self.login()
        page = self.client.get("/?preset=snapshot")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Model Proposal", page.text)
        self.assertIn("downloads updates", page.text)
        self.assertIn("Example launcher downloads", page.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page.text)
        self.assertNotIn("<script>alert(1)</script>", page.text)
        self.assertIn("https://docs.example/downloads", page.text)
        self.assertIn("All household destinations", page.text)
        self.assertIn("No saved model analysis", page.text)
        self.assertEqual(self.runner_calls, [])
        self.assertEqual(self.store.count_attempts(analysis_id), attempts_before)

    def test_filters_are_local_and_keep_the_denominators_visible(self):
        self.login()
        response = self.client.get("/?preset=snapshot&q=api")
        self.assertEqual(response.status_code, 200)
        self.assertIn("api.example.org", response.text)
        self.assertNotIn("cdn.example.net", response.text)
        self.assertIn("Showing 1 of 3 domains", response.text)
        self.assertEqual(self.runner_calls, [])

    def test_report_json_download_is_an_attachment(self):
        self.login()
        response = self.client.get("/diagnostics/report.json?preset=snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        payload = response.json()
        self.assertEqual(payload["summary"]["raw_rows"], 3)
        self.assertIn("period_digest", payload)
        self.assertIn("timeline", payload)

    def test_unknown_snapshot_is_reported_not_invented(self):
        self.login()
        response = self.client.get("/?preset=24h&snapshot=missing")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Unknown snapshot", response.text)


class GamingViewTests(WebTestCase):
    def test_gaming_view_is_authenticated_and_renders_empty_namespace_and_usage(self):
        response = self.client.get("/gaming", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.login()
        before = self.store._conn.execute("SELECT count(*) FROM call_attempts").fetchone()[0]
        response = self.client.get("/gaming")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Known-list unavailable", response.text)
        self.assertIn(
            "No destinations met the known-list or gameplay-matchmaking predicate", response.text
        )
        self.assertIn("Local recorded usage", response.text)
        self.assertIn("Exa MCP", response.text)
        self.assertIn("Model provider", response.text)
        self.assertEqual(self.runner_calls, [])
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM call_attempts").fetchone()[0], before
        )

    def test_gaming_filters_are_csrf_protected_posts_and_select_synthetic_rule_match(self):
        self.login()
        rule_file = self.root / "gaming-namespaces.json"
        rule_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "revision": "synthetic-r1",
                    "rules": [
                        {
                            "rule_id": "game-rule",
                            "namespace": "example.com",
                            "match": "suffix",
                            "group_id": "example-game",
                            "group_label": "Synthetic example game",
                            "group_kind": "game",
                            "review_note": "Synthetic test fixture only",
                        }
                    ],
                }
            )
        )
        self.reports._gaming_namespace_path = rule_file
        page = self.client.get("/gaming")
        self.assertEqual(page.status_code, 200)
        self.assertIn("www.example.com", page.text)
        self.assertIn("Known-list match", page.text)
        self.assertNotIn("192.168.1.1", page.text)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        fingerprint = re.search(r'name="fingerprint" value="([^"]+)"', page.text).group(1)
        filtered = self.client.post(
            "/gaming/filter",
            data={
                "csrf": csrf,
                "snapshot": self.store.snapshots()[0]["snapshot_id"],
                "basis": "known_list",
                "group": "example-game",
                "role": "",
                "fingerprint": fingerprint,
            },
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertIn("www.example.com", filtered.text)
        self.assertEqual(self.runner_calls, [])
        attempts = self.store._conn.execute("SELECT count(*) FROM call_attempts").fetchone()[0]
        self.assertEqual(attempts, 0)

    def test_exports_match_page_selection_and_omit_private_fields(self):
        self.login()
        self.reports._gaming_namespace_path = self.root / "gaming-namespaces.json"
        self.reports._gaming_namespace_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "revision": "export-test",
                    "rules": [
                        {
                            "rule_id": "known",
                            "namespace": "example.com",
                            "match": "suffix",
                            "group_id": "example-game",
                            "group_label": "Example game",
                            "group_kind": "game",
                            "review_note": "Synthetic only",
                        }
                    ],
                }
            )
        )
        page = self.client.get("/gaming")
        fingerprint = re.search(r'name="fingerprint" value="([^"]+)"', page.text).group(1)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        snapshot_id = self.store.snapshots()[0]["snapshot_id"]
        data = {
            "csrf": csrf,
            "snapshot": snapshot_id,
            "basis": "known_list",
            "group": "example-game",
            "role": "",
            "fingerprint": fingerprint,
        }
        html_selection = self.client.post(
            "/gaming/filter", data={**data, "expected_fingerprint": fingerprint}
        )
        self.assertEqual(html_selection.status_code, 200)
        visible = re.findall(r'<p class="domain">([^<]+)</p>', html_selection.text)
        csv_response = self.client.post("/gaming/export.csv", data=data)
        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        self.assertIn(
            'attachment; filename="gaming-destinations.csv"',
            csv_response.headers["content-disposition"],
        )
        self.assertEqual(csv_response.headers["cache-control"], "no-store")
        csv_rows = list(csv.DictReader(io.StringIO(csv_response.text)))
        self.assertEqual([row["domain"] for row in csv_rows], visible)
        self.assertTrue(all(row["known_list_match"] == "True" for row in csv_rows))
        json_response = self.client.post("/gaming/export.json", data=data)
        self.assertEqual(json_response.status_code, 200, json_response.text)
        document = json_response.json()
        self.assertEqual([row["domain"] for row in document["rows"]], visible)
        encoded = json_response.text.lower()
        for forbidden in (
            "192.168.1.23",
            '"client"',
            '"observation_ids"',
            "filesystem",
            "credentials",
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertIn("limitations", document)

    def test_export_rejects_stale_fingerprint_and_unknown_snapshot(self):
        self.login()
        page = self.client.get("/gaming")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        snapshot_id = self.store.snapshots()[0]["snapshot_id"]
        stale = self.client.post(
            "/gaming/export.json",
            data={
                "csrf": csrf,
                "snapshot": snapshot_id,
                "basis": "all",
                "fingerprint": "stale",
            },
        )
        self.assertEqual(stale.status_code, 409)
        self.assertIn("changed since it was displayed", stale.text)
        self.assertIn('name="fingerprint"', stale.text)
        unknown = self.client.post(
            "/gaming/export.csv",
            data={
                "csrf": csrf,
                "snapshot": "missing",
                "basis": "all",
                "fingerprint": "x",
            },
        )
        self.assertEqual(unknown.status_code, 404)

    def test_filter_rejects_stale_fingerprint(self):
        self.login()
        page = self.client.get("/gaming")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        snapshot_id = self.store.snapshots()[0]["snapshot_id"]
        response = self.client.post(
            "/gaming/filter",
            data={
                "csrf": csrf,
                "snapshot": snapshot_id,
                "basis": "all",
                "fingerprint": "stale",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("changed since it was displayed", response.text)

    def test_csv_formula_cells_are_neutralized_and_empty_csv_has_headers(self):
        self.login()
        self.reports._gaming_namespace_path = self.root / "gaming-namespaces.json"
        self.reports._gaming_namespace_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "revision": "formula",
                    "rules": [
                        {
                            "rule_id": "known",
                            "namespace": "example.com",
                            "match": "suffix",
                            "group_id": "example-game",
                            "group_label": "Example game",
                            "group_kind": "game",
                            "review_note": "Synthetic only",
                        }
                    ],
                }
            )
        )
        page = self.client.get("/gaming")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        snapshot_id = self.store.snapshots()[0]["snapshot_id"]
        projection = self.reports.gaming_projection(snapshot_id=snapshot_id)
        projection["entries"][0]["domain"] = "=1+1"
        self.reports.gaming_export = lambda **kwargs: __import__(
            "household_report.gaming", fromlist=["gaming_export_projection"]
        ).gaming_export_projection(
            projection, basis=kwargs["basis"], group=kwargs["group"], role=kwargs["role"]
        )
        response = self.client.post(
            "/gaming/export.csv",
            data={
                "csrf": csrf,
                "snapshot": snapshot_id,
                "basis": "all",
                "fingerprint": projection["fingerprint"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("'=1+1", response.text)
        from unittest.mock import patch

        with patch.object(
            self.reports,
            "gaming_export",
            return_value={
                "metadata": {
                    "fingerprint": "empty",
                    "export_schema_version": 1,
                    "snapshot_id": snapshot_id,
                    "window": {"start_utc": "a", "end_utc": "b", "timezone": "UTC"},
                    "namespace_revision": None,
                    "namespace_sha256": None,
                    "filters": {"basis": "all", "group": "", "role": ""},
                },
                "rows": [],
            },
        ):
            empty = self.client.post(
                "/gaming/export.csv",
                data={
                    "csrf": csrf,
                    "snapshot": snapshot_id,
                    "basis": "all",
                    "fingerprint": "empty",
                },
            )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(len(list(csv.reader(io.StringIO(empty.text)))), 1)

    def test_review_analysis_action_opens_snapshot_wide_preview_without_dispatch(self):
        self.login()
        self.reports._attribution_source = lambda _rows: self.fail(
            "gaming analysis preview must not look up device attribution"
        )
        page = self.client.get("/gaming")
        self.assertEqual(page.status_code, 200)
        self.assertIn("This scope is not limited to the filtered gaming list", page.text)
        snapshot_id = self.store.snapshots()[0]["snapshot_id"]
        preview = self.client.get(
            "/analysis/preview",
            params={"preset": "snapshot", "snapshot": snapshot_id, "scope": "gaming"},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIn("Confirm what would leave this machine", preview.text)
        self.assertIn("example.com", preview.text)
        self.assertIn("api.example.org", preview.text)
        self.assertEqual(self.runner_calls, [])
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM call_attempts").fetchone()[0], 0
        )
        csrf = re.search(r'name="csrf" value="([^"]+)"', preview.text).group(1)
        token = re.search(r'name="preview_token" value="([^"]+)"', preview.text).group(1)
        started = self.client.post(
            "/analyses",
            data={
                "csrf": csrf,
                "preview_token": token,
                "preset": "snapshot",
                "snapshot": snapshot_id,
                "scope": "gaming",
            },
            follow_redirects=False,
        )
        self.assertEqual(started.status_code, 303, started.text)
        self.assertEqual(len(self.runner_calls), 1)
        analysis_id = self.runner_calls[0][0]
        submitted = {item["domain"] for item in self.store.items(analysis_id)}
        self.assertEqual(submitted, {"example.com", "api.example.org", "cdn.example.net"})
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM call_attempts").fetchone()[0], 0
        )


class InventoryViewTests(WebTestCase):
    def test_inventory_shows_presence_and_explicit_unknown_attribution(self):
        self.login()
        response = self.client.get("/inventory")
        self.assertEqual(response.status_code, 200)
        self.assertIn("listed", response.text)
        self.assertIn("device-unknown", response.text)
        self.assertIn("not proof", response.text)

    def test_manual_edit_requires_csrf_and_is_audited(self):
        self.login()
        key = "mac:aa:bb:cc:dd:ee:01"
        refused = self.client.post(f"/inventory/{key}", data={"display_name": "X"})
        self.assertEqual(refused.status_code, 403)
        csrf = self.csrf()
        response = self.client.post(
            f"/inventory/{key}",
            data={"csrf": csrf, "display_name": "Kitchen TV", "category": "tv"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        revisions = self.store.device_settings()
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["display_name"], "Kitchen TV")
        page = self.client.get("/inventory")
        self.assertIn("Kitchen TV", page.text)
        self.assertIn("device-a", page.text)

    def test_clearing_an_override_records_no_manual_category(self):
        self.login()
        key = "mac:aa:bb:cc:dd:ee:01"
        csrf = self.csrf()
        self.client.post(
            f"/inventory/{key}",
            data={"csrf": csrf, "display_name": "Kitchen TV", "category": "tv"},
            follow_redirects=False,
        )
        cleared = self.client.post(
            f"/inventory/{key}",
            data={"csrf": csrf, "display_name": "", "category": "unknown"},
            follow_redirects=False,
        )
        self.assertEqual(cleared.status_code, 303)
        latest = self.store.device_settings()[-1]
        self.assertIsNone(latest["display_name"])
        self.assertIsNone(latest["category"])
        page = self.client.get("/inventory")
        self.assertIn("device-a", page.text)
        self.assertNotIn("(manual)", page.text)

    def test_device_names_are_escaped(self):
        self.login()
        key = "mac:aa:bb:cc:dd:ee:01"
        csrf = self.csrf()
        self.client.post(
            f"/inventory/{key}",
            data={"csrf": csrf, "display_name": '<img src=x onerror="alert(1)">', "category": "tv"},
            follow_redirects=False,
        )
        page = self.client.get("/inventory")
        self.assertNotIn('<img src=x onerror="alert(1)">', page.text)
        self.assertIn("&lt;img", page.text)


class AnalysisViewTests(WebTestCase):
    def preview_token(self, path: str) -> str:
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200, page.text)
        match = re.search(r'name="preview_token" value="([^"]+)"', page.text)
        self.assertIsNotNone(match, "preview page has no token")
        return match.group(1)

    def test_preview_is_local_and_makes_no_call(self):
        self.login()
        page = self.client.get("/analysis")
        self.assertIn("Optional gaming validation manifest", page.text)
        self.assertIn('"status": "not_ready"', page.text)
        self.assertIn('"search_per_analysis": 0', page.text)
        self.assertIn(
            '<button type="submit">Preview what would be sent</button>',
            page.text,
            "the local preview must never be gated on provider configuration",
        )
        response = self.client.get("/analysis/preview?preset=snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertIn("example.com", response.text)
        self.assertEqual(self.runner_calls, [])

    def test_coverage_page_is_local_and_lists_first_time_worklist(self):
        self.login()
        page = self.client.get("/analysis/coverage?preset=snapshot")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Research coverage and first-time worklist", page.text)
        self.assertIn("Distinct eligible names", page.text)
        # The seeded names are pending first-time research (no rules, no prior jobs).
        for name in ("www.example.com", "api.example.org", "cdn.example.net"):
            self.assertIn(name, page.text)
        # Nothing may dispatch and nothing may be selected from this page.
        self.assertEqual(self.runner_calls, [])
        self.assertNotIn("Confirm and start", page.text)

    def test_coverage_page_refuses_shared_control_without_data(self):
        shared = TestClient(
            create_app(
                auth=self.auth,
                config=WebConfig(
                    allowed_hosts=("testserver",),
                    public_url="http://testserver",
                    max_body_bytes=4096,
                    shared_control=True,
                ),
                reports=self.reports,
                inventory=self.inventory,
                analysis=self.analysis,
                runner=lambda *args: self.fail("Shared control must never dispatch AI"),
                ai={"enabled": False},
                timezone="UTC",
            )
        )
        self.addCleanup(shared.close)
        response = shared.get("/analysis/coverage?preset=snapshot")
        self.assertEqual(response.status_code, 403)

    def test_preview_accounts_for_reverse_lookups_as_local_exclusions(self):
        self.login()

        def row(row_id: int, domain: str) -> dict[str, object]:
            return {
                "id": row_id,
                "timestamp": BASE + 3700 + row_id,
                "type": 1,
                "status": 2,
                "domain": domain,
                "client": "192.168.1.1",
                "forward": "1.2.3.4#53",
                "additional_info": None,
                "list_id": 0,
                "reply_type": 5,
                "ede": None,
                "reply_time": 0.02,
                "dnssec": 0,
            }

        self.store.import_snapshot(
            {
                "schema_version": 2,
                "start_epoch": BASE + 3600,
                "end_epoch": BASE + 7200,
                "captured_utc": "2026-10-23T06:00:00Z",
                "retained_rows": 2,
                "oldest_epoch": float(BASE + 3600),
                "newest_epoch": float(BASE + 3700),
                "window_count": 2,
                "observations": [
                    row(1, "public.example.com"),
                    row(2, "4.3.2.1.in-addr.arpa"),
                ],
            },
            datasource="test-reverse",
        )
        page = self.client.get("/analysis/preview?preset=snapshot")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("public.example.com", page.text)
        self.assertIn("4.3.2.1.in-addr.arpa", page.text)
        self.assertIn("Excluded locally (1)", page.text)
        self.assertIn("reverse", page.text)
        self.assertEqual(self.runner_calls, [])

    def test_local_preview_survives_without_ai_but_confirmation_disappears(self):
        self.ai.update({"enabled": False, "provider": None, "model": None, "exa_enabled": False})
        client = TestClient(self.app())
        self.addCleanup(client.close)
        self.client = client
        self.login()
        page = self.client.get("/analysis")
        self.assertIn('<button type="submit">Preview what would be sent</button>', page.text)
        preview = self.client.get("/analysis/preview?preset=snapshot")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("example.com", preview.text)
        self.assertIn("Analysis is disabled until a provider is configured.", preview.text)
        self.assertNotIn('action="/analyses"', preview.text)
        self.assertEqual(self.runner_calls, [])

    def test_confirmation_starts_exactly_one_frozen_job(self):
        self.login()
        token = self.preview_token("/analysis/preview?preset=snapshot")
        csrf = self.csrf("/analysis/preview?preset=snapshot")
        data = {
            "csrf": csrf,
            "preview_token": token,
            "preset": "snapshot",
            "snapshot": "",
            "start": "",
            "end": "",
        }
        first = self.client.post("/analyses", data=data, follow_redirects=False)
        self.assertEqual(first.status_code, 303, first.text)
        self.assertEqual(len(self.runner_calls), 1)
        analysis_id, allow_resume = self.runner_calls[0]
        self.assertFalse(allow_resume)
        second = self.client.post("/analyses", data=data, follow_redirects=False)
        self.assertEqual(second.status_code, 303)
        self.assertEqual(len(self.runner_calls), 1, "a repeated POST must not start a second job")
        self.assertEqual(self.analysis.status(analysis_id)["state"], "queued")

    def test_stale_or_tampered_preview_is_rejected(self):
        self.login()
        csrf = self.csrf("/analysis/preview?preset=snapshot")
        response = self.client.post(
            "/analyses",
            data={
                "csrf": csrf,
                "preview_token": "0" * 64,
                "preset": "snapshot",
                "snapshot": "",
                "start": "",
                "end": "",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.runner_calls, [])

    def test_missing_csrf_blocks_a_start(self):
        self.login()
        token = self.preview_token("/analysis/preview?preset=snapshot")
        response = self.client.post(
            "/analyses",
            data={"preview_token": token, "preset": "snapshot"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.runner_calls, [])

    def test_polling_status_never_starts_work(self):
        self.login()
        analysis_id, _ = self.analysis.create(
            period_digest="d" * 64,
            selected_item_ids=["www.example.com"],
            candidates=[
                {
                    "item_id": "www.example.com",
                    "domain": "www.example.com",
                    "claim_scope": "service_and_provider",
                }
            ],
            provider="groq",
            model_id="test-model",
            config_fingerprint="fingerprint",
            policy_revision=1,
        )
        page = self.client.get(f"/analysis/{analysis_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("queued", page.text)
        payload = self.client.get(f"/api/analysis/{analysis_id}").json()
        self.assertEqual(payload["state"], "queued")
        self.assertEqual(self.runner_calls, [])

    def test_status_renders_sparse_unknown_result_without_requiring_service_fields(self):
        self.login()
        analysis_id, _ = self.analysis.create(
            period_digest="d" * 64,
            selected_item_ids=["example.com"],
            candidates=[{"item_id": "example.com", "domain": "example.com"}],
            provider="groq",
            model_id="test-model",
            config_fingerprint="fingerprint",
            policy_revision=1,
        )
        self.analysis.checkpoint(
            analysis_id,
            "example.com",
            outcome="unknown",
            result={
                "source": "model",
                "verification_state": "unknown",
                "role": "unknown",
                "unresolved_reason": "no public evidence retrieved",
                "supporting_spans": [
                    {
                        "source_id": "s1",
                        "source_url": "https://docs.example/unknown",
                        "source_sha256": "c" * 64,
                        "start": 0,
                        "end": 15,
                        "text": "reviewed excerpt",
                    }
                ],
            },
        )
        self.analysis.finish_with_summary(analysis_id, state="completed")
        page = self.client.get(f"/analysis/{analysis_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("unknown", page.text)
        self.assertIn("no public evidence retrieved", page.text)
        self.assertIn("reviewed excerpt", page.text)
        self.assertEqual(self.runner_calls, [])

    def test_disabled_ai_refuses_to_start(self):
        self.ai = dict(self.ai, enabled=False)
        self.client = TestClient(self.app())
        self.login()
        csrf = self.csrf("/analysis/preview?preset=snapshot")
        response = self.client.post(
            "/analyses",
            data={"csrf": csrf, "preview_token": "x", "preset": "snapshot"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.runner_calls, [])

    def test_reanalysis_uses_a_local_nonce(self):
        self.login()
        analysis_id, _ = self.analysis.create(
            period_digest="e" * 64,
            selected_item_ids=["www.example.com"],
            candidates=[
                {
                    "item_id": "www.example.com",
                    "domain": "www.example.com",
                    "claim_scope": "service_and_provider",
                }
            ],
            provider="groq",
            model_id="test-model",
            config_fingerprint="fingerprint",
            policy_revision=1,
        )
        self.analysis.finish(analysis_id, state="completed")
        page = self.client.get(f"/analysis/{analysis_id}")
        nonce = re.search(r'name="nonce" value="([^"]+)"', page.text).group(1)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        response = self.client.post(
            f"/analysis/{analysis_id}/reanalyze",
            data={"csrf": csrf, "nonce": nonce},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(self.runner_calls), 1)
        self.assertNotEqual(self.runner_calls[0][0], analysis_id)


if __name__ == "__main__":
    unittest.main()
