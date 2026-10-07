import json

import yaml

import abimeta
from conftest import commit_file, git


def feature_yaml(ws):
    return yaml.safe_load((ws / "feature.yaml").read_text())


def meta_commits(ws):
    return git("rev-list", "--count", "origin/main..HEAD", cwd=ws)


def test_new_creates_workspace(sandbox, run):
    code, _, err = run("new", "demo", "-d", "a demo")
    assert code == 0, err
    ws = sandbox.ws("demo")

    assert git("branch", "--show-current", cwd=ws) == "demo"
    for name, upstream_remote in (("abinit", "trunk"), ("abipy", "upstream")):
        repo = ws / name
        assert git("branch", "--show-current", cwd=repo) == "demo"
        assert git("remote", "get-url", "origin", cwd=repo) == str(sandbox.fork("alice", name))
        assert git("remote", "get-url", upstream_remote, cwd=repo) == str(sandbox.upstream(name))
        # The branch starts from the official repo, which is ahead of the fork.
        assert git("rev-parse", "HEAD", cwd=repo) == sandbox.upstream_head[name]

    data = feature_yaml(ws)
    assert data["name"] == "demo" and data["description"] == "a demo"
    assert data["repos"]["abinit"]["base"] == "trunk/develop"
    assert data["repos"]["abinit"]["base_commit"] == sandbox.upstream_head["abinit"]
    assert data["repos"]["abinit"]["fork"] == str(sandbox.fork("alice", "abinit"))
    assert "review" in data["repos"]["abipy"]
    # feature.yaml is committed on the meta feature branch, and the code repos are not tracked.
    assert meta_commits(ws) == "1"
    assert git("status", "--porcelain", cwd=ws) == ""
    assert "[FAIL]" not in err


def test_new_is_idempotent(sandbox, run):
    assert run("new", "demo")[0] == 0
    code, _, err = run("new", "demo")
    assert code == 0, err
    assert meta_commits(sandbox.ws("demo")) == "1"


def test_status_json(sandbox, run):
    run("new", "demo")
    ws = sandbox.ws("demo")
    commit_file(ws / "abinit", "src.F90", "x\n", "work")
    (ws / "abipy" / "scratch.py").write_text("y\n")

    code, out, _ = run("status", "--json", "-w", str(ws))
    assert code == 0
    st = json.loads(out)["repos"]
    assert st["abinit"]["ahead"] == 1 and st["abinit"]["behind"] == 0
    assert st["abinit"]["unpushed"] == 1 and st["abinit"]["dirty"] == 0
    assert st["abipy"]["dirty"] == 1 and st["abipy"]["unpushed"] == 0
    assert st["meta"]["branch"] == "demo" and st["meta"]["unpushed"] == 1


def test_status_finds_workspace_from_cwd(sandbox, run, monkeypatch):
    run("new", "demo")
    monkeypatch.chdir(sandbox.ws("demo") / "abinit")
    code, out, _ = run("status")
    assert code == 0 and "feature demo" in out


def test_remove_refuses_unpushed_meta_branch(sandbox, run):
    run("new", "demo")
    ws = sandbox.ws("demo")
    code, _, err = run("remove", "demo")
    assert code == abimeta.EXIT_USER
    assert "meta: 1 unpushed commit" in err and ws.exists()

    git("push", "-q", "-u", "origin", "demo", cwd=ws)
    code, _, err = run("remove", "demo")
    assert code == 0, err
    assert not ws.exists()


def test_remove_refuses_dirty_or_unpushed_code(sandbox, run):
    run("new", "demo")
    ws = sandbox.ws("demo")
    git("push", "-q", "-u", "origin", "demo", cwd=ws)
    (ws / "abipy" / "new.py").write_text("x\n")
    commit_file(ws / "abinit", "a.F90", "a\n", "work")

    code, _, err = run("remove", "demo")
    assert code == abimeta.EXIT_USER
    assert "abipy: uncommitted changes" in err and "abinit: 1 unpushed commit" in err

    code, _, _ = run("remove", "demo", "--force")
    assert code == 0 and not ws.exists()


def test_new_then_remove_force_leaves_nothing(sandbox, run):
    run("new", "demo")
    assert run("remove", "demo", "--force")[0] == 0
    assert list(sandbox.ws_root.iterdir()) == []


def test_remove_refuses_non_workspace(sandbox, run):
    (sandbox.ws_root / "meta_other").mkdir()
    code, _, err = run("remove", "other")
    assert code == abimeta.EXIT_USER and "not a feature workspace" in err


def test_branch_clash_warning(sandbox, run):
    run("new", "one", "--branch", "shared")
    code, _, err = run("new", "two", "--branch", "shared")
    assert code == 0
    assert "branch 'shared' is also used by meta_one" in err


