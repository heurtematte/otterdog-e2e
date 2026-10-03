"""Base templates (SPEC 10.6): upstream/url/offline refs, vendoring, auto resolution and the TemplatePublisher flow."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
import responses

from otterdog_e2e import procs
from otterdog_e2e.github.http import GitHubHttp
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.sut.spec import ResolvedSut, parse_sut_spec
from otterdog_e2e.sut.template import (
    HOOK_FILES,
    OFFLINE_TEMPLATE_URL,
    TemplatePublisher,
    TemplateRef,
    content_hash8,
    git_blob_sha,
    needs_publisher,
    offline_template,
    resolve_template,
    template_files,
    upstream_template,
    url_template,
    vendor_template,
)
from otterdog_e2e.testing.fakes import FAKE_ORG, FakeGitHubHttp, HttpCall, fake_sha, make_verified_org

SHA = "a07ce8ad16f43178cb7366b737e3e2903aa349ef"
API = f"/repos/{FAKE_ORG}/otterdog-e2e-defaults"
DEFAULTS = "otterdog-e2e-defaults"
HEAD = fake_sha("defaults-head")
TEMPLATE = {
    "otterdog-defaults.libsonnet": "local otterdog = import 'otterdog-functions.libsonnet';\n{ newOrg(n, i):: {} }\n",
    "otterdog-functions.libsonnet": "{}\n",
}


def make_sut(
    tmp_path: Path, raw: str = "v1.6.1", *, label: str = "v1.6.1", files: dict[str, str] | None = None
) -> ResolvedSut:
    """A ResolvedSut whose source dir holds examples/template files."""
    source = tmp_path / "source"
    template_dir = source / "examples" / "template"
    template_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (files if files is not None else TEMPLATE).items():
        (template_dir / name).write_text(content)
    spec = parse_sut_spec(raw)
    return ResolvedSut(
        spec, label, SHA, "1.6.1", "1.6.1", source, "https://github.com/eclipse-csi/otterdog", spec.trusted
    )


# --- refs ------------------------------------------------------------------------------------------------------------
def test_upstream_template_is_sha_pinned(tmp_path: Path) -> None:
    """Upstream example template at the SUT sha, imported from vendor/otterdog/examples/template/."""
    ref = upstream_template(make_sut(tmp_path), "eclipse-csi/otterdog")
    assert ref.url == f"https://github.com/eclipse-csi/otterdog#examples/template/otterdog-defaults.libsonnet@{SHA}"
    assert (ref.repo_name, ref.ref, ref.is_pinned, ref.tag) == ("otterdog", SHA, True, None)  # tags: published only
    assert ref.import_path == "vendor/otterdog/examples/template/otterdog-defaults.libsonnet"


@pytest.mark.parametrize("raw", [f"pr:1@{SHA}", "sha:a07ce8a", "path:/x", "dirty:/x"])
def test_upstream_template_only_for_upstream_refs(tmp_path: Path, raw: str) -> None:
    """otterdog's template clone only sees upstream branches/tags: other SUTs must publish."""
    with pytest.raises(ValueError, match="publish"):
        upstream_template(make_sut(tmp_path, raw), "eclipse-csi/otterdog")


def test_url_template_parses_like_otterdog(caplog: pytest.LogCaptureFixture) -> None:
    """repo name = basename of the repo URL, file = fragment before '@', ref after it."""
    ref = url_template(f"https://github.com/acme/defaults#sub/dir/otterdog-defaults.libsonnet@{SHA}")
    assert (ref.repo_name, ref.file, ref.ref) == ("defaults", "sub/dir/otterdog-defaults.libsonnet", SHA)
    assert ref.import_path == "vendor/defaults/sub/dir/otterdog-defaults.libsonnet"
    with caplog.at_level(logging.WARNING):
        assert not url_template("https://github.com/acme/defaults#otterdog-defaults.libsonnet@main").is_pinned
    assert "not a commit sha" in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/acme/defaults#otterdog-defaults.libsonnet@main",
        "https://github.com/acme#otterdog-defaults.libsonnet@main",
        "https://github.com/acme/defaults/extra#otterdog-defaults.libsonnet@main",
        "http://github.com/acme/defaults#otterdog-defaults.libsonnet@main",
        "https://github.com/acme/defaults#otterdog-defaults.libsonnet",
        "https://github.com/acme/defaults",
        "https://github.com/acme/defaults#../x.libsonnet@main",
    ],
)
def test_url_template_rejects_invalid_urls(url: str) -> None:
    """Only https://github.com/<owner>/<repo>#<relative file>@<ref>."""
    with pytest.raises(ValueError):
        url_template(url)


