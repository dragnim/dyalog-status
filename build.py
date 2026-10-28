#!/usr/bin/env python3
"""Check Dyalog services and build the status page into _site/index.html.

Run by the GitHub Actions workflow. No dependencies beyond Python 3.
"""
import html
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

TIMEOUT_S = 10   # no response after this = Outage
SLOW_S = 5       # slower than this = Degraded
SSL_WARN_DAYS = 14  # certificate flag turns amber inside this many days
UA = "DyalogStatus/1.0 (+https://status.dyalog.com)"

LABELS = {"up": "Operational", "degraded": "Degraded", "down": "Outage", "maint": "Maintenance"}
VALID_STATUS = {"auto", *LABELS}
ROOT = Path(__file__).parent


def check(url: str) -> dict:
    """Request the URL once. Returns the status, response time and a short reason."""
    start = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    body = b""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            code = res.status
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            body = e.read(65536)
        except Exception:
            pass
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            return {"status": "down", "secs": None, "detail": "Certificate error"}
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            return {"status": "down", "secs": None, "detail": f"No response within {TIMEOUT_S} s"}
        return {"status": "down", "secs": None, "detail": "Couldn't connect"}
    except (TimeoutError, socket.timeout):
        return {"status": "down", "secs": None, "detail": f"No response within {TIMEOUT_S} s"}
    except Exception:
        return {"status": "down", "secs": None, "detail": "Couldn't connect"}
    secs = time.monotonic() - start
    if code >= 400:
        # An error page that says it's down for maintenance counts as Maintenance
        if b"maintenance" in body.lower():
            return {"status": "maint", "secs": secs, "detail": "Maintenance page"}
        if code >= 500:
            reason = f"Server error ({code})"
        elif code == 403:
            reason = "Access blocked (403)"
        elif code == 404:
            reason = "Not found (404)"
        else:
            reason = f"Error {code}"
        return {"status": "down", "secs": secs, "detail": reason}
    if secs > SLOW_S:
        return {"status": "degraded", "secs": secs, "detail": f"Slow response \u00b7 {secs:.1f} s"}
    return {"status": "up", "secs": secs, "detail": f"{secs:.1f} s"}


def cert_info(url: str):
    """Return (kind, text, tooltip) for the HTTPS certificate, or None if unknown.

    This is shown as a separate flag and never changes the service status.
    """
    u = urlparse(url)
    if u.scheme != "https":
        return None
    host = u.hostname
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, u.port or 443), timeout=TIMEOUT_S) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                not_after = tls.getpeercert()["notAfter"]
    except ssl.SSLCertVerificationError as e:
        if "expired" in str(e.verify_message).lower():
            return ("bad", "SSL expired", "The certificate has expired")
        return ("bad", "SSL invalid", f"Certificate problem: {e.verify_message}")
    except Exception:
        return None  # couldn't connect; the status check covers that
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)
    days = (expires - datetime.now(timezone.utc)).days
    tip = f"Certificate expires {expires:%Y-%m-%d} ({days} days)"
    if days < SSL_WARN_DAYS:
        return ("warn", f"SSL expires in {days} day{'s' if days != 1 else ''}", tip)
    return ("ok", "SSL valid", tip)


RETRY_DELAY_S = 3  # pause before retrying an error, so a brief blip has time to clear


def check_with_retry(url: str) -> dict:
    # A slow response is a real result, so only errors are retried
    first = check(url)
    if first["status"] in ("up", "degraded"):
        return first
    time.sleep(RETRY_DELAY_S)
    return check(url)


def warn(msg: str):
    # Shows as a warning annotation on the GitHub Actions run
    print(f"::warning::{msg}")


def validate_services(services):
    """Fix up mistakes in services.json so one typo can't stop the page updating."""
    seen = set()
    clean = []
    for i, s in enumerate(services, 1):
        label = s.get("id") or s.get("name") or f"entry {i}"
        if not s.get("id") or not s.get("name") or not s.get("host"):
            warn(f"services.json: {label} is missing id, name or host, so it was left off the page")
            continue
        if s["id"] in seen:
            warn(f"services.json: duplicate id '{s['id']}', so the second one was left off the page")
            continue
        seen.add(s["id"])
        status = s.get("status", "auto")
        if status not in VALID_STATUS:
            warn(f"services.json: {label} has status '{status}', which isn't one of "
                 f"{', '.join(sorted(VALID_STATUS))}. Using the automatic check instead.")
            s["status"] = "auto"
        url = s.get("url", "")
        if urlparse(url).scheme not in ("http", "https"):
            warn(f"services.json: {label} has no valid http(s) url, so it was left off the page")
            continue
        clean.append(s)
    return clean


def parse_updates(text: str):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    updates = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        date, _, body = block.partition("\n")
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        if paras:
            updates.append((date.strip(), paras))
    return updates


