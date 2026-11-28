// The nightly dashboard (docs/nightly.md): the live state of a run of nightly.yml, read from the public GitHub API by
// the browser without a token (60 requests per hour per IP address, so it polls sparingly and pauses in a hidden tab: the
// API reads no browser session), and the history that docs_nightly.py publishes next to it
// (assets/nightly/history.json, rebuilt after every nightly).
//
// A cell is one lane (release:latest, branch:main vs release:latest, web-UI tier release:latest) on one shard. A
// finished session job carries the annotation "otterdog-acceptance results" (src/otterdog_acceptance/digest.py): its
// counts, SUT and failed node ids. Every string from the API or the history is rendered as text, never as HTML.
(function () {
  "use strict";

  const API = "https://api.github.com";
  const NOTICE_TITLE = "otterdog-acceptance results";
  const COUNTED = ["passed", "failed", "error", "skipped", "xfailed", "xpassed"];
  const PROBLEM_OUTCOMES = ["failed", "error", "xpassed"];
  const LANES = ["release:latest", "branch:main vs release:latest", "web-UI tier release:latest"];
  const JOBS_INTERVAL = 180 * 1000; // the jobs of a run in progress
  const RUNS_INTERVAL = 600 * 1000; // the list of runs (a new run)
  const RECENT_RUNS = 10;
  const LOW_RATE = 8; // requests left under which the page stops polling until the reset
  const STORE = "e2e-nightly-digests"; // finished jobs never change: their digests survive a reload
  const COUNTS_RE =
    /^(\d+) passed, (\d+) failed, (\d+) errors, (\d+) skipped, (\d+) xfailed, (\d+) xpassed$/;
  const KB_RE = /^KB-\d{1,5}$/;
  const SEPARATOR = " · ";
  let timer = null; // the polling of the page shown (navigation.instant keeps this script across pages)

  // --- parsing (shared with docs_nightly.py, checked by tests/unit/test_nightly_js.py) -----------------------------
  function parseJobName(name) {
    if (typeof name !== "string" || !name.includes(" / ")) return null;
    const index = name.indexOf(" / ");
    const caller = name.slice(0, index).trim();
    const called = name.slice(index + 3).trim();
    const match = /^(.+?) \(([^()]+)\)$/.exec(caller);
    if (!match || !called) return null;
    return { lane: laneName(match[1]), label: match[2], job: called };
  }

  // a lane without parentheses: "web-UI tier (release:latest)" of the older runs reads "web-UI tier release:latest"
  function laneName(text) {
    return text.replace(/[()]/g, " ").split(/\s+/).filter(Boolean).join(" ");
  }

  function isSession(called) {
    return called.startsWith("e2e ") || called.startsWith("web-UI ");
  }

  function parseNotice(message) {
    if (typeof message !== "string") return null;
    const lines = message.split(/\r?\n/);
    const match = COUNTS_RE.exec((lines[0] || "").trim());
    if (!match) return null;
    const digest = { counts: {}, problems: [], known_bugs: [] };
    COUNTED.forEach((name, index) => (digest.counts[name] = Number(match[index + 1])));
    lines.slice(1).forEach((raw) => {
      const found = /^([a-z][a-z ]*): (.*)$/.exec(raw.trim());
      if (!found) return;
      const key = found[1];
      const value = found[2].trim();
      if (PROBLEM_OUTCOMES.includes(key)) {
        const parts = value.split(SEPARATOR);
        digest.problems.push({
          outcome: key,
          nodeid: parts[0],
          known_bugs: parts.slice(1).filter((part) => KB_RE.test(part)),
          infra: parts.slice(1).includes("infra"),
        });
      } else if (key === "known bugs") {
        digest.known_bugs = value.split(/\s+/).filter((kb) => KB_RE.test(kb));
      } else if ((key === "seconds" || key === "more") && /^\d+$/.test(value)) {
        digest[key] = Number(value);
      } else if (["sut", "instance", "shard", "lane", "session"].includes(key)) {
        digest[key] = value;
      }
    });
    return digest;
  }

  function countsText(counts) {
    if (!counts) return "";
    const parts = [`${counts.passed} passed`];
    if (counts.failed) parts.push(`${counts.failed} failed`);
    if (counts.error) parts.push(`${counts.error} errors`);
    if (counts.xpassed) parts.push(`${counts.xpassed} xpassed`);
    if (counts.xfailed) parts.push(`${counts.xfailed} xfailed`);
    if (counts.skipped) parts.push(`${counts.skipped} skipped`);
    return parts.join(" · ");
  }

  function duration(seconds) {
    if (seconds === null || seconds === undefined || !isFinite(seconds) || seconds < 0) return "";
    const total = Math.round(seconds);
    if (total < 60) return `${total} s`;
    const minutes = Math.floor(total / 60);
    if (minutes < 60) return `${minutes}m ${String(total % 60).padStart(2, "0")}s`;
    return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
  }

  // the state of a cell: success, failure, cancelled, skipped, running, queued, waiting (no job yet)
  function stateOf(job) {
    if (!job) return "waiting";
    if (job.status === "in_progress") return "running";
    if (job.status === "queued" || job.status === "waiting" || job.status === "pending") return "queued";
    if (job.conclusion === "success") return "success";
    if (job.conclusion === "failure" || job.conclusion === "timed_out") return "failure";
    if (job.conclusion === "skipped") return "skipped";
    return job.conclusion ? "cancelled" : "queued";
  }

  // jobs of a run (API objects) -> {lanes: Map(lane -> Map(shard -> job)), skipped: Set(lane)}: per cell the session
  // job, else the job before it (a failed classification)
  function cellsOf(jobs, instanceShards) {
    const lanes = new Map();
    const skipped = new Set();
    (jobs || []).forEach((job) => {
      const parsed = parseJobName(job.name);
      if (!parsed) {
        // a matrix job skipped as a whole (its "if"): its name without the matrix part
        if (job.conclusion === "skipped" && typeof job.name === "string") {
          skipped.add(laneName(job.name.split("${{")[0]));
        }
        return;
      }
      const shard = (instanceShards && instanceShards[parsed.label]) || parsed.label;
      if (!lanes.has(parsed.lane)) lanes.set(parsed.lane, new Map());
      const row = lanes.get(parsed.lane);
      const current = row.get(shard);
      if (!current || (isSession(parsed.job) && !isSession(parseJobName(current.name).job))) row.set(shard, job);
    });
    return { lanes: lanes, skipped: skipped };
  }

  const api = { parseJobName, parseNotice, isSession, countsText, duration, stateOf, cellsOf };
  if (typeof module === "object" && module.exports) {
    module.exports = api;
    return;
  }

  // --- DOM helpers ------------------------------------------------------------------------------------------------
  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    (Array.isArray(content) ? content : content === undefined ? [] : [content]).forEach((child) => {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function link(href, content, className) {
    const node = el("a", className, content);
    if (typeof href === "string" && href.startsWith("https://github.com/")) node.href = href;
    return node;
  }

  function utc(value) {
    const date = value ? new Date(value) : null;
    if (!date || isNaN(date)) return "";
    return `${date.toISOString().slice(0, 10)} ${date.toISOString().slice(11, 16)} UTC`;
  }

  function seconds(start, end) {
    const from = start ? Date.parse(start) : NaN;
    const to = end ? Date.parse(end) : Date.now();
    return isNaN(from) || isNaN(to) ? null : (to - from) / 1000;
  }

  const STATE_LABELS = {
    success: "✓ passed",
    failure: "✗ failed",
    cancelled: "■ cancelled",
    skipped: "– skipped",
    running: "⟳ running",
    queued: "… queued",
    waiting: "… waiting",
  };

  function shortLane(lane) {
    if (lane === "release:latest") return "release:latest";
    if (lane.startsWith("branch:main")) return "branch:main";
    if (lane.startsWith("web-UI")) return "web-UI";
    return lane;
  }

  function readStore() {
    try {
      return JSON.parse(window.localStorage.getItem(STORE) || "{}") || {};
    } catch (error) {
      return {};
    }
  }

  function writeStore(store) {
    try {
      const keys = Object.keys(store);
      keys.slice(0, Math.max(0, keys.length - 200)).forEach((key) => delete store[key]);
      window.localStorage.setItem(STORE, JSON.stringify(store));
    } catch (error) {
      // private window, storage full: the digests are fetched again
    }
  }

  // --- the dashboard of one page ----------------------------------------------------------------------------------
  function Dashboard(root) {
    this.root = root;
    this.repo = root.dataset.repo || repoOfSite();
    this.workflow = root.dataset.workflow || "nightly.yml";
    this.historyUrl = new URL(root.dataset.history || "../assets/nightly/history.json", window.location.href);
    this.history = null;
    this.runs = [];
    this.runId = Number(new URLSearchParams(window.location.search).get("run")) || null;
    this.jobs = null;
    this.rate = null;
    this.error = null;
    this.digests = readStore();
    this.lastRuns = 0;
    this.updated = null;
    root.textContent = "";
    this.live = el("section", "e2e-nightly__live");
    this.past = el("section", "e2e-nightly__history");
    root.appendChild(this.live);
    root.appendChild(this.past);
  }

  function repoOfSite() {
    const source = document.querySelector(".md-source");
    const match = source && /^https:\/\/github\.com\/([^/]+\/[^/?#]+)/.exec(source.href);
    return match ? match[1] : null;
  }

  Dashboard.prototype.request = async function (path) {
    if (this.rate && this.rate.remaining < LOW_RATE && Date.now() < this.rate.reset) {
      throw new Error(this.limitMessage("nearly reached"));
    }
    const response = await fetch(API + path, {
      headers: { Accept: "application/vnd.github+json" },
      cache: "no-cache",
    });
    const remaining = Number(response.headers.get("x-ratelimit-remaining"));
    const reset = Number(response.headers.get("x-ratelimit-reset"));
    if (!isNaN(remaining) && response.headers.get("x-ratelimit-remaining") !== null) {
      this.rate = {
        remaining: remaining,
        limit: Number(response.headers.get("x-ratelimit-limit")) || 60,
        reset: reset * 1000,
      };
    }
    if ((response.status === 403 || response.status === 429) && this.rate && this.rate.remaining === 0) {
      throw new Error(this.limitMessage("reached"));
    }
    if (!response.ok) throw new Error(`GitHub API: HTTP ${response.status} for ${path.split("?")[0]}`);
    return response.json();
  };

  Dashboard.prototype.limitMessage = function (state) {
    return (
      `GitHub API: the limit of ${this.rate.limit} requests per hour of your IP address (shared by every page and ` +
      `tool behind it) is ${state}; next requests after ${utc(new Date(this.rate.reset))}.`
    );
  };

  Dashboard.prototype.loadHistory = async function () {
    try {
      const response = await fetch(this.historyUrl, { cache: "no-cache" });
      if (!response.ok) return;
      const data = await response.json();
      if (data && data.schema === 1 && Array.isArray(data.runs)) this.history = data;
    } catch (error) {
      // no history published yet (a local preview, the first deployment)
    }
  };

  Dashboard.prototype.instanceShards = function () {
    return (this.history && this.history.instance_shards) || {};
  };

  // digests of the published history, by job URL
  Dashboard.prototype.historyDigest = function (url) {
    if (!this.history || !url) return null;
    for (const run of this.history.runs) {
      for (const job of run.jobs || []) if (job.url === url && job.digest) return job.digest;
    }
    return null;
  };

  Dashboard.prototype.refresh = async function (force) {
    this.error = null;
    try {
      if (force || !this.runs.length || Date.now() - this.lastRuns >= RUNS_INTERVAL) {
        const data = await this.request(
          `/repos/${this.repo}/actions/workflows/${this.workflow}/runs?branch=main&per_page=${RECENT_RUNS}`
        );
        this.runs = (data.workflow_runs || []).filter((run) => run.event !== "pull_request");
        this.lastRuns = Date.now();
      }
      const run = this.selectedRun();
      if (run && (force || !this.jobs || this.jobs.runId !== run.id || run.status !== "completed" || !this.jobs.done)) {
        const data = await this.request(`/repos/${this.repo}/actions/runs/${run.id}/jobs?filter=latest&per_page=100`);
        this.jobs = { runId: run.id, list: data.jobs || [], done: run.status === "completed" };
        await this.fetchDigests(this.jobs.list);
      }
      this.updated = new Date();
    } catch (error) {
      this.error = error.message;
    }
    this.render();
    this.schedule();
  };

  // the run of ?run=, else the newest run in progress, else the newest run
  Dashboard.prototype.selectedRun = function () {
    return (
      this.runs.find((run) => run.id === this.runId) ||
      this.runs.find((run) => run.status !== "completed") ||
      this.runs[0] ||
      null
    );
  };

  // the annotations of the finished session jobs that neither the history nor the store hold
  Dashboard.prototype.fetchDigests = async function (jobs) {
    let changed = false;
    for (const job of jobs) {
      const parsed = parseJobName(job.name);
      if (!parsed || !isSession(parsed.job) || job.status !== "completed") continue;
      if (!["success", "failure"].includes(job.conclusion)) continue;
      if (this.digests[job.id] !== undefined || this.historyDigest(job.html_url)) continue;
      const annotations = await this.request(`/repos/${this.repo}/check-runs/${job.id}/annotations?per_page=50`);
      const notice = (annotations || []).find((annotation) => annotation.title === NOTICE_TITLE);
      this.digests[job.id] = notice ? parseNotice(notice.message) : null;
      changed = true;
    }
    if (changed) writeStore(this.digests);
  };

  Dashboard.prototype.digestOf = function (job) {
    return this.historyDigest(job.html_url) || this.digests[job.id] || null;
  };

  Dashboard.prototype.schedule = function () {
    clearTimeout(timer);
    if (!this.root.isConnected) return;
    const run = this.selectedRun();
    let delay = run && run.status !== "completed" ? JOBS_INTERVAL : RUNS_INTERVAL;
    if (this.rate && this.rate.remaining < LOW_RATE) delay = Math.max(delay, this.rate.reset - Date.now() + 5000);
    timer = setTimeout(() => {
      if (document.hidden) {
        document.addEventListener("visibilitychange", () => this.refresh(false), { once: true });
      } else {
        this.refresh(false);
      }
    }, delay);
  };

  // lanes and shards to show: those of the run, then those the history expects
  Dashboard.prototype.layout = function (cells) {
    const shards = [...((this.history && this.history.shards) || [])];
    const lanes = [...LANES];
    const expected = new Set();
    ((this.history && this.history.runs) || []).forEach((run) =>
      (run.jobs || []).forEach((job) => expected.add(`${job.lane}\n${job.shard}`))
    );
    cells.lanes.forEach((row, lane) => {
      if (!lanes.includes(lane)) lanes.push(lane);
      row.forEach((job, shard) => {
        if (!shards.includes(shard)) shards.push(shard);
        expected.add(`${lane}\n${shard}`);
      });
    });
    const used = shards.filter((shard) => lanes.some((lane) => expected.has(`${lane}\n${shard}`)));
    const rows = lanes.filter((lane) => used.some((shard) => expected.has(`${lane}\n${shard}`)));
    return { lanes: rows, shards: used, expected: expected };
  };

  Dashboard.prototype.render = function () {
    this.renderLive();
    this.renderHistory();
  };

  Dashboard.prototype.renderLive = function () {
    const live = this.live;
    live.textContent = "";
    live.appendChild(el("h2", null, "Live"));
    if (!this.repo) {
      live.appendChild(el("p", null, "The repository of the site is unknown (no data-repo, no repository link)."));
      return;
    }
    const run = this.selectedRun();
    live.appendChild(this.toolbar(run));
    if (this.error) live.appendChild(el("p", "e2e-nightly__error", this.error));
    if (!run) {
      if (!this.error) live.appendChild(el("p", null, "No run of the nightly yet."));
      return;
    }
    const jobs = this.jobs && this.jobs.runId === run.id ? this.jobs.list : [];
    const cells = cellsOf(jobs, this.instanceShards());
    const { lanes, shards, expected } = this.layout(cells);
    const table = el("table", "e2e-nightly__grid");
    table.appendChild(el("thead", null, el("tr", null, [el("th", null, "Lane"), ...shards.map((s) => el("th", null, s))])));
    const body = el("tbody");
    const problems = [];
    lanes.forEach((lane) => {
      const head = el("th", null, shortLane(lane));
      head.title = lane;
      const row = el("tr", null, head);
      shards.forEach((shard) => {
        const job = cells.lanes.has(lane) ? cells.lanes.get(lane).get(shard) : undefined;
        if (!job && !expected.has(`${lane}\n${shard}`)) {
          row.appendChild(el("td", "e2e-nightly__cell e2e-nightly__cell--none", ""));
          return;
        }
        const laneSkipped = !job && cells.skipped.has(lane);
        let state = laneSkipped ? "skipped" : stateOf(job);
        if (state === "waiting" && run.status === "completed") state = "none";
        const digest = job ? this.digestOf(job) : null;
        row.appendChild(this.cell(job, state, digest));
        if (digest) digest.problems.forEach((problem) => problems.push({ lane, shard, problem, job }));
      });
      body.appendChild(row);
    });
    table.appendChild(body);
    live.appendChild(el("div", "md-typeset__scrollwrap", el("div", "md-typeset__table", table)));
    if (problems.length) {
      live.appendChild(el("h3", null, "Failed, errored and xpassed items"));
      const list = el("ul", "e2e-nightly__problems");
      problems.forEach(({ lane, shard, problem, job }) => {
        list.appendChild(
          el("li", null, [
            el("span", `e2e-nightly__tag e2e-nightly__tag--${problem.outcome}`, problem.outcome),
            " ",
            link(job.html_url, `${shortLane(lane)} / ${shard}`),
            " ",
            el("code", null, problem.nodeid),
            problem.known_bugs.length ? ` ${problem.known_bugs.join(", ")}` : "",
            problem.infra ? " (infrastructure)" : "",
          ])
        );
      });
      live.appendChild(list);
    }
  };

  Dashboard.prototype.toolbar = function (run) {
    const bar = el("div", "e2e-nightly__toolbar");
    if (this.runs.length) {
      const select = el("select", "e2e-nightly__select");
      select.setAttribute("aria-label", "Run of the nightly");
      this.runs.forEach((item) => {
        const state = item.status === "completed" ? item.conclusion : item.status.replace("_", " ");
        const option = new Option(`#${item.run_number} · ${utc(item.created_at)} · ${item.event} · ${state}`, item.id);
        option.selected = run && item.id === run.id;
        select.appendChild(option);
      });
      select.addEventListener("change", () => {
        this.runId = Number(select.value);
        const params = new URLSearchParams(window.location.search);
        params.set("run", select.value);
        window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
        this.refresh(false);
      });
      bar.appendChild(select);
    }
    const button = el("button", "md-button e2e-nightly__refresh", "Refresh");
    button.type = "button";
    button.addEventListener("click", () => this.refresh(true));
    bar.appendChild(button);
    const facts = [];
    if (run) {
      facts.push(link(run.html_url, `run #${run.run_number}`));
      facts.push(` · ${run.status === "completed" ? run.conclusion : run.status.replace("_", " ")}`);
      facts.push(` · started ${utc(run.run_started_at || run.created_at)}`);
      if (run.head_sha) {
        facts.push(" · ");
        facts.push(link(`https://github.com/${this.repo}/commit/${run.head_sha}`, el("code", null, run.head_sha.slice(0, 7))));
      }
    }
    if (this.updated) facts.push(` · updated ${this.updated.toISOString().slice(11, 19)} UTC`);
    if (this.rate) facts.push(` · API ${this.rate.remaining}/${this.rate.limit} requests left`);
    bar.appendChild(el("span", "e2e-nightly__facts", facts));
    return bar;
  };

  Dashboard.prototype.cell = function (job, state, digest) {
    const td = el("td", `e2e-nightly__cell e2e-nightly__cell--${state}`);
    if (state === "none") {
      td.appendChild(el("span", "e2e-nightly__state", "not run"));
      return td;
    }
    const head = el("span", "e2e-nightly__state", STATE_LABELS[state] || state);
    td.appendChild(job && job.html_url ? link(job.html_url, head) : head);
    if (job && job.started_at && state !== "queued") {
      td.appendChild(el("span", "e2e-nightly__detail", duration(seconds(job.started_at, job.completed_at))));
    }
    if (state === "running") {
      const step = (job.steps || []).find((item) => item.status === "in_progress");
      if (step) td.appendChild(el("span", "e2e-nightly__detail", step.name));
    }
    if (digest) {
      td.appendChild(el("span", "e2e-nightly__counts", countsText(digest.counts)));
      if (digest.sut) td.appendChild(el("span", "e2e-nightly__detail", digest.sut));
    }
    return td;
  };

  // --- history ----------------------------------------------------------------------------------------------------
  Dashboard.prototype.renderHistory = function () {
    const past = this.past;
    past.textContent = "";
    past.appendChild(el("h2", null, "History"));
    if (!this.history || !this.history.runs.length) {
      past.appendChild(
        el("p", null, "No history published yet: the site gets it after the next nightly (docs_nightly.py).")
      );
      return;
    }
    const runs = this.history.runs;
    const shards = [...(this.history.shards || [])];
    runs.forEach((run) => (run.jobs || []).forEach((job) => shards.includes(job.shard) || shards.push(job.shard)));
    const used = shards.filter((shard) => runs.some((run) => (run.jobs || []).some((job) => job.shard === shard)));
    past.appendChild(
      el("p", "e2e-nightly__facts", `${runs.length} run(s), published ${utc(this.history.generated_at)}.`)
    );
    const table = el("table", "e2e-nightly__history-table");
    table.appendChild(
      el("thead", null, el("tr", null, [el("th", null, "Run"), el("th", null, "Lane"), ...used.map((s) => el("th", null, s))]))
    );
    const body = el("tbody");
    const failing = new Map(); // lane/shard -> node ids failing in the newer run already listed
    const news = [];
    runs.forEach((run) => {
      const lanes = [];
      (run.jobs || []).forEach((job) => lanes.includes(job.lane) || lanes.push(job.lane));
      lanes.sort((a, b) => (LANES.indexOf(a) + 1 || 99) - (LANES.indexOf(b) + 1 || 99));
      if (!lanes.length) lanes.push("");
      lanes.forEach((lane, index) => {
        const row = el("tr", index === 0 ? "e2e-nightly__run-start" : null);
        if (index === 0) {
          const head = el("th", null, [
            link(run.url, `#${run.number || run.id}`),
            el("span", "e2e-nightly__detail", utc(run.created_at)),
            el("span", "e2e-nightly__detail", `${run.event || ""} · ${run.conclusion || ""}`),
            run.sha ? link(`https://github.com/${this.history.repository}/commit/${run.sha}`, el("code", null, run.sha.slice(0, 7))) : "",
          ]);
          head.rowSpan = lanes.length;
          row.appendChild(head);
        }
        row.appendChild(el("td", null, shortLane(lane)));
        used.forEach((shard) => {
          const job = (run.jobs || []).find((item) => item.lane === lane && item.shard === shard);
          if (!job) {
            row.appendChild(el("td", "e2e-nightly__cell e2e-nightly__cell--none", ""));
            return;
          }
          const state = stateOf(job);
          const td = el("td", `e2e-nightly__cell e2e-nightly__cell--${state}`);
          td.appendChild(link(job.url, el("span", "e2e-nightly__state", STATE_LABELS[state] || state)));
          if (job.digest) {
            td.appendChild(el("span", "e2e-nightly__counts", countsText(job.digest.counts)));
            td.title = [job.digest.sut, duration(job.digest.seconds)].filter(Boolean).join(" · ");
          } else if (job.started_at && job.completed_at) {
            td.appendChild(el("span", "e2e-nightly__detail", duration(seconds(job.started_at, job.completed_at))));
          }
          row.appendChild(td);
          this.trackNew(run, lane, shard, job, failing, news);
        });
        body.appendChild(row);
      });
    });
    table.appendChild(body);
    past.appendChild(el("div", "md-typeset__scrollwrap", el("div", "md-typeset__table", table)));
    if (news.length) {
      past.appendChild(el("h3", null, "New failures"));
      past.appendChild(
        el("p", null, "Failed or errored in a run, not in the run before it on the same lane and shard (newest first).")
      );
      const list = el("ul", "e2e-nightly__problems");
      news.slice(0, 40).forEach(({ run, lane, shard, problem, job }) => {
        list.appendChild(
          el("li", null, [
            link(run.url, `#${run.number || run.id}`),
            ` ${utc(run.created_at).slice(0, 10)} `,
            link(job.url, `${shortLane(lane)} / ${shard}`),
            " ",
            el("code", null, problem.nodeid),
            problem.known_bugs.length ? ` ${problem.known_bugs.join(", ")}` : "",
            problem.infra ? " (infrastructure)" : "",
          ])
        );
      });
      past.appendChild(list);
    }
  };

  // runs come newest first: a failure is new when the next (older) run of the cell did not fail it
  Dashboard.prototype.trackNew = function (run, lane, shard, job, failing, news) {
    const key = `${lane}\n${shard}`;
    const failed = new Set(
      ((job.digest && job.digest.problems) || [])
        .filter((problem) => problem.outcome !== "xpassed")
        .map((problem) => problem.nodeid)
    );
    const newer = failing.get(key);
    if (newer && job.digest) {
      newer.items.forEach((entry) => {
        if (!failed.has(entry.problem.nodeid)) news.push(entry);
      });
    }
    const items = ((job.digest && job.digest.problems) || [])
      .filter((problem) => problem.outcome !== "xpassed")
      .map((problem) => ({ run, lane, shard, problem, job }));
    failing.set(key, { items: items });
  };

  // --- page hooks -------------------------------------------------------------------------------------------------
  async function init() {
    clearTimeout(timer);
    const root = document.querySelector(".e2e-nightly");
    if (!root || root.dataset.e2eReady) return;
    root.dataset.e2eReady = "true";
    const dashboard = new Dashboard(root);
    await dashboard.loadHistory();
    dashboard.render();
    await dashboard.refresh(false);
  }

  // navigation.instant replaces the content without reloading the page: document$ emits every page, the first one too
  if (window.document$) window.document$.subscribe(init);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
