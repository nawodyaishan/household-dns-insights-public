"""Inventory: observed devices, presence states, local edits and strict bindings.

Inventory reports what a poll *listed*. A successful poll that omits a device says
exactly that and nothing more: not "offline", not "asleep", not "no activity". A
failed poll is a monitoring gap. Presence states are poll-granular, wired clients may
simply not appear, and controller/repeater roles are infrastructure rather than
household endpoints.

DNS attribution is separate and deliberately strict: a row is attributed only through
an explicitly recorded, time-valid binding. The current poll's lease is never used to
explain older rows, and conflicting bindings leave rows unattributed.

No provider, MCP or web import belongs here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .storage import Store

MAX_POLL_BYTES = 4 * 1024 * 1024

LISTED = "listed"
NOT_LISTED = "not_listed_in_successful_poll"
GAP = "monitoring_gap"
UNOBSERVED = "unobserved"

ROLE_CONTROLLER = "CONTROLLER"

#: Observed router/dish management endpoints. Rows from these addresses are the
#: router itself forwarding household queries, never a household endpoint.
MANAGEMENT_IPS = frozenset({"192.168.1.1", "192.168.100.1"})

#: Manual categories describe reviewed hardware only; they never imply an OS.
DEVICE_CATEGORIES = (
    "unknown",
    "phone",
    "tablet",
    "computer",
    "tv",
    "console",
    "iot",
    "network_infrastructure",
    "other",
)

_IFACE_LABELS = {
    "ETH": "wired",
    "RF_2GHZ": "wireless 2.4 GHz",
    "RF_5GHZ": "wireless 5 GHz",
}


class InventoryError(ValueError):
    """A poll, edit or binding is not usable as inventory evidence."""


def _parse_time(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"{field_name} is missing or not a timestamp")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise InventoryError(f"{field_name} is not a valid ISO timestamp") from error
    if parsed.tzinfo is None:
        raise InventoryError(f"{field_name} has no timezone")
    return parsed.astimezone(UTC)


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _opt_str(client: Mapping[str, object], key: str) -> str | None:
    value = client.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(client: Mapping[str, object], key: str) -> int | None:
    value = client.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InventoryError(f"{key} is not numeric")
    return int(value)


def _opt_bool(client: Mapping[str, object], key: str) -> bool | None:
    """Proto3 omits false booleans, so an absent flag is unknown, not false."""
    value = client.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise InventoryError(f"{key} is not a boolean")
    return value


def mac_warnings(mac: str | None) -> list[str]:
    """Flag addresses that cannot be trusted as a stable device identity."""
    if mac is None:
        return ["no MAC address reported"]
    compact = mac.replace(":", "").replace("-", "").strip().lower()
    if len(compact) != 12 or any(char not in "0123456789abcdef" for char in compact):
        return ["MAC address is malformed"]
    if compact == "0" * 12:
        return ["MAC address is all zeros"]
    first_octet = int(compact[:2], 16)
    warnings = []
    if first_octet & 0x01:
        warnings.append("MAC is multicast; not a device address")
    if first_octet & 0x02:
        warnings.append("locally administered MAC; likely randomized per network or boot")
    return warnings


@dataclass(frozen=True, slots=True)
class DeviceObservation:
    """One client entry exactly as a single poll listed it."""

    device_key: str
    role: str
    iface: str | None
    iface_name: str | None
    name: str | None
    given_name: str | None
    ip_address: str | None
    mac_address: str | None
    device_id: str | None
    client_id: str | None
    upstream_mac_address: str | None
    hops_from_controller: int | None
    signal_strength: int | None
    snr: int | None
    associated_time_s: int | None
    active: bool | None
    dhcp_lease_found: bool | None
    dhcp_lease_active: bool | None
    lease_expires_s: int | None
    download_mb: int | None
    upload_mb: int | None
    warnings: tuple[str, ...] = ()
    raw: Mapping[str, object] = field(default_factory=dict, compare=False)

    @property
    def label(self) -> str | None:
        return self.given_name or self.name

    @property
    def iface_label(self) -> str | None:
        if self.iface is None:
            return None
        return _IFACE_LABELS.get(self.iface, self.iface)

    @property
    def is_infrastructure(self) -> bool:
        return self.role == ROLE_CONTROLLER


def device_key(client: Mapping[str, object]) -> str:
    """Stable local identity: MAC first, then client id, then network address."""
    mac = _opt_str(client, "macAddress")
    if mac:
        return f"mac:{mac.replace('-', ':').lower()}"
    client_id = _opt_str(client, "clientId")
    if client_id:
        return f"client:{client_id}"
    ip = _opt_str(client, "ipAddress")
    if ip:
        return f"ip:{ip}"
    name = _opt_str(client, "name") or _opt_str(client, "givenName")
    if name:
        return f"name:{name.lower()}"
    encoded = json.dumps(client, sort_keys=True, separators=(",", ":")).encode()
    return "hash:" + hashlib.sha256(encoded).hexdigest()[:16]


def normalize_client(client: Mapping[str, object]) -> DeviceObservation:
    """Normalize one ProtoJSON client, preserving every original field in ``raw``."""
    if not isinstance(client, Mapping):
        raise InventoryError("A client entry must be an object")
    mac = _opt_str(client, "macAddress")
    role = _opt_str(client, "role") or "UNKNOWN"
    warnings = mac_warnings(mac)
    if role == "UNKNOWN":
        warnings.append("role was not reported; treating it as a non-controller client")
    return DeviceObservation(
        device_key=device_key(client),
        role=role,
        iface=_opt_str(client, "iface"),
        iface_name=_opt_str(client, "ifaceName"),
        name=_opt_str(client, "name"),
        given_name=_opt_str(client, "givenName"),
        ip_address=_opt_str(client, "ipAddress"),
        mac_address=mac,
        device_id=_opt_str(client, "deviceId"),
        client_id=_opt_str(client, "clientId"),
        upstream_mac_address=_opt_str(client, "upstreamMacAddress"),
        hops_from_controller=_opt_int(client, "hopsFromController"),
        signal_strength=_opt_int(client, "signalStrength"),
        snr=_opt_int(client, "snr"),
        associated_time_s=_opt_int(client, "associatedTimeS"),
        active=_opt_bool(client, "active"),
        dhcp_lease_found=_opt_bool(client, "dhcpLeaseFound"),
        dhcp_lease_active=_opt_bool(client, "dhcpLeaseActive"),
        lease_expires_s=_opt_int(client, "secondsUntilDhcpLeaseExpires"),
        download_mb=_opt_int(client, "downloadMb"),
        upload_mb=_opt_int(client, "uploadMb"),
        warnings=tuple(warnings),
        raw=dict(client),
    )


@dataclass(frozen=True, slots=True)
class Poll:
    """One normalized presence poll: success, failure or malformed response."""

    source: str
    polled_utc: str
    ok: bool
    error: str | None
    observations: tuple[DeviceObservation, ...]
    digest: str
    duration_ms: int | None = None


def parse_poll(payload: Mapping[str, object], *, source: str) -> Poll:
    """Parse a stored poll envelope or a bare ``wifiGetClients`` response."""
    if not isinstance(payload, Mapping):
        raise InventoryError("Poll payload must be an object")
    if "stdout" in payload or "returncode" in payload:
        started = _parse_time(payload.get("start"), field_name="poll start")
        ended = _parse_time(payload.get("end"), field_name="poll end")
        if ended < started:
            raise InventoryError("Poll end precedes its start")
        returncode = payload.get("returncode")
        if not isinstance(returncode, int):
            raise InventoryError("Poll returncode is missing")
        stdout = payload.get("stdout")
        if returncode != 0:
            digest = hashlib.sha256(
                json.dumps(
                    {"polled_utc": utc_iso(started), "returncode": returncode},
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            return Poll(
                source=source,
                polled_utc=utc_iso(started),
                ok=False,
                error=f"collector exited with code {returncode}",
                observations=(),
                digest=digest,
                duration_ms=int((ended - started).total_seconds() * 1000),
            )
        if not isinstance(stdout, str) or not stdout.strip():
            raise InventoryError("Successful poll has no response body")
        try:
            body = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise InventoryError("Poll response body is not JSON") from error
        duration_ms = int((ended - started).total_seconds() * 1000)
    else:
        body = payload
        started = None
        duration_ms = None

    if not isinstance(body, Mapping):
        raise InventoryError("Poll response body must be an object")
    wifi = body.get("wifiGetClients")
    if not isinstance(wifi, Mapping):
        raise InventoryError("Poll response has no wifiGetClients object")
    clients = wifi.get("clients", [])
    if not isinstance(clients, list):
        raise InventoryError("wifiGetClients.clients must be a list")
    observations = tuple(normalize_client(client) for client in clients)
    keys = [observation.device_key for observation in observations]
    if len(set(keys)) != len(keys):
        raise InventoryError("Poll lists the same device key more than once")

    if started is None:
        polled_raw = body.get("polled_utc")
        started = _parse_time(polled_raw, field_name="polled_utc")
    digest = hashlib.sha256(
        json.dumps(
            {
                "polled_utc": utc_iso(started),
                "clients": [dict(observation.raw) for observation in observations],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return Poll(
        source=source,
        polled_utc=utc_iso(started),
        ok=True,
        error=None,
        observations=observations,
        digest=digest,
        duration_ms=duration_ms,
    )


def load_poll(path: str | Path) -> Poll:
    """Read one owner-provided poll file; never fetch anything."""
    location = Path(path)
    try:
        size = location.stat().st_size
    except FileNotFoundError as error:
        raise InventoryError(f"Poll file is missing: {location.name}") from error
    if size > MAX_POLL_BYTES:
        raise InventoryError(f"Poll file exceeds {MAX_POLL_BYTES} bytes")
    try:
        payload = json.loads(location.read_text())
    except json.JSONDecodeError as error:
        raise InventoryError(f"Poll file is not JSON: {location.name}") from error
    return parse_poll(payload, source=location.name)


# -- presence ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PresenceSegment:
    """One poll-granular observation state lasting until the next poll."""

    state: str
    start_utc: str
    end_utc: str | None
    polls: int

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "polls": self.polls,
        }


def _observation_key(observation: DeviceObservation | Mapping[str, object]) -> str:
    if isinstance(observation, Mapping):
        return str(observation["device_key"])
    return observation.device_key


def _field(
    observation: DeviceObservation | Mapping[str, object],
    name: str,
    default: object = None,
) -> object:
    if isinstance(observation, Mapping):
        return observation.get(name, default)
    return getattr(observation, name, default)


def _segment_states(
    polls: Sequence[Mapping[str, object]], key: str | None
) -> list[PresenceSegment]:
    segments: list[PresenceSegment] = []
    for index, poll in enumerate(polls):
        end = polls[index + 1]["polled_utc"] if index + 1 < len(polls) else None
        if not poll.get("ok"):
            state = GAP
        else:
            keys = {_observation_key(item) for item in poll.get("observations") or ()}
            state = LISTED if key in keys else NOT_LISTED
        if segments and segments[-1].state == state:
            previous = segments.pop()
            segments.append(
                PresenceSegment(
                    state=state,
                    start_utc=previous.start_utc,
                    end_utc=end,
                    polls=previous.polls + 1,
                )
            )
        else:
            segments.append(
                PresenceSegment(
                    state=state,
                    start_utc=str(poll["polled_utc"]),
                    end_utc=end,
                    polls=1,
                )
            )
    return segments


def _poll_bounds(polls: Sequence[Mapping[str, object]]) -> dict[str, object]:
    intervals = []
    for current, following in zip(polls, polls[1:], strict=False):
        start = _parse_time(current["polled_utc"], field_name="poll time")
        end = _parse_time(following["polled_utc"], field_name="poll time")
        intervals.append((end - start).total_seconds())
    ordered = sorted(intervals)
    median = ordered[len(ordered) // 2] if ordered else None
    return {
        "total": len(polls),
        "successful": sum(1 for poll in polls if poll.get("ok")),
        "failed": sum(1 for poll in polls if not poll.get("ok")),
        "first_utc": polls[0]["polled_utc"] if polls else None,
        "last_utc": polls[-1]["polled_utc"] if polls else None,
        "median_interval_s": median,
        "max_interval_s": max(ordered) if ordered else None,
    }


def presence_timeline(polls: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Build device presence views and explicit gaps from stored polls.

    ``polls`` are store-shaped: ``polled_utc``, ``ok`` and normalized ``observations``
    (each a :class:`DeviceObservation` or a mapping with ``device_key`` and friends).
    """
    ordered = sorted(polls, key=lambda poll: str(poll["polled_utc"]))
    successful = [poll for poll in ordered if poll.get("ok")]
    devices: dict[str, dict[str, object]] = {}
    infrastructure: dict[str, dict[str, object]] = {}

    for poll in successful:
        for observation in poll.get("observations") or ():
            view = _device_view(devices, infrastructure, observation)
            view["listed_polls"] += 1
            view["last_listed_utc"] = poll["polled_utc"]
            if view["first_listed_utc"] is None:
                view["first_listed_utc"] = poll["polled_utc"]
            address = _field(observation, "ip_address")
            if address and address not in view["ip_addresses"]:
                view["ip_addresses"].append(address)
            label = _field(observation, "label")
            if label:
                view["label"] = label
            for warning in _field(observation, "warnings", ()) or ():
                if warning not in view["warnings"]:
                    view["warnings"].append(warning)

    for key, view in {**devices, **infrastructure}.items():
        segments = _segment_states(ordered, key)
        view["segments"] = [segment.as_dict() for segment in segments]
        view["state"] = segments[-1].state if segments else UNOBSERVED
        view["counts"] = {
            "listed": sum(segment.polls for segment in segments if segment.state == LISTED),
            "not_listed": sum(segment.polls for segment in segments if segment.state == NOT_LISTED),
            "monitoring_gap": sum(segment.polls for segment in segments if segment.state == GAP),
        }
        view["vision_note"] = (
            "Presence states come from individual polls; not-listed never proves offline."
        )

    gaps = [
        {
            "start_utc": poll["polled_utc"],
            "end_utc": (ordered[index + 1]["polled_utc"] if index + 1 < len(ordered) else None),
            "reason": poll.get("error") or "poll failed",
        }
        for index, poll in enumerate(ordered)
        if not poll.get("ok")
    ]

    return {
        "polls": _poll_bounds(ordered),
        "devices": sorted(
            devices.values(),
            key=lambda view: (str(view.get("label") or view["device_key"])).lower(),
        ),
        "infrastructure": sorted(infrastructure.values(), key=lambda view: str(view["device_key"])),
        "gaps": gaps,
        "notes": [
            "A successful poll that omits a device is a listing gap, not proof of "
            "disconnection, sleep or inactivity.",
            "Poll failure or absence is reported as a monitoring gap; no state is "
            "invented for that interval.",
            "Wired clients may be absent from the Wi-Fi client listing entirely; "
            "omission proves nothing about the device.",
            "Presence is network association only: not OS uptime, human presence or "
            "application activity.",
        ],
    }


