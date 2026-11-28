---
# the grid of the dashboard takes the width of the navigation sidebar
hide:
  - navigation
---

# Nightly dashboard

Every night, [`nightly.yml`](../.github/workflows/nightly.yml) runs one session per test organization with
`release:latest`, then one with `branch:main` and a differential against `release:latest`, two organizations at a
time, then the web-UI tier. On the [documentation site](https://heurtematte.github.io/otterdog-e2e/nightly/), this page shows a run
of the nightly as it goes, and the history of the previous runs; the runs are also listed under
[Actions](https://github.com/heurtematte/otterdog-e2e/actions/workflows/nightly.yml).

<!-- site:nightly -->

## Reading the dashboard

- **A cell** is one lane on one shard (the organization that runs it, see
  [Organizations and shards](architecture.md#organizations-and-shards)): `release:latest`, `branch:main` (named
  `branch:main vs release:latest` in Actions) or the web-UI tier. A waiting cell has no job yet: the nightly runs two
  organizations at a time, and `branch:main` starts once every `release:latest` session is done. A cell links to its
  job, which has the job summary, the logs and the artifact name.
- **The counts** of a finished session (passed, failed, errors, xpassed, xfailed, skipped) and its SUT come from the
  notice its digest step prints (`otterdog-acceptance digest`, [reference](reference.md)), which GitHub keeps as an
  annotation of the job. Only counts, the SUT, durations and the node ids of the failed, errored and xpassed items
  with their known bugs are published that way, never a failure text or a command output: those stay in the scrubbed
  artifacts. An xfailed item is a [known otterdog issue](known-issues.md) that showed as expected.
- **Live**: the page reads the runs and their jobs from the GitHub API in your browser. Without a token GitHub allows
  60 requests per hour per IP address, shared with every page and tool behind that address (an office, a VPN): the page
  refreshes the jobs of a run in progress every 3 minutes, the list of runs every 10 minutes, never while the tab is
  hidden, and stops until the limit resets when fewer than 8 requests are left. `?run=<id>` in the address shows
  another run of the last ten. It uses no token and cannot use your github.com session: the API reads no browser
  cookie, and signing in with GitHub needs a server to exchange its code, which a static site has not.
- **History**: after every nightly, the documentation workflow rebuilds the site with the runs of the nightly on
  `main` and the digests of their jobs (`docs_nightly.py`, at most the 60 newest runs). A failure is new when the run
  before it on the same lane and shard did not have it.

## Running it locally

`python docs_nightly.py collect` writes the history to `docs/assets/nightly/history.json` (ignored by git), which
`make docs-serve` then serves: set `GITHUB_REPOSITORY=heurtematte/otterdog-e2e`, and `GITHUB_TOKEN` to raise the
API limit of the collection (without it, keep `--max-new` low: about 12 requests per run).