def test_offline_template() -> None:
    """The offline placeholder imports vendor/template/otterdog-defaults.libsonnet."""
    ref = offline_template()
    assert ref.url == OFFLINE_TEMPLATE_URL and ref.import_path == "vendor/template/otterdog-defaults.libsonnet"
    assert ref.tag is None and url_template(f"https://github.com/acme/t#f.libsonnet@{SHA}").tag is None


def test_vendor_template_offline_and_subdir(tmp_path: Path) -> None:
    """Files land in vendor/<repo>/<dirname(file)>/; stale vendored files are removed."""
    sut = make_sut(tmp_path)
    src = sut.source_dir / "examples" / "template"
    (src / "hook.py").write_text("print('never copied')\n")
    org_dir = tmp_path / "orgs" / "o"
    stale = org_dir / "vendor" / "template" / "stale.libsonnet"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    vendor_template(src, org_dir, offline_template())
    assert sorted(p.name for p in (org_dir / "vendor" / "template").iterdir()) == sorted(TEMPLATE)
    upstream = upstream_template(sut, "eclipse-csi/otterdog")
    vendor_template(src, org_dir, upstream)
    assert (org_dir / upstream.import_path).read_text() == TEMPLATE["otterdog-defaults.libsonnet"]
    with pytest.raises(FileNotFoundError):
        vendor_template(src, org_dir, TemplateRef("u", "template", "missing.libsonnet", "offline"))
    with pytest.raises(ValueError):
        vendor_template(src, org_dir, TemplateRef("u", "..", "otterdog-defaults.libsonnet", "offline"))


def test_vendor_template_writes_hook_files_at_the_template_root(tmp_path: Path) -> None:
    """Hook scripts land in vendor/<repo>/ (otterdog's template_dir), also for a template file in a subdirectory;
    unknown names are refused before anything is written; a later vendoring without hooks removes them."""
    sut = make_sut(tmp_path)
    src = sut.source_dir / "examples" / "template"
    org_dir = tmp_path / "orgs" / "o"
    hook = "context.property_equals(self, 'default_repository_permission', 'none')\n"
    vendor_template(src, org_dir, offline_template(), hooks={"validate-org-settings.py": hook})
    root = org_dir / "vendor" / "template"
    assert (root / "validate-org-settings.py").read_text() == hook
    assert sorted(p.name for p in root.iterdir()) == sorted([*TEMPLATE, "validate-org-settings.py"])
    nested = TemplateRef("u", "template", "sub/otterdog-defaults.libsonnet", "offline")
    vendor_template(src, org_dir, nested, hooks={"pre-add-object-hook.py": "pass\n"})
    assert (root / "pre-add-object-hook.py").is_file() and (root / "sub" / "otterdog-defaults.libsonnet").is_file()
    assert not (root / "sub" / "pre-add-object-hook.py").exists()
    with pytest.raises(ValueError, match="unknown template hook"):
        vendor_template(src, org_dir, offline_template(), hooks={"evil.py": "pass\n"})
    assert (root / "pre-add-object-hook.py").is_file()  # refused before the old vendored files were touched
    vendor_template(src, org_dir, offline_template())
    assert not (root / "pre-add-object-hook.py").exists() and set(HOOK_FILES).isdisjoint(p.name for p in root.iterdir())