def _device_view(
    devices: dict[str, dict[str, object]],
    infrastructure: dict[str, dict[str, object]],
    observation: DeviceObservation | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(observation, Mapping):
        # Store-shaped reconstruction (used when re-reading persisted polls).
        key = str(observation["device_key"])
        role = str(observation.get("role", "UNKNOWN"))
        iface = observation.get("iface")
        label = observation.get("label")
        mac = observation.get("mac_address")
        ips = [str(observation["ip_address"])] if observation.get("ip_address") else []
        warnings = list(observation.get("warnings") or ())
    else:
        key = observation.device_key
        role = observation.role
        iface = observation.iface
        label = observation.label
        mac = observation.mac_address
        ips = [observation.ip_address] if observation.ip_address else []
        warnings = list(observation.warnings)
    bucket = infrastructure if role == ROLE_CONTROLLER else devices
    if key in bucket:
        return bucket[key]
    view: dict[str, object] = {
        "device_key": key,
        "role": role,
        "iface": iface,
        "iface_label": _IFACE_LABELS.get(iface or "", iface),
        "label": label,
        "mac_address": mac,
        "ip_addresses": ips,
        "first_listed_utc": None,
        "last_listed_utc": None,
        "listed_polls": 0,
        "warnings": warnings,
        "segments": [],
        "state": UNOBSERVED,
        "counts": {},
    }
    bucket[key] = view
    return view


# -- manual overrides -------------------------------------------------------


def latest_manual_settings(
    revisions: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    """Resolve the supersede chain per device; ignore stale branches.

    A revision with ``supersedes`` set applies only if that pointer names the current
    revision for the device. Anything else is preserved in history but not applied.
    """
    ordered = sorted(revisions, key=lambda revision: int(revision["revision_id"]))
    current: dict[str, dict[str, object]] = {}
    for revision in ordered:
        key = str(revision["device_key"])
        supersedes = revision.get("supersedes")
        previous = current.get(key)
        if supersedes is None:
            if previous is not None:
                continue
            current[key] = dict(revision)
        elif previous is not None and int(previous["revision_id"]) == int(supersedes):
            current[key] = dict(revision)
    return current


def validate_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    name = " ".join(value.split())
    if not name:
        return None
    if len(name) > 64:
        raise InventoryError("Display name must be at most 64 characters")
    if any(char in name for char in "\r\n\t"):
        raise InventoryError("Display name must be a single line")
    return name


def validate_category(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    category = value.strip().lower()
    if category not in DEVICE_CATEGORIES:
        raise InventoryError(f"Unknown device category: {category}")
    return category


def apply_manual_settings(
    view: Mapping[str, object], settings: Mapping[str, object] | None
) -> dict[str, object]:
    """Overlay manual display fields; the observed label is never overwritten."""
    observed = view.get("label")
    display = settings.get("display_name") if settings else None
    category = settings.get("category") if settings else None
    enriched = dict(view)
    enriched["observed_label"] = observed
    enriched["display_name"] = display or observed or str(view["device_key"])
    enriched["category"] = category or "unknown"
    enriched["category_source"] = "manual" if category else "unset"
    enriched["revision_id"] = settings.get("revision_id") if settings else None
    return enriched


# -- attribution ------------------------------------------------------------


def resolve_attribution(
    rows: Sequence[Mapping[str, object]],
    bindings: Sequence[Mapping[str, object]],
    *,
    management_ips: Iterable[str] = MANAGEMENT_IPS,
) -> dict[object, str]:
    """Attribute rows only through exact, unambiguous, time-valid IP bindings.

    Rules, all required:

    * the binding's ``observed_ip`` equals the row's client address exactly;
    * the row timestamp falls inside ``[valid_from_utc, valid_to_utc)``;
    * exactly one distinct device key matches at that instant;
    * the address is not a router/dish management endpoint.

    MAC-only bindings never match an IP row, and a binding cannot explain rows from
    before it was recorded. Zero matches leaves the row explicitly unattributed.
    """
    management = frozenset(management_ips)
    parsed: list[dict[str, object]] = []
    for binding in bindings:
        start = _parse_time(binding["valid_from_utc"], field_name="binding start")
        raw_end = binding.get("valid_to_utc")
        end = None if raw_end is None else _parse_time(raw_end, field_name="binding end")
        if end is not None and end <= start:
            raise InventoryError("Binding end must be after its start")
        ip = binding.get("observed_ip")
        parsed.append(
            {
                "device_key": str(binding["device_key"]),
                "ip": None if ip is None else str(ip),
                "start": start,
                "end": end,
            }
        )

    attributions: dict[object, str] = {}
    for row in rows:
        client = str(row["client"])
        if client in management:
            continue
        moment = datetime.fromtimestamp(float(row["timestamp"]), tz=UTC)
        matches = {
            item["device_key"]
            for item in parsed
            if item["ip"] == client
            and item["start"] <= moment
            and (item["end"] is None or moment < item["end"])
        }
        if len(matches) == 1:
            attributions[row["id"]] = matches.pop()
    return attributions


def attribution_conflicts(bindings: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Report overlapping bindings for the same address with different devices."""
    parsed: list[tuple[str, datetime, datetime | None, str, object]] = []
    for binding in bindings:
        ip = binding.get("observed_ip")
        if not ip:
            continue
        parsed.append(
            (
                str(ip),
                _parse_time(binding["valid_from_utc"], field_name="binding start"),
                None
                if binding.get("valid_to_utc") is None
                else _parse_time(binding["valid_to_utc"], field_name="binding end"),
                str(binding["device_key"]),
                binding.get("binding_id"),
            )
        )
    conflicts = []
    for index, (ip, start, end, key, binding_id) in enumerate(parsed):
        for other_ip, other_start, other_end, other_key, other_id in parsed[index + 1 :]:
            if ip != other_ip or key == other_key:
                continue
            if (end is None or other_start < end) and (other_end is None or start < other_end):
                conflicts.append(
                    {
                        "ip": ip,
                        "first_binding": binding_id,
                        "second_binding": other_id,
                        "reason": "overlapping bindings name different devices",
                    }
                )
    return conflicts


# -- service ----------------------------------------------------------------


class InventoryService:
    """Store-backed inventory reads and the only local manual-edit path."""

    def __init__(self, store: Store, *, management_ips: Iterable[str] = MANAGEMENT_IPS) -> None:
        self._store = store
        self._management_ips = frozenset(management_ips)

    def import_poll_file(self, path: str | Path) -> dict[str, object]:
        poll = load_poll(path)
        poll_id, inserted = self._store.add_inventory_poll(
            polled_utc=poll.polled_utc,
            source=poll.source,
            ok=poll.ok,
            error=poll.error,
            clients=None
            if not poll.ok
            else [
                {
                    **dict(observation.raw),
                    "device_key": observation.device_key,
                    "warnings": list(observation.warnings),
                }
                for observation in poll.observations
            ],
            digest=poll.digest,
        )
        return {
            "poll_id": poll_id,
            "inserted": inserted,
            "polled_utc": poll.polled_utc,
            "ok": poll.ok,
            "clients": len(poll.observations),
            "source": poll.source,
        }

    def import_poll_files(self, paths: Iterable[str | Path]) -> list[dict[str, object]]:
        return [self.import_poll_file(path) for path in paths]

    def polls(self, *, limit: int | None = None) -> list[dict[str, object]]:
        stored = self._store.inventory_polls(limit=limit)
        for poll in stored:
            poll["observations"] = [
                normalize_client(client) for client in (poll.pop("clients") or ())
            ]
        return stored

    def devices(self) -> dict[str, object]:
        """Presence view plus manual overrides; controller entries stay separate."""
        timeline = presence_timeline(self.polls())
        settings = latest_manual_settings(self._store.device_settings())
        for collection in ("devices", "infrastructure"):
            timeline[collection] = [
                apply_manual_settings(view, settings.get(str(view["device_key"])))
                for view in timeline[collection]
            ]
        timeline["generated_utc"] = utc_iso(datetime.now(UTC))
        timeline["categories"] = list(DEVICE_CATEGORIES)
        timeline["bindings"] = attribution_conflicts(self._store.device_bindings())
        return timeline

    def edit_device(
        self,
        device_key: str,
        *,
        display_name: str | None,
        category: str | None,
    ) -> dict[str, object]:
        if not device_key or len(device_key) > 200:
            raise InventoryError("A device key is required")
        known = {
            str(view["device_key"])
            for view in (*self.devices()["devices"], *self.devices()["infrastructure"])
        }
        if device_key not in known:
            raise InventoryError("Unknown device key; refresh the inventory view")
        current = latest_manual_settings(self._store.device_settings()).get(device_key)
        cleaned_name = validate_display_name(display_name)
        cleaned_category = validate_category(category)
        revision_id = self._store.add_device_setting(
            device_key=device_key,
            display_name=cleaned_name,
            category=cleaned_category,
            supersedes=None if current is None else int(current["revision_id"]),
        )
        return {"device_key": device_key, "revision_id": revision_id}

    def attributions(self, rows: Sequence[Mapping[str, object]]) -> dict[int, str]:
        return resolve_attribution(
            rows, self._store.device_bindings(), management_ips=self._management_ips
        )


__all__ = [
    "DEVICE_CATEGORIES",
    "GAP",
    "LISTED",
    "MANAGEMENT_IPS",
    "NOT_LISTED",
    "ROLE_CONTROLLER",
    "UNOBSERVED",
    "DeviceObservation",
    "InventoryError",
    "InventoryService",
    "Poll",
    "PresenceSegment",
    "apply_manual_settings",
    "attribution_conflicts",
    "device_key",
    "latest_manual_settings",
    "load_poll",
    "mac_warnings",
    "normalize_client",
    "parse_poll",
    "presence_timeline",
    "resolve_attribution",
    "validate_category",
    "validate_display_name",
]
