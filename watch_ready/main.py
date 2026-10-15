"""Start the cook VM only when Google has finished a run we have not published.

Cloud Scheduler calls this every 5 minutes. An empty check does not boot the VM.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PROJECT = "weathernext3-joros"
ZONE = "us-east1-b"
INSTANCE = "wn3-ens-cook"
LOG_BUCKET = "weathernext3-joros-watch"
LOG_OBJECT = "watch.log"
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
    syn_ready: list[str],
    ens_ready: list[str],
) -> str:
    """Why to boot, or '' when the published inits already cover every finished run."""
    reasons = []
    if stats_ready and max(stats_ready) > (hourly_init or ""):
        reasons.append(f"surface {max(stats_ready)}")
    syn = [s for s in syn_ready if _hour(s) % 6 == 0]
    if syn and max(syn) > (synoptic_init or ""):
        reasons.append(f"synoptic {max(syn)}")
    if ens_ready and max(ens_ready) > (ensemble_init or ""):
        reasons.append(f"ensemble {max(ens_ready)}")
    return ", ".join(reasons)


def _newest(ready: list[str]) -> str:
    return max(ready) if ready else "none"


def _six(ready: list[str], published: str, label: str) -> str:
    got = _newest(ready)
    if got == "none":
        return f"{label} none"
    if got > (published or ""):
        return f"{label} {got} new"
    return f"{label} {got} already on page"


def check_line(
    when: str,
    stats_ready: list[str],
    syn_ready: list[str],
    ens_ready: list[str],
    hourly_init: str,
    synoptic_init: str,
    ensemble_init: str,
    action: str,
) -> str:
    return (
        f"{when} check  google {_six(stats_ready, hourly_init, 'surface')}, "
        f"{_six(syn_ready, synoptic_init, 'synoptic')}, "
        f"{_six(ens_ready, ensemble_init, 'ensemble')} | "
        f"page hourly {hourly_init or 'none'}, synoptic {synoptic_init or 'none'}, "
        f"ensemble {ensemble_init or 'none'} | {action}"
    )


def _run_iso(stamp: datetime) -> str:
    return stamp.strftime("%Y-%m-%dT%H:00:00Z")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _adc_raw() -> str:
    raw = os.environ.get("WN3_ADC") or ""
    if raw:
        return raw
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or ""
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    return ""


def _token() -> str:
    """The WeatherNext buckets allow the same user login the VM already uses."""
    raw = _adc_raw()
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


def _log_text(token: str) -> tuple[str, str]:
    name = urllib.parse.quote(LOG_OBJECT, safe="")
    meta = f"https://storage.googleapis.com/storage/v1/b/{LOG_BUCKET}/o/{name}?fields=generation"
    code, body = _get(meta, token)
    if code == 404:
        return "", "0"
    if code != 200:
        raise RuntimeError(f"log {code} {body[:120]!r}")
    generation = str(json.loads(body).get("generation") or "0")
    media = f"https://storage.googleapis.com/storage/v1/b/{LOG_BUCKET}/o/{name}?alt=media"
    code, raw = _get(media, token)
    text = raw.decode("utf-8", "replace") if code == 200 else ""
    return text, generation


def append_log(token: str, line: str) -> None:
    """Keep the last 400 lines. One lost line on a clash is fine; the next check rewrites it."""
    name = urllib.parse.quote(LOG_OBJECT, safe="")
    text, generation = _log_text(token)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    lines.append(line)
    payload = ("\n".join(lines[-400:]) + "\n").encode()
    url = (
        "https://storage.googleapis.com/upload/storage/v1/b/"
        f"{LOG_BUCKET}/o?uploadType=media&name={name}&ifGenerationMatch={generation}"
    )
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain; charset=utf-8",
            "x-goog-user-project": PROJECT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 412:
            raise
        text, generation = _log_text(token)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        lines.append(line)
        payload = ("\n".join(lines[-400:]) + "\n").encode()
        url = (
            "https://storage.googleapis.com/upload/storage/v1/b/"
            f"{LOG_BUCKET}/o?uploadType=media&name={name}&ifGenerationMatch={generation}"
        )
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/plain; charset=utf-8",
                "x-goog-user-project": PROJECT,
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()


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


def _record(token: str, line: str) -> None:
    print(line, flush=True)
    try:
        append_log(token, line)
    except Exception as exc:
        print(f"watch log failed: {exc}", flush=True)


def watch(request):
    token = _token()
    when = _now()
    try:
        status = _instance_status(token)
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        hours = [now - timedelta(hours=i) for i in range(18)]
        syn = now.replace(hour=(now.hour // 6) * 6)
        cycles = [syn - timedelta(hours=6 * i) for i in range(4)]
        stats_ready = _ready(token, STATS_BUCKET, STATS_ROOT, hours)
        syn_ready = _ready(token, STATS_BUCKET, STATS_ROOT, cycles)
        ens_ready = _ready(token, ENS_BUCKET, ENS_ROOT, cycles)
        manifest = _manifest()
        hourly = manifest.get("hourly_init") or ""
        synoptic = manifest.get("synoptic_init") or ""
        ensemble = manifest.get("ensemble_init") or synoptic
        reason = decide(hourly, synoptic, ensemble, stats_ready, syn_ready, ens_ready)
        if status in ("RUNNING", "STAGING", "PROVISIONING", "STOPPING"):
            action = f"vm {status.lower()}, cook already going"
            boot = False
        elif not reason:
            action = "no cook"
            boot = False
        else:
            code = _start(token)
            boot = code in (200, 409)
            action = f"cook started ({reason})" if boot else f"start failed {code} ({reason})"
        line = check_line(when, stats_ready, syn_ready, ens_ready, hourly, synoptic, ensemble, action)
        _record(token, line)
        return (json.dumps({"boot": boot, "reason": action}), 200)
    except Exception as exc:
        line = f"{when} check  failed: {exc}"
        _record(token, line)
        return (json.dumps({"boot": False, "reason": f"check failed: {exc}"}), 200)


def _self_check() -> None:
    assert decide(
        "2026-10-15T05:00:00Z", "2026-10-15T00:00:00Z", "2026-10-15T00:00:00Z",
        ["2026-10-15T06:00:00Z"], ["2026-10-15T06:00:00Z"], [],
    )
    assert decide(
        "2026-10-15T07:00:00Z", "2026-10-15T00:00:00Z", "2026-10-15T00:00:00Z",
        ["2026-10-15T06:00:00Z"], ["2026-10-15T06:00:00Z"], [],
    )
    assert not decide(
        "2026-10-15T07:00:00Z", "2026-10-15T06:00:00Z", "2026-10-15T06:00:00Z",
        ["2026-10-15T06:00:00Z", "2026-10-15T07:00:00Z"],
        ["2026-10-15T06:00:00Z"],
        ["2026-10-15T06:00:00Z"],
    )
    assert decide(
        "2026-10-15T07:00:00Z", "2026-10-15T06:00:00Z", "2026-10-15T06:00:00Z",
        ["2026-10-15T07:00:00Z"], ["2026-10-15T06:00:00Z"], ["2026-10-15T12:00:00Z"],
    )
    # A 6-hourly run already on the page does not boot again.
    assert not decide(
        "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z",
        ["2026-10-15T12:00:00Z"], ["2026-10-15T12:00:00Z"], ["2026-10-15T12:00:00Z"],
    )
    same = check_line(
        "2026-10-15T18:00:00Z",
        ["2026-10-15T12:00:00Z"], ["2026-10-15T12:00:00Z"], ["2026-10-15T12:00:00Z"],
        "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z",
        "no cook",
    )
    assert "already on page" in same and "no cook" in same
    new = check_line(
        "2026-10-15T19:00:00Z",
        ["2026-10-15T12:00:00Z"], ["2026-10-15T12:00:00Z"], ["2026-10-15T18:00:00Z"],
        "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z",
        "cook started (ensemble 2026-10-15T18:00:00Z)",
    )
    assert "ensemble 2026-10-15T18:00:00Z new" in new
    assert "synoptic 2026-10-15T12:00:00Z already on page" in new
    print("watch decide ok")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--note":
        append_log(_token(), f"{_now()} cook   {' '.join(sys.argv[2:])}")
    elif len(sys.argv) == 3 and sys.argv[1] == "--dump":
        text, _gen = _log_text(_token())
        with open(sys.argv[2], "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        _self_check()