# --- resolve_template ------------------------------------------------------------------------------------------------
class _StubPublisher:
    """Records publish() calls."""

    def __init__(self) -> None:
        """No calls yet."""
        self.calls: list[str] = []

    def publish(self, sut: ResolvedSut) -> TemplateRef:
        """Return a fixed published ref."""
        self.calls.append(sut.label)
        return TemplateRef(
            f"https://github.com/o/d#otterdog-defaults.libsonnet@{SHA}", "d", "otterdog-defaults.libsonnet", SHA
        )


@pytest.mark.parametrize(("raw", "published"), [("release:latest", False), ("v1.6.1", False), ("main", False),
                                                 (f"pr:1@{SHA}", True), ("sha:a07ce8a", True), ("dirty:/x", True)])  # fmt: skip
def test_resolve_template_auto(tmp_path: Path, raw: str, published: bool) -> None:
    """auto: upstream for release/tag/branch, publish otherwise."""
    publisher = _StubPublisher()
    ref = resolve_template(
        "auto", make_sut(tmp_path, raw), upstream_repo="eclipse-csi/otterdog", publisher=publisher, url=None
    )  # type: ignore[arg-type]
    assert bool(publisher.calls) is published
    assert ref.repo_name == ("d" if published else "otterdog")
    assert needs_publisher("auto", make_sut(tmp_path, raw)) is published


def test_resolve_template_explicit_modes(tmp_path: Path) -> None:
    """upstream, publish and url modes; missing inputs are errors."""
    sut = make_sut(tmp_path)
    publisher = _StubPublisher()
    kw: dict[str, Any] = {"upstream_repo": "eclipse-csi/otterdog"}
    assert resolve_template("publish", sut, publisher=publisher, url=None, **kw).repo_name == "d"  # type: ignore[arg-type]
    assert resolve_template("upstream", sut, publisher=None, url=None, **kw).repo_name == "otterdog"
    url = f"https://github.com/acme/t#otterdog-defaults.libsonnet@{SHA}"
    assert resolve_template("url", sut, publisher=None, url=url, **kw).url == url
    with pytest.raises(ValueError, match="needs a template url"):
        resolve_template("url", sut, publisher=None, url=None, **kw)
    with pytest.raises(ValueError, match="needs a publisher"):
        resolve_template("auto", make_sut(tmp_path, f"pr:1@{SHA}"), publisher=None, url=None, **kw)
    with pytest.raises(ValueError, match="unknown template mode"):
        resolve_template("magic", sut, publisher=None, url=None, **kw)
    assert needs_publisher("publish", sut) and not needs_publisher("upstream", make_sut(tmp_path, f"pr:1@{SHA}"))
    assert not needs_publisher("url", make_sut(tmp_path, f"pr:1@{SHA}"))
    with pytest.raises(ValueError, match="unknown template mode"):
        needs_publisher("magic", sut)


# --- TemplatePublisher -----------------------------------------------------------------------------------------------
def test_git_blob_sha_matches_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The expected blob ids are what git hash-object computes."""
    monkeypatch.setattr(procs, "_default_home", tmp_path / "home")
    content = TEMPLATE["otterdog-defaults.libsonnet"]
    result = procs.run(["git", "hash-object", "--stdin"], input=content, timeout=30)
    assert git_blob_sha(content.encode()) == result.stdout.strip()


def _tree_entries(files: dict[str, str]) -> list[dict[str, Any]]:
    """What GitHub returns for a tree of 100644 blobs."""
    return [
        {"path": n, "mode": "100644", "type": "blob", "sha": git_blob_sha(c.encode())} for n, c in sorted(files.items())
    ]


def _tree_responder(call: HttpCall) -> tuple[int, dict[str, Any]]:
    """POST git/trees: blobs are hashed from the inline content like GitHub does."""
    files = {entry["path"]: entry["content"] for entry in call.json["tree"]}
    return 201, {
        "sha": fake_sha(("tree", tuple(sorted(files.items())))),
        "tree": _tree_entries(files),
        "truncated": False,
    }


def _publisher(http: FakeGitHubHttp) -> TemplatePublisher:
    """A publisher bound to the fake org's defaults repo."""
    return TemplatePublisher(http, http.write_scope, DEFAULTS)  # type: ignore[arg-type]