def main():
    services = validate_services(json.loads((ROOT / "services.json").read_text())["services"])
    to_check = [s for s in services if s.get("status", "auto") == "auto"]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = dict(zip([s["id"] for s in to_check], pool.map(check_with_retry, [s["url"] for s in to_check])))
        certs = dict(zip([s["id"] for s in services], pool.map(cert_info, [s["url"] for s in services])))

    statuses, details = [], []
    for s in services:
        st = s.get("status", "auto")
        if st == "auto":
            statuses.append(results[s["id"]]["status"])
            details.append(results[s["id"]]["detail"])
        else:
            statuses.append(st)
            details.append("Set manually")

    e = html.escape
    def host(s):
        h = f'<a class="service-host" href="{e(s["url"])}" target="_blank" rel="noopener">{e(s["host"])}</a>'
        c = certs.get(s["id"])
        if c:
            kind, text, tip = c
            h += f'<span class="ssl {kind}" title="{e(tip)}">{e(text)}</span>'
        return f'<span class="service-meta">{h}</span>'

    rows = "".join(
        f'\n\t<li class="{st}">\n\t\t<span><span class="service-name">{e(s["name"])}</span>'
        f'{host(s)}</span>\n'
        f'\t\t<span class="status-col"><span class="state">{LABELS[st]}</span>'
        f'<span class="detail">{e(d)}</span></span>\n\t</li>'
        for s, st, d in zip(services, statuses, details)
    )

    key = f"""<h2>What the statuses mean</h2>
<ul class="key">
	<li class="up"><span class="state">{LABELS["up"]}</span><span>Responded normally within {SLOW_S} seconds.</span></li>
	<li class="degraded"><span class="state">{LABELS["degraded"]}</span><span>Working, but took longer than {SLOW_S} seconds to respond.</span></li>
	<li class="maint"><span class="state">{LABELS["maint"]}</span><span>The site is showing a maintenance page.</span></li>
	<li class="down"><span class="state">{LABELS["down"]}</span><span>The site returned an error, or didn't respond within {TIMEOUT_S} seconds. The reason is shown under the status.</span></li>
</ul>
<p class="key-note">Response times are measured from GitHub's servers, so they include the time to reach each site from there.
A site may load faster for you.</p>"""

    updates = parse_updates((ROOT / "updates.md").read_text())
    log = ""
    if updates:
        log = "<h2>Updates</h2>" + "".join(
            f'\n<div class="notice"><time class="date" datetime="{e(d)}">{e(d)}</time>'
            + "".join(f"<p>{e(p).replace(chr(10), '<br>')}</p>" for p in paras)
            + "</div>"
            for d, paras in updates
        )

    stamp = datetime.now(timezone.utc)
    now = stamp.strftime("%Y-%m-%d %H:%M UTC")
    iso = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    css = (ROOT / "style.css").read_text()

    page = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<meta http-equiv="refresh" content="300">
	<title>Dyalog | Service status</title>
	<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 247 247'%3E%3Cpath fill='%23FF6A13' d='M0 0L90.9989 0.0251617C107.5 0 124.322 1.83359 140.012 7.49824C170.926 18.0164 197.448 41.034 211.767 70.4078C225.488 98.0927 227.777 131.163 218.075 160.497C208.787 189.073 188.372 213.686 162.382 228.686C144.27 239.35 123.457 244.882 102.537 246.025H0V208C0 208 66.5525 208.434 99.822 208.234C122.578 207.902 145.082 198.554 161.211 182.491C175.876 168.13 185.152 148.303 186.216 127.759C187.427 107.906 180.907 87.8139 168.597 72.2029C152.375 51.2597 126.318 38.4809 99.8486 38.1751C79.2082 38.1618 58.6404 38 38 38V67H0V0Z'/%3E%3C/svg%3E">
	<style>
{css}
	</style>
</head>
<body>
<a class="logo" href="https://www.dyalog.com" title="Dyalog" target="_blank" rel="noopener">Dyalog</a>
<h1>Service status</h1>
<div class="banner degraded stale" role="alert" hidden></div>
<p class="checked" data-checked="{iso}">Last checked {now}.</p>
<ul class="services">{rows}
</ul>
{key}
{log}
<footer><p>&copy; Dyalog Ltd · <a href="https://github.com/dragnim/dyalog-status" target="_blank" rel="noopener">Source on GitHub</a></p></footer>
<script>
// Warn visitors if the checks have stopped updating this page
(function () {{
	var p = document.querySelector(".checked");
	var age = (Date.now() - Date.parse(p.dataset.checked)) / 60000;
	if (age > 30) {{
		var when = age < 120 ? Math.round(age) + " minutes" : Math.round(age / 60) + " hours";
		var s = document.querySelector(".stale");
		s.textContent = "This page may be out of date. The last check was " + when + " ago.";
		s.hidden = false;
	}}
}})();
</script>
</body>
</html>
"""
    out = ROOT / "_site"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(page)
    for s, st, d in zip(services, statuses, details):
        c = certs.get(s["id"])
        print(f"{s['id']:<12} {LABELS[st]:<12} {d:<28} {c[1] if c else 'no certificate info'}")


if __name__ == "__main__":
    main()
