# Dyalog service status

A status page for Dyalog's public web services, live at
https://dragnim.github.io/dyalog-status/

Every 10 minutes the checks run, the page is rebuilt from the results and published with GitHub Pages.
Each update usually appears 1 to 2 minutes after the check starts.

## How the checks run

- **cron-job.org** triggers the workflow every 10 minutes through GitHub's API. This is the main schedule,
  because GitHub's own scheduled runs are unreliable.
- **GitHub's built-in schedule** (`cron` in `.github/workflows/status.yml`) runs hourly as a backup.
- **Any commit to `main`** also triggers a run, so edits to the files below appear straight away.

The cron-job.org job uses a fine-grained GitHub token, stored only in cron-job.org. It is limited to
Actions (read and write) on this repository and has no expiry. If it is ever exposed, revoke it under
GitHub Settings > Developer settings > Personal access tokens > Fine-grained tokens, create a new one with
the same permissions, and paste it into the job's `Authorization` header as `Bearer <token>`.

## How statuses are decided

Each service's URL is requested. If that gives an error, it waits 3 seconds and tries once more before
showing Maintenance or Outage. Slow responses aren't retried.

| Result | Status |
| --- | --- |
| Normal response within 5 seconds | Operational |
| Normal response, but slower than 5 seconds | Degraded |
| Error page (4xx or 5xx) that mentions maintenance | Maintenance |
| Any other 4xx or 5xx error, or no response within 10 seconds | Outage |

Sites behind Cloudflare's bot check can't be seen past that check, so they show as Outage when the
check blocks them.

## The SSL badge

The badge next to each hostname shows the state of its HTTPS certificate. It is separate from the
status and never changes it.

- **SSL valid** (grey): the certificate is fine. Hover over it to see the expiry date.
- **SSL expires in N days** (amber): the certificate expires within 14 days.
- **SSL expired** or **SSL invalid** (red): the certificate has expired or fails verification.

No badge is shown if the site can't be reached at all.

## The out-of-date notice

If the last check is more than 30 minutes old, an amber notice appears at the top of the page saying so.
It means the checks have stopped running, so look at the Actions tab and the cron-job.org job history.

## Posting an update

Edit `updates.md` on GitHub and commit. Add the new update at the top:

    ## 2026-10-28

    Your message here.

Leave a blank line between paragraphs. The page republishes within a minute or two of the commit.

## Mistakes in services.json

The build checks `services.json` before running. A mistyped `status` falls back to the automatic check,
and an entry with a duplicate `id` or missing `id`, `name`, `host` or `url` is left off the page. Either way
the page keeps publishing, and the run shows a warning in the Actions tab explaining what was wrong.

## Overriding a service

In `services.json`, change a service's `status` from `auto` to one of:
`up`, `degraded`, `down` or `maint`. This replaces the automatic check for that service until you set it
back to `auto`, so remember to change it back.

## Adding a service

Copy a line in `services.json` and change the `id`, `name`, `host` and `url`.
Every service needs a `url`; only add services that can be checked over the web.

## Running checks now

Actions tab > Status checks > Run workflow.

## Files

- `services.json`: the list of services and any overrides
- `updates.md`: the dated messages shown under the list
- `build.py`: runs the checks and builds the page
- `style.css`: the page styling, including light and dark mode
- `.github/workflows/status.yml`: the workflow that runs `build.py` and publishes the page

## Housekeeping

- GitHub pauses scheduled workflows in public repos after 60 days without a commit. The workflow pushes an
  empty commit when the last one is more than 50 days old, so this shouldn't happen.
- The repo is public because GitHub Pages and unlimited Actions minutes are only free for public repos.
  Nothing in it is secret.