def _http() -> FakeGitHubHttp:
    """Fake client with write_scope = the fake verified org."""
    return FakeGitHubHttp(identity="admin", write_scope=make_verified_org())


def _expect_create(http: FakeGitHubHttp, *, refs_status: int = 201) -> str:
    """Routes of a fresh publication; returns the commit sha the fake will create."""
    commit = fake_sha("published-commit")
    http.add("GET", f"{API}/git/ref/tags/*", status=404, json={"message": "Not Found"})
    http.add("GET", API, json={"name": DEFAULTS, "default_branch": "main", "private": False})
    http.add(
        "GET", f"{API}/git/ref/heads/main", json={"ref": "refs/heads/main", "object": {"type": "commit", "sha": HEAD}}
    )
    http.add("POST", f"{API}/git/trees", responder=_tree_responder)
    http.add("POST", f"{API}/git/commits", status=201, json={"sha": commit, "tree": {"sha": "t"}})
    http.add("POST", f"{API}/git/refs", status=refs_status, json={"ref": "x", "object": {"sha": commit}})
    return commit


def test_publish_creates_tree_commit_and_tag(tmp_path: Path) -> None:
    """No base_tree, parent = default-branch head, lightweight tag, default branch never updated, sha-pinned URL."""
    http = _http()
    commit = _expect_create(http)
    sut = make_sut(tmp_path, f"pr:792@{SHA}", label="pr792-a07ce8a")
    ref = _publisher(http).publish(sut)
    tag = f"sut-pr792-a07ce8a-{content_hash8({k: v.encode() for k, v in TEMPLATE.items()})}"
    assert ref == TemplateRef(
        f"https://github.com/{FAKE_ORG}/{DEFAULTS}#otterdog-defaults.libsonnet@{commit}",
        DEFAULTS,
        "otterdog-defaults.libsonnet",
        commit,
        tag=tag,
    )
    assert ref.import_path == f"vendor/{DEFAULTS}/otterdog-defaults.libsonnet" and ref.is_pinned
    (tree,) = http.calls_to("POST", f"{API}/git/trees")
    assert set(tree.json) == {"tree"}  # NO base_tree: the tree holds exactly the template files
    assert [(e["path"], e["mode"], e["type"]) for e in tree.json["tree"]] == [
        ("otterdog-defaults.libsonnet", "100644", "blob"),
        ("otterdog-functions.libsonnet", "100644", "blob"),
    ]
    (commit_call,) = http.calls_to("POST", f"{API}/git/commits")
    assert commit_call.json["parents"] == [HEAD] and SHA in commit_call.json["message"]
    assert "/home" not in commit_call.json["message"]
    (refs,) = http.calls_to("POST", f"{API}/git/refs")
    assert refs.json == {"ref": f"refs/tags/{tag}", "sha": commit}
    assert not http.calls_to("PATCH") and not http.calls_to("PUT") and not http.calls_to("DELETE")


def _ref_name(path: str) -> str:
    """refs/tags/<tag> of a GET git/ref/tags/<tag> path."""
    return "refs/" + path.split("/git/ref/", 1)[1]


def _existing_tag(http: FakeGitHubHttp, files: dict[str, str], *, annotated: bool = False) -> str:
    """Routes of an already published tag whose tree holds ``files``."""
    commit, tree = fake_sha("existing-commit"), fake_sha("existing-tree")
    target = {"type": "tag", "sha": "tagobj"} if annotated else {"type": "commit", "sha": commit}
    http.add("GET", f"{API}/git/ref/tags/*", responder=lambda c: (200, {"ref": _ref_name(c.path), "object": target}))
    if annotated:
        http.add("GET", f"{API}/git/tags/tagobj", json={"object": {"type": "commit", "sha": commit}})
    http.add("GET", f"{API}/git/commits/{commit}", json={"sha": commit, "tree": {"sha": tree}})
    http.add("GET", f"{API}/git/trees/{tree}", json={"sha": tree, "tree": _tree_entries(files), "truncated": False})
    return commit


