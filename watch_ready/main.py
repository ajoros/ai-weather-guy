"""Start the cook VM only when Google has finished a run we have not published.

Cloud Scheduler calls this every 5 minutes. An empty check does not boot the VM.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PROJECT = "weathernext3-joros"
ZONE = "us-east1-b"
INSTANCE = "wn3-ens-cook"
LOG_BUCKET = "weathernext3-joros-watch"
LOG_OBJECT = "watch.log"
REPO = "ajoros/ai-weather-guy"
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
    return max(ready) if ready else ""


def _run_label(iso: str) -> str:
    if not iso:
        return "—"
    return f"{int(iso[8:10])} Oct {iso[11:13]}Z"


def _clock(when: str) -> str:
    dt = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%b %-d, %-I:%M:%S %p PT")


def _block_time(block: str, now: datetime) -> datetime | None:
    first = block.splitlines()[0].strip()
    match = re.match(
        r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), "
        r"(\d{1,2}):(\d{2})(?::(\d{2}))? (AM|PM) PT$",
        first,
    )
    if not match:
        return None
    month = datetime.strptime(match.group(1), "%b").month
    hour = int(match.group(3)) % 12
    if match.group(6) == "PM":
        hour += 12
    second = int(match.group(5) or 0)
    pt = now.astimezone(ZoneInfo("America/Los_Angeles"))
    when = datetime(
        pt.year, month, int(match.group(2)), hour, int(match.group(4)), second,
        tzinfo=ZoneInfo("America/Los_Angeles"),
    )
    if when - now > timedelta(days=2):
        when = when.replace(year=pt.year - 1)
    return when


def _recent(blocks: list[str], now: datetime) -> list[str]:
    """Newest first, and only the last 12 hours."""
    cutoff = now - timedelta(hours=12)
    ranked = []
    for i, block in enumerate(blocks):
        when = _block_time(block, now)
        if when is not None and when < cutoff:
            continue
        stamp = when or datetime.min.replace(tzinfo=timezone.utc)
        ranked.append((stamp, -i, block))
    ranked.sort(reverse=True)
    return [block for _stamp, _i, block in ranked]


def _cell(label: str, iso: str, mark: str = "") -> str:
    text = f"{label} {_run_label(iso)}"
    if mark:
        text += f" {mark}"
    return text.ljust(26)


def _row(label: str, rest: str) -> str:
    return f"  {label:<14}{rest.rstrip()}"


def _field(ready: list[str], published: str) -> tuple[str, str]:
    got = _newest(ready)
    mark = "new" if got and got > (published or "") else ""
    return got, mark


def _action(action: str) -> str:
    action = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:00:00Z", lambda m: _run_label(m.group(0)), action)
    action = action.replace("synoptic ", "6-hour ").replace("ensemble ", "upper air ")
    if action == "no cook":
        return "no cook"
    if action.startswith("cook started (") and action.endswith(")"):
        return "started a cook: " + action[len("cook started ("):-1]
    if "cook already going" in action:
        return "cook already running"
    return action


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
    fields = (
        ("surface", stats_ready, hourly_init),
        ("6-hour", syn_ready, synoptic_init),
        ("upper air", ens_ready, ensemble_init),
    )
    google = []
    page = []
    for label, ready, published in fields:
        got, mark = _field(ready, published)
        google.append(_cell(label, got, mark))
        page.append(_cell(label, published))
    return "\n".join([
        _clock(when),
        _row("Google", "".join(google)),
        _row("Page", "".join(page)),
        _row("Result", _action(action)),
    ])


def note_block(when: str, text: str) -> str:
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:00:00Z", lambda m: _run_label(m.group(0)), text)
    text = text.replace("surface hourly ", "surface ")
    text = text.replace("synoptic ", "6-hour ")
    text = text.replace("ensemble ", "upper air ")
    text = text.replace("COOK_STATUS=updated", "drew new maps")
    text = text.replace("COOK_STATUS=noop", "already drawn")
    text = text.replace(" already on page", " already on the page")
    text = re.sub(r"\s+", " ", text).strip()
    return "\n".join([_clock(when), _row("Cook", text)])


def _legacy_block(line: str) -> str:
    cook = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) cook\s+(.*)$", line.strip())
    if cook:
        return note_block(cook.group(1), cook.group(2))
    check = re.match(
        r"^(?P<when>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) check  google surface (?P<gs>.+?), "
        r"synoptic (?P<gy>.+?), ensemble (?P<ge>.+?) \| page hourly (?P<ph>.+?), "
        r"synoptic (?P<py>.+?), ensemble (?P<pe>.+?) \| (?P<action>.+)$",
        line.strip(),
    )
    if not check:
        return line.strip()

    def one(raw: str) -> list[str]:
        raw = raw.replace(" already on page", "").strip()
        return [] if raw == "none" else [raw]

    return check_line(
        check.group("when"),
        one(check.group("gs")),
        one(check.group("gy")),
        one(check.group("ge")),
        one(check.group("ph"))[0] if one(check.group("ph")) else "",
        one(check.group("py"))[0] if one(check.group("py")) else "",
        one(check.group("pe"))[0] if one(check.group("pe")) else "",
        check.group("action"),
    )


def _normalize(text: str) -> list[str]:
    out = []
    for para in text.split("\n\n"):
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(re.match(r"^\d{4}-\d{2}-\d{2}T", ln) for ln in lines):
            out.extend(_legacy_block(ln) for ln in lines)
        else:
            out.append(para.strip("\n"))
    return out


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


def _log_body(text: str, line: str, now: datetime | None = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    blocks = _normalize(text)
    blocks.insert(0, line.strip("\n"))
    kept = _recent(blocks, now)
    return ("\n\n".join(kept) + "\n").encode()


def _put_log(token: str, generation: str, payload: bytes) -> None:
    name = urllib.parse.quote(LOG_OBJECT, safe="")
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


def append_log(token: str, line: str) -> None:
    """Keep the last 200 checks. One lost line on a clash is fine; the next check rewrites it."""
    text, generation = _log_text(token)
    try:
        _put_log(token, generation, _log_body(text, line))
    except urllib.error.HTTPError as exc:
        if exc.code != 412:
            raise
        text, generation = _log_text(token)
        _put_log(token, generation, _log_body(text, line))


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


def _gh(token: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "wn3-watch",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return exc.code, parsed


def post_watch_page(log_text: str) -> None:
    """Put the log on the website. One file, on top of whatever is already published."""
    gh = os.environ.get("GH_TOKEN") or ""
    if not gh:
        print("watch page skipped: no github token", flush=True)
        return
    for _ in range(3):
        code, ref = _gh(gh, "GET", f"/repos/{REPO}/git/ref/heads/gh-pages")
        if code != 200:
            raise RuntimeError(f"gh ref {code}")
        parent = ref["object"]["sha"]
        code, commit = _gh(gh, "GET", f"/repos/{REPO}/git/commits/{parent}")
        if code != 200:
            raise RuntimeError(f"gh commit {code}")
        code, blob = _gh(gh, "POST", f"/repos/{REPO}/git/blobs", {"content": log_text, "encoding": "utf-8"})
        if code not in (200, 201):
            raise RuntimeError(f"gh blob {code}")
        code, tree = _gh(gh, "POST", f"/repos/{REPO}/git/trees", {
            "base_tree": commit["tree"]["sha"],
            "tree": [{"path": "watch.log", "mode": "100644", "type": "blob", "sha": blob["sha"]}],
        })
        if code not in (200, 201):
            raise RuntimeError(f"gh tree {code}")
        code, made = _gh(gh, "POST", f"/repos/{REPO}/git/commits", {
            "message": "Update the watch log",
            "tree": tree["sha"],
            "parents": [parent],
        })
        if code not in (200, 201):
            raise RuntimeError(f"gh commit create {code}")
        code, _updated = _gh(gh, "PATCH", f"/repos/{REPO}/git/refs/heads/gh-pages", {"sha": made["sha"]})
        if code == 200:
            return
    raise RuntimeError("watch page raced a map publish")


def _record(token: str, line: str) -> None:
    print(line, flush=True)
    try:
        append_log(token, line)
    except Exception as exc:
        print(f"watch log failed: {exc}", flush=True)
        return
    try:
        text, _gen = _log_text(token)
        post_watch_page(text)
    except Exception as exc:
        print(f"watch page failed: {exc}", flush=True)


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
        line = "\n".join([_clock(when), _row("Result", f"failed: {exc}")])
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
    assert "Oct 15, 11:00:00 AM PT" in same and "no cook" in same and "new" not in same
    new = check_line(
        "2026-10-15T19:00:00Z",
        ["2026-10-15T12:00:00Z"], ["2026-10-15T12:00:00Z"], ["2026-10-15T18:00:00Z"],
        "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z", "2026-10-15T12:00:00Z",
        "cook started (ensemble 2026-10-15T18:00:00Z)",
    )
    assert "upper air 15 Oct 18Z new" in new
    assert "started a cook: upper air 15 Oct 18Z" in new
    old = _legacy_block(
        "2026-10-15T18:58:05Z check  google surface 2026-10-15T11:00:00Z, "
        "synoptic 2026-10-15T06:00:00Z already on page, "
        "ensemble 2026-10-15T06:00:00Z already on page | "
        "page hourly 2026-10-15T11:00:00Z, synoptic 2026-10-15T06:00:00Z, "
        "ensemble 2026-10-15T06:00:00Z | no cook"
    )
    assert "11:58:05 AM PT" in old and "surface 15 Oct 11Z" in old
    now = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
    older = check_line(
        "2026-10-15T18:00:00Z", [], [], [], "", "", "", "no cook",
    )
    newer = check_line(
        "2026-10-15T19:30:00Z", [], [], [], "", "", "", "no cook",
    )
    stale = check_line(
        "2026-10-15T06:00:00Z", [], [], [], "", "", "", "no cook",
    )
    ordered = _recent([older, newer, stale], now)
    assert ordered[0].startswith("Oct 15, 12:30:00 PM PT"), ordered[0]
    assert ordered[1].startswith("Oct 15, 11:00:00 AM PT")
    assert len(ordered) == 2
    print("watch decide ok")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--note":
        append_log(_token(), note_block(_now(), " ".join(sys.argv[2:])))
    elif len(sys.argv) == 3 and sys.argv[1] == "--dump":
        text, _gen = _log_text(_token())
        with open(sys.argv[2], "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        _self_check()
