# Dyalog service status

Checks Dyalog services every 10 minutes and publishes the status page with GitHub Pages.

## Posting an update

Edit `updates.md` on GitHub and commit. Add the new update at the top:

    ## 2026-10-28

    Your message here.

The page republishes within a minute or two of the commit.

## Overriding a service

In `services.json`, change a service's `status` from `auto` to one of:
`up`, `degraded`, `down` or `maint`. Set it back to `auto` to return to the automatic checks.

## Adding a service

Copy a line in `services.json` and change the `id`, `name`, `host` and `url`.
Every service needs a `url`; only add services that can be checked over the web.

## Running checks now

Actions tab > Status checks > Run workflow.