@pytest.mark.parametrize("annotated", [False, True])
def test_publish_reuses_a_verified_existing_tag(tmp_path: Path, annotated: bool) -> None:
    """An existing tag with exactly the expected blobs is reused without any write."""
    http = _http()
    commit = _existing_tag(http, TEMPLATE, annotated=annotated)
    ref = _publisher(http).publish(make_sut(tmp_path, "dirty:/x", label="local-a07ce8a"))
    assert (
        ref.ref == commit
        and ref.tag == f"sut-local-a07ce8a-{content_hash8({k: v.encode() for k, v in TEMPLATE.items()})}"
    )
    assert not [c for c in http.calls if c.method != "GET"]


@pytest.mark.parametrize(
    "files",
    [
        {**TEMPLATE, "validate-repository.py": "import os\n"},  # an exec'd hook sneaked in (SEC-12)
        {"otterdog-defaults.libsonnet": TEMPLATE["otterdog-defaults.libsonnet"]},  # missing file
        {**TEMPLATE, "otterdog-functions.libsonnet": "{ evil: true }\n"},  # changed content
    ],
)
def test_publish_refuses_a_tampered_existing_tag(tmp_path: Path, files: dict[str, str]) -> None:
    """A tag whose tree differs from the expected blobs is a SafetyError (tags are mutable, names predictable)."""
    http = _http()
    _existing_tag(http, files)
    with pytest.raises(SafetyError, match="differs"):
        _publisher(http).publish(make_sut(tmp_path))


def test_publish_race_accepts_only_identical_trees(tmp_path: Path) -> None:
    """422 on POST git/refs: re-read the tag and accept it only with the identical tree."""
    http = _http()
    _expect_create(http, refs_status=422)  # first tag lookup: 404 (routes are answered FIFO)
    other = _existing_tag(http, TEMPLATE)  # lookup after the 422: the racing publisher's tag
    assert _publisher(http).publish(make_sut(tmp_path)).ref == other
    assert len(http.calls_to("POST", f"{API}/git/refs")) == 1
    http = _http()
    _expect_create(http, refs_status=422)
    _existing_tag(http, {**TEMPLATE, "hook.py": "x"})
    with pytest.raises(SafetyError, match="differs"):
        _publisher(http).publish(make_sut(tmp_path))


def test_publish_requires_a_public_initialised_defaults_repo(tmp_path: Path) -> None:
    """otterdog clones templates anonymously; an empty repo has no parent commit."""
    http = _http()
    http.add("GET", f"{API}/git/ref/tags/*", status=404, json={})
    http.add("GET", API, json={"default_branch": "main", "private": True})
    with pytest.raises(RuntimeError, match="must be public"):
        _publisher(http).publish(make_sut(tmp_path))
    http = _http()
    http.add("GET", f"{API}/git/ref/tags/*", status=404, json={})
    http.add("GET", API, json={"default_branch": "main", "private": False})
    http.add("GET", f"{API}/git/ref/heads/main", status=409, json={"message": "Git Repository is empty."}, repeat=True)
    publisher, sleeps = _publisher(http), []
    publisher.sleep = sleeps.append
    with pytest.raises(RuntimeError, match=r"no commit on main after 30 s.*auto_init"):
        publisher.publish(make_sut(tmp_path))
    assert sleeps == [3.0] * 10


def test_publish_waits_for_the_first_commit_of_a_new_defaults_repo(tmp_path: Path) -> None:
    """F3: a defaults repository bootstrap just created answers 409 until its auto_init commit exists: the publisher
    retries instead of failing."""
    http = _http()
    commit = _expect_create(http)
    route = http.routes[("GET", f"{API}/git/ref/heads/main")]
    route.insert(0, route[0].__class__(409, {"message": "Git Repository is empty."}, {}, False, None))
    publisher, sleeps = _publisher(http), []
    publisher.sleep = sleeps.append
    assert publisher.publish(make_sut(tmp_path)).ref == commit and sleeps == [3.0]


