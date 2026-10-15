"""Start the cook VM only when Google has finished a run we have not published.

Cloud Scheduler calls this every 5 minutes. An empty check does not boot the VM.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PROJECT = "weathernext3-joros"
ZONE = "us-east1-b"
INSTANCE = "wn3-ens-cook"
MANIFEST = "https://raw.githubusercontent.com/ajoros/ai-weather-guy/gh-pages/manifest.json"
STATS_BUCKET = "weathernext3_statistics_spatial"
STATS_ROOT = "weathernext_3_0_0_statistics/zarr/2026_to_present"
ENS_BUCKET = "weathernext3_spatial"
ENS_ROOT = "weathernext_3_0_0/zarr/2026_to_present"


def _hour(iso: str) -> int:
    return int(iso[11:13])


def decide(
    hourly_init: str,
    synoptic_init: str,
    ensemble_init: str,
    stats_ready: list[str],
    ens_ready: list[str],
) -> str:
    """Why to boot, or '' when the published inits already cover every finished run."""
    reasons = []
    if stats_ready and max(stats_ready) > (hourly_init or ""):
        reasons.append(f"surface {max(stats_ready)}")
    syn = [s for s in stats_ready if _hour(s) % 6 == 0]
    if syn and max(syn) > (synoptic_init or ""):
        reasons.append(f"synoptic {max(syn)}")
    if ens_ready and max(ens_ready) > (ensemble_init or ""):
        reasons.append(f"ensemble {max(ens_ready)}")
    return ", ".join(reasons)


def _run_iso(stamp: datetime) -> str:
    return stamp.strftime("%Y-%m-%dT%H:00:00Z")


def _token() -> str:
    """The WeatherNext buckets allow the same user login the VM already uses."""
    raw = os.environ.get("WN3_ADC")
    if not raw:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp)["access_token"]
    info = json.loads(raw)
    data = urllib.parse.urlencode(
        {
            "client_id": info["client_id"],
            "client_secret": info["client_secret"],
            "refresh_token": info["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["access_token"]


def _get(url: str, token: str, timeout: int = 15) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": PROJECT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _success(token: str, bucket: str, folder: str) -> bool:
    name = urllib.parse.quote(f"{folder}/success", safe="")
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{name}?fields=name"
    code, body = _get(url, token, timeout=10)
    if code == 200:
        return True
    if code == 404:
        return False
    raise RuntimeError(f"{bucket} {code} {body[:120]!r}")


def _ready(token: str, bucket: str, root: str, stamps: list[datetime]) -> list[str]:
    found = []
    for stamp in stamps:
        folder = f"{root}/{stamp:%Y%m%d_%H}hr_01_preds"
        if _success(token, bucket, folder):
            found.append(_run_iso(stamp))
    return found


def _manifest() -> dict:
    req = urllib.request.Request(MANIFEST)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _instance_status(token: str) -> str:
    url = (
        "https://compute.googleapis.com/compute/v1/projects/"
        f"{PROJECT}/zones/{ZONE}/instances/{INSTANCE}"
    )
    code, body = _get(url, token)
    if code != 200:
        return ""
    return json.loads(body).get("status") or ""


def _start(token: str) -> int:
    url = (
        "https://compute.googleapis.com/compute/v1/projects/"
        f"{PROJECT}/zones/{ZONE}/instances/{INSTANCE}/start"
    )
    req = urllib.request.Request(
        url, data=b"{}", method="POST", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def watch(request):
    token = _token()
    status = _instance_status(token)
    if status in ("RUNNING", "STAGING", "PROVISIONING", "STOPPING"):
        body = json.dumps({"boot": False, "reason": status.lower()})
        print(body, flush=True)
        return (body, 200)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = [now - timedelta(hours=i) for i in range(8)]
    syn = now.replace(hour=(now.hour // 6) * 6)
    cycles = [syn - timedelta(hours=6 * i) for i in range(4)]
    try:
        stats_ready = _ready(token, STATS_BUCKET, STATS_ROOT, hours)
        ens_ready = _ready(token, ENS_BUCKET, ENS_ROOT, cycles)
        manifest = _manifest()
    except Exception as exc:
        body = json.dumps({"boot": False, "reason": f"check failed: {exc}"})
        print(body, flush=True)
        return (body, 200)
    reason = decide(
        manifest.get("hourly_init") or "",
        manifest.get("synoptic_init") or "",
        manifest.get("ensemble_init") or manifest.get("synoptic_init") or "",
        stats_ready,
        ens_ready,
    )
    if not reason:
        body = json.dumps({"boot": False, "reason": "current"})
    else:
        code = _start(token)
        body = json.dumps({"boot": code in (200, 409), "start": code, "reason": reason})
    print(body, flush=True)
    return (body, 200)


def _self_check() -> None:
    assert decide("2026-10-15T05:00:00Z", "2026-10-15T00:00:00Z", "2026-10-15T00:00:00Z", ["2026-10-15T06:00:00Z"], [])
    assert decide("2026-10-15T07:00:00Z", "2026-10-15T00:00:00Z", "2026-10-15T00:00:00Z", ["2026-10-15T06:00:00Z"], [])
    assert not decide(
        "2026-10-15T07:00:00Z",
        "2026-10-15T06:00:00Z",
        "2026-10-15T06:00:00Z",
        ["2026-10-15T06:00:00Z", "2026-10-15T07:00:00Z"],
        ["2026-10-15T06:00:00Z"],
    )
    assert decide(
        "2026-10-15T07:00:00Z",
        "2026-10-15T06:00:00Z",
        "2026-10-15T06:00:00Z",
        ["2026-10-15T07:00:00Z"],
        ["2026-10-15T12:00:00Z"],
    )
    print("watch decide ok")


if __name__ == "__main__":
    _self_check()
