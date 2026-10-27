#!/usr/bin/env python3
"""Check Dyalog services and build the status page into _site/index.html.

Run by the GitHub Actions workflow. No dependencies beyond Python 3.
"""
import html
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

TIMEOUT_S = 10   # no response after this = Outage
SLOW_S = 3       # slower than this = Degraded
UA = "DyalogStatus/1.0 (+https://status.dyalog.com)"

LABELS = {"up": "Operational", "degraded": "Degraded", "down": "Outage", "maint": "Maintenance"}
ROOT = Path(__file__).parent


def check(url: str) -> str:
    start = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            code = res.status
            body = b""
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            body = e.read(65536)
        except Exception:
            body = b""
    except Exception:
        return "down"
    if code >= 400:
        # An error page that says it's down for maintenance counts as Maintenance
        return "maint" if b"maintenance" in body.lower() else "down"
    return "degraded" if time.monotonic() - start > SLOW_S else "up"


def check_with_retry(url: str) -> str:
    # Retry once so a single blip doesn't show as an outage
    first = check(url)
    return first if first == "up" else check(url)


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
    services = json.loads((ROOT / "services.json").read_text())["services"]
    to_check = [s for s in services if s.get("url") and s.get("status", "auto") == "auto"]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = dict(zip([s["id"] for s in to_check], pool.map(check_with_retry, [s["url"] for s in to_check])))

    statuses = []
    for s in services:
        st = s.get("status", "auto")
        statuses.append(results.get(s["id"], "up") if st == "auto" else st)

    if "down" in statuses:
        banner, banner_text = "down", "Some services are currently unavailable"
    elif "degraded" in statuses:
        banner, banner_text = "degraded", "Some services are experiencing problems"
    elif "maint" in statuses:
        banner, banner_text = "maint", "Some services are undergoing maintenance"
    else:
        banner, banner_text = "up", "All services are operational"

    e = html.escape
    def host(s):
        if s.get("url"):
            return f'<a class="service-host" href="{e(s["url"])}">{e(s["host"])}</a>'
        return f'<span class="service-host">{e(s["host"])}</span>'

    rows = "".join(
        f'\n\t<li class="{st}">\n\t\t<span><span class="service-name">{e(s["name"])}</span>'
        f'{host(s)}</span>\n'
        f'\t\t<span class="state">{LABELS[st]}</span>\n\t</li>'
        for s, st in zip(services, statuses)
    )

    updates = parse_updates((ROOT / "updates.md").read_text())
    log = ""
    if updates:
        log = "<h2>Updates</h2>" + "".join(
            f'\n<div class="notice"><time class="date" datetime="{e(d)}">{e(d)}</time>'
            + "".join(f"<p>{e(p).replace(chr(10), '<br>')}</p>" for p in paras)
            + "</div>"
            for d, paras in updates
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    css = (ROOT / "style.css").read_text()

    page = f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<meta http-equiv="refresh" content="300">
	<title>Dyalog | Service status</title>
	<style>
{css}
	</style>
</head>
<body>
<a class="logo" href="https://www.dyalog.com" title="Dyalog">Dyalog</a>
<h1>Service status</h1>
<div class="banner {banner}">{banner_text}</div>
<p class="checked">Last checked {now}.</p>
<ul class="services">{rows}
</ul>
{log}
<footer><p>&copy; Dyalog Ltd</p></footer>
</body>
</html>
"""
    out = ROOT / "_site"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(page)
    print(banner_text, results)


if __name__ == "__main__":
    main()