def test_publisher_requires_verified_scope(tmp_path: Path) -> None:
    """A VerifiedOrg and a write-scoped client of the same org are mandatory."""
    verified = make_verified_org()
    with pytest.raises(SafetyError, match="VerifiedOrg"):
        TemplatePublisher(FakeGitHubHttp(write_scope=verified), object(), DEFAULTS)  # type: ignore[arg-type]
    with pytest.raises(SafetyError, match="write_scope"):
        TemplatePublisher(FakeGitHubHttp(), verified, DEFAULTS)  # type: ignore[arg-type]
    other = make_verified_org("other-org", org_id=1)
    with pytest.raises(SafetyError, match="write_scope"):
        TemplatePublisher(FakeGitHubHttp(write_scope=other), verified, DEFAULTS)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid repository"):
        TemplatePublisher(FakeGitHubHttp(write_scope=verified), verified, "a/b")  # type: ignore[arg-type]


def test_template_files_and_hash(tmp_path: Path) -> None:
    """Only regular *.libsonnet files; the hash depends on names and contents."""
    sut = make_sut(tmp_path)
    src = sut.source_dir / "examples" / "template"
    (src / "README.md").write_text("x")
    (src / "link.libsonnet").symlink_to("otterdog-functions.libsonnet")
    files = template_files(sut.source_dir)
    assert sorted(files) == sorted(TEMPLATE)
    changed = {**files, "otterdog-functions.libsonnet": b"{ x: 1 }\n"}
    assert content_hash8(files) == content_hash8(dict(files)) != content_hash8(changed)
    assert len(content_hash8(files)) == 8
    with pytest.raises(FileNotFoundError):
        template_files(make_sut(tmp_path / "empty", files={"other.libsonnet": "{}"}).source_dir)


def test_publish_through_the_real_client_with_responses(tmp_path: Path) -> None:
    """The same flow through github.http.GitHubHttp (write-scoped) against mocked api.github.com endpoints."""
    base = f"https://api.github.com{API}"
    commit = fake_sha("real-client-commit")
    bodies: dict[str, Any] = {}

    def tree_callback(request: Any) -> tuple[int, dict[str, str], str]:
        """Hash the posted inline contents like GitHub."""
        bodies["tree"] = json.loads(request.body)
        status, body = _tree_responder(HttpCall("POST", f"{API}/git/trees", None, bodies["tree"]))
        return status, {}, json.dumps(body)

    def capture(name: str, status: int, answer: dict[str, Any]) -> Any:
        """Record the request body of ``name`` and answer ``answer``."""

        def callback(request: Any) -> tuple[int, dict[str, str], str]:
            """Store the JSON body."""
            bodies[name] = json.loads(request.body)
            return status, {}, json.dumps(answer)

        return callback

    verified = make_verified_org()
    http = GitHubHttp("ghp_" + "t" * 36, write_scope=verified, sleep=lambda s: None, min_write_interval=0)
    with responses.RequestsMock() as mock:
        mock.add(
            responses.GET,
            f"{base}/git/ref/tags/sut-v1.6.1-{content_hash8({k: v.encode() for k, v in TEMPLATE.items()})}",
            status=404,
            json={"message": "Not Found"},
        )
        mock.add(responses.GET, base, json={"default_branch": "main", "private": False})
        mock.add(
            responses.GET,
            f"{base}/git/ref/heads/main",
            json={"ref": "refs/heads/main", "object": {"type": "commit", "sha": HEAD}},
        )
        mock.add_callback(responses.POST, f"{base}/git/trees", callback=tree_callback)
        mock.add_callback(responses.POST, f"{base}/git/commits", callback=capture("commit", 201, {"sha": commit}))
        mock.add_callback(responses.POST, f"{base}/git/refs", callback=capture("ref", 201, {"ref": "x"}))
        ref = TemplatePublisher(http, verified, DEFAULTS).publish(make_sut(tmp_path))
    assert ref.ref == commit and ref.url.endswith(f"#otterdog-defaults.libsonnet@{commit}")
    assert "base_tree" not in bodies["tree"] and bodies["commit"]["parents"] == [HEAD]
    assert bodies["ref"]["ref"].startswith("refs/tags/sut-v1.6.1-") and bodies["ref"]["sha"] == commit