def test_no_clash_warning_for_base_branch(sandbox, run):
    run("new", "one", "--branch", "abipy=develop")
    _, _, err = run("new", "two", "--branch", "abipy=develop")
    assert "also used by" not in err
    assert git("branch", "--show-current", cwd=sandbox.ws("two") / "abipy") == "develop"
    assert git("branch", "--show-current", cwd=sandbox.ws("two") / "abinit") == "two"


def test_freeze(sandbox, run):
    run("new", "demo")
    ws = sandbox.ws("demo")
    head = commit_file(ws / "abinit", "a.F90", "a\n", "work")

    code, _, err = run("freeze", "-w", str(ws))
    assert code == 0, err
    data = feature_yaml(ws)
    assert data["repos"]["abinit"]["pinned_commit"] == head
    assert data["repos"]["abipy"]["pinned_commit"] == sandbox.upstream_head["abipy"]
    assert meta_commits(ws) == "2"
    assert git("status", "--porcelain", cwd=ws) == ""

    (ws / "abinit" / "a.F90").write_text("changed\n")
    code, _, err = run("freeze", "-w", str(ws))
    assert code == abimeta.EXIT_USER and "uncommitted changes" in err
    assert run("freeze", "-w", str(ws), "--allow-dirty")[0] == 0


def test_resume_existing_feature(sandbox, run):
    run("new", "demo")
    ws = sandbox.ws("demo")
    head = commit_file(ws / "abinit", "a.F90", "a\n", "work")
    git("push", "-q", "-u", "origin", "demo", cwd=ws / "abinit")
    git("push", "-q", "-u", "origin", "demo", cwd=ws)
    assert run("remove", "demo")[0] == 0

    # e.g. on another machine: the meta branch and the fork branch already exist.
    code, _, err = run("new", "demo", "--branch", "ignored")
    assert code == 0, err
    assert "ignoring --branch" in err
    assert git("rev-parse", "HEAD", cwd=ws / "abinit") == head
    assert git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=ws / "abinit") == "origin/demo"
    assert git("status", "-sb", cwd=ws).startswith("## demo...origin/demo")


def test_no_fork_and_fork_override(sandbox, run):
    code, _, err = run("new", "demo", "--no-fork", "abipy", "--fork", "abinit=bob")
    assert code == 0, err
    ws = sandbox.ws("demo")
    assert git("remote", cwd=ws / "abipy").split() == ["upstream"]
    assert git("remote", "get-url", "origin", cwd=ws / "abinit") == str(sandbox.fork("bob", "abinit"))
    data = feature_yaml(ws)
    assert data["repos"]["abipy"]["fork"] is None


def test_extra_remotes(sandbox, run):
    sandbox.config["extra_remotes"] = {"abinit": {"bobfork": "bob"}}
    sandbox.write_config()
    run("new", "demo", "--repos", "abinit")
    ws = sandbox.ws("demo")
    assert git("remote", "get-url", "bobfork", cwd=ws / "abinit") == str(sandbox.fork("bob", "abinit"))
    assert not (ws / "abipy").exists()
    assert list(feature_yaml(ws)["repos"]) == ["abinit"]


def test_doctor_detects_problems(sandbox, run):
    run("new", "demo")
    ws = sandbox.ws("demo")
    assert run("doctor", "-w", str(ws))[0] == 0

    (ws / "CLAUDE.md").write_text("@AGENTS.md\n@abipy/AGENTS.md\n\n```\n@not/an/import\n```\n")
    (ws / ".gitignore").write_text("/abinit/\n")
    code, out, _ = run("doctor", "-w", str(ws), "--json")
    assert code == abimeta.EXIT_DOCTOR
    report = json.loads(out)
    errors = {c["check"]: c["message"] for c in report["checks"] if c["level"] == "error"}
    assert errors["CLAUDE.md imports"] == "missing: abipy/AGENTS.md"
    assert "not ignored" in errors["repo abipy"]


def test_user_errors(sandbox, run):
    assert run("new", "bad/name")[0] == abimeta.EXIT_USER
    assert run("new", "demo", "--repos", "nope")[0] == abimeta.EXIT_USER
    assert run("status", "-w", str(sandbox.root))[0] == abimeta.EXIT_USER

    sandbox.config["identities"] = {}
    sandbox.write_config()
    code, _, err = run("new", "demo2")
    assert code == abimeta.EXIT_USER and "no identity for host" in err


def test_convert_protocol():
    ssh = "git@gitlab.uliege.be:abinit/developers/u/abinit.git"
    https = "https://gitlab.uliege.be/abinit/developers/u/abinit.git"
    assert abimeta.convert_protocol(ssh, "https") == https
    assert abimeta.convert_protocol(https, "ssh") == ssh
    assert abimeta.convert_protocol(ssh, None) == ssh
    assert abimeta.convert_protocol("/local/path.git", "https") == "/local/path.git"
