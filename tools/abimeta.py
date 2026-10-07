#!/usr/bin/env python3
"""abimeta: create and manage ABINIT/abipy feature workspaces.

A feature workspace is a clone of the meta repo on a feature branch, with full clones of the code repos
(ABINIT, abipy, ...) inside it. See plans/plan_metarepo.md for the design.

Exit codes: 0 ok, 1 user error, 2 git error, 3 doctor found errors.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import stat
import subprocess
import sys

if sys.version_info < (3, 11):
    sys.exit("abimeta needs Python 3.11 or newer")

from pathlib import Path
from typing import Any, Self

import yaml

EXIT_OK, EXIT_USER, EXIT_GIT, EXIT_DOCTOR = 0, 1, 2, 3

FEATURE_FILE = "feature.yaml"
REPOS_FILE = "repos.yaml"
META_BASE = "origin/main"
WORKSPACE_PREFIX = "meta_"
FEATURE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class UserError(Exception):
    """Wrong input or state the user can fix."""


class GitError(Exception):
    """A git command failed."""


# ---------------------------------------------------------------------------
# Output and git helpers
# ---------------------------------------------------------------------------

def info(msg: str) -> None:
    """Progress messages go to stderr, so stdout stays parseable with --json."""
    print(msg, file=sys.stderr)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def git(args: list[str], cwd: Path | None = None, quiet: bool = True, check: bool = True) -> str:
    """Run git and return stdout. Mutating calls pass quiet=False so the command is printed."""
    cmd = ["git"] + args
    if not quiet:
        where = f" (in {cwd})" if cwd else ""
        info(f"$ {' '.join(cmd)}{where}")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError(f"{' '.join(cmd)} failed in {cwd or os.getcwd()}:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def git_ok(args: list[str], cwd: Path | None = None) -> bool:
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True).returncode == 0


def ref_exists(repo: Path, ref: str) -> bool:
    return git_ok(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=repo)


def current_branch(repo: Path) -> str:
    return git(["branch", "--show-current"], cwd=repo)


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def config_path() -> Path:
    env = os.environ.get("ABINIT_METAREPO_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "abinit_metarepo" / "config.yaml"


def main_clone() -> Path:
    """The meta repo clone this script runs from."""
    return Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        raise UserError(f"{path} not found")
    except yaml.YAMLError as exc:
        raise UserError(f"cannot parse {path}: {exc}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise UserError(f"{path}: expected a mapping at top level")
    return data


def dump_yaml(data: dict[str, Any], path: Path) -> None:
    with open(path, "w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)


class Config:
    """Personal config: ~/.config/abinit_metarepo/config.yaml (never committed)."""

    def __init__(self, data: dict[str, Any], path: Path):
        self.data = data
        self.path = path

    @classmethod
    def load(cls) -> Self:
        path = config_path()
        return cls(load_yaml(path) if path.exists() else {}, path)

    @property
    def workspace_root(self) -> Path:
        root = self.data.get("workspace_root")
        return Path(root).expanduser().resolve() if root else main_clone().parent

    @property
    def meta_remote(self) -> str:
        url = self.data.get("meta_remote")
        if url:
            return url
        url = git(["remote", "get-url", "origin"], cwd=main_clone(), check=False)
        if not url:
            raise UserError(f"set meta_remote in {self.path}: the main clone has no origin remote")
        return url

    @property
    def clone_filter(self) -> str | None:
        return self.data.get("clone_filter")

    def identity(self, host: str) -> dict[str, Any]:
        ident = (self.data.get("identities") or {}).get(host)
        if not ident or not ident.get("user"):
            raise UserError(f"no identity for host {host!r}: add it under 'identities:' in {self.path}")
        return ident

    def extra_remotes(self, repo: str) -> dict[str, str]:
        """Map remote name -> username on the repo's host."""
        return (self.data.get("extra_remotes") or {}).get(repo) or {}

    def no_fork(self) -> list[str]:
        return list(self.data.get("no_fork") or [])


def convert_protocol(url: str, protocol: str | None) -> str:
    """Convert between git@host:path and https://host/path forms."""
    if protocol == "https":
        m = re.match(r"^git@([^:]+):(.+)$", url)
        if m:
            return f"https://{m.group(1)}/{m.group(2)}"
    elif protocol == "ssh":
        m = re.match(r"^https://([^/]+)/(.+)$", url)
        if m:
            return f"git@{m.group(1)}:{m.group(2)}"
    return url


def resolve_fork_url(spec: dict[str, Any], config: Config, user: str | None = None) -> str:
    template = spec.get("fork")
    if not template:
        raise UserError("repo has no fork template in repos.yaml")
    ident = config.identity(spec["host"]) if "{user}" in template else {}
    url = template.replace("{user}", user or ident.get("user", ""))
    return convert_protocol(url, ident.get("protocol"))


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

def check_feature_name(name: str) -> None:
    if not FEATURE_NAME_RE.match(name) or name.endswith(".lock") or ".." in name:
        raise UserError(f"invalid feature name {name!r}: use letters, digits, '.', '_' and '-'")


def workspace_dir(config: Config, feature: str) -> Path:
    return config.workspace_root / f"{WORKSPACE_PREFIX}{feature}"


def find_workspace(start: str | None) -> Path:
    """The workspace given with --workspace, or the one containing the current directory."""
    path = Path(start).expanduser().resolve() if start else Path.cwd().resolve()
    for cand in [path] + list(path.parents):
        if (cand / FEATURE_FILE).is_file() and is_git_repo(cand):
            return cand
    raise UserError(f"{path} is not inside a feature workspace (no {FEATURE_FILE} found)")


def load_feature(ws: Path) -> dict[str, Any]:
    data = load_yaml(ws / FEATURE_FILE)
    if not isinstance(data.get("repos"), dict):
        raise UserError(f"{ws / FEATURE_FILE}: missing 'repos:' mapping")
    return data


def other_workspaces(config: Config, exclude: Path | None = None):
    """Yield (path, feature data) for every other workspace under the workspace root."""
    root = config.workspace_root
    if not root.is_dir():
        return
    for cand in sorted(root.glob(f"{WORKSPACE_PREFIX}*")):
        if exclude is not None and cand.resolve() == exclude.resolve():
            continue
        if (cand / FEATURE_FILE).is_file():
            try:
                yield cand, load_yaml(cand / FEATURE_FILE)
            except UserError:
                continue


def branch_clashes(config: Config, ws: Path, repos: dict[str, Any]) -> list[str]:
    """Other workspaces that use the same branch for the same repo."""
    msgs = []
    for other, data in other_workspaces(config, exclude=ws):
        for name, entry in (data.get("repos") or {}).items():
            mine = repos.get(name)
            if not mine or not isinstance(entry, dict):
                continue
            if entry.get("branch") == mine.get("branch") and entry.get("branch") != base_branch(mine.get("base")):
                msgs.append(f"{name}: branch {mine['branch']!r} is also used by {other.name}")
    return msgs


def base_branch(base: str | None) -> str | None:
    """'trunk/develop' -> 'develop'."""
    return base.split("/", 1)[1] if base and "/" in base else base


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------

def parse_overrides(values: list[str] | None, what: str) -> dict[str | None, str]:
    """Parse ['NAME', 'repo=NAME', ...] into {None: NAME, 'repo': NAME}."""
    out: dict[str | None, str] = {}
    for value in values or []:
        if "=" in value:
            repo, _, val = value.partition("=")
            if not repo or not val:
                raise UserError(f"bad {what} {value!r}: expected REPO=VALUE")
            out[repo] = val
        else:
            out[None] = value
    return out


def clone_meta(config: Config, ws: Path, feature: str) -> None:
    if is_git_repo(ws):
        info(f"meta clone {ws} exists, reusing it")
        git(["fetch", "origin"], cwd=ws, quiet=False)
    else:
        if ws.exists() and any(ws.iterdir()):
            raise UserError(f"{ws} exists and is not a git repo")
        git(["clone", config.meta_remote, str(ws)], quiet=False)

    branch = current_branch(ws)
    if branch == feature:
        return
    if git_ok(["show-ref", "--verify", "--quiet", f"refs/heads/{feature}"], cwd=ws):
        git(["switch", feature], cwd=ws, quiet=False)
    elif ref_exists(ws, f"origin/{feature}"):
        info(f"meta branch {feature!r} exists on the remote: resuming that feature")
        git(["switch", "--track", f"origin/{feature}"], cwd=ws, quiet=False)
    else:
        git(["switch", "-c", feature, "--no-track", META_BASE], cwd=ws, quiet=False)


def clone_repo(config: Config, ws: Path, name: str, entry: dict[str, Any], spec: dict[str, Any]) -> None:
    """Clone one code repo into the workspace and check out its feature branch."""
    dest = ws / name
    origin = entry.get("fork") or entry["upstream"]
    origin_name = "origin" if entry.get("fork") else spec["upstream_remote"]
    filt = ["--filter", config.clone_filter] if config.clone_filter else []

    if is_git_repo(dest):
        info(f"{name}: clone exists, reusing it")
    else:
        git(["clone"] + filt + ["-o", origin_name, origin, str(dest)], quiet=False)

    remotes = git(["remote"], cwd=dest).split()
    if entry.get("fork") and spec["upstream_remote"] not in remotes:
        git(["remote", "add", spec["upstream_remote"], entry["upstream"]], cwd=dest, quiet=False)
    for rname, user in config.extra_remotes(name).items():
        if rname not in remotes:
            url = resolve_fork_url(spec, config, user=user)
            git(["remote", "add", rname, url], cwd=dest, quiet=False)
    git(["fetch"] + filt + [spec["upstream_remote"]], cwd=dest, quiet=False)

    branch, base = entry["branch"], entry["base"]
    if not ref_exists(dest, base):
        raise UserError(f"{name}: base {base!r} not found after fetch")
    if current_branch(dest) == branch:
        pass
    elif git_ok(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=dest):
        git(["switch", branch], cwd=dest, quiet=False)
    elif entry.get("fork") and ref_exists(dest, f"origin/{branch}"):
        info(f"{name}: branch {branch!r} exists on the fork, checking it out")
        git(["switch", "--track", f"origin/{branch}"], cwd=dest, quiet=False)
    else:
        git(["switch", "-c", branch, "--no-track", base], cwd=dest, quiet=False)

    if not entry.get("base_commit"):
        entry["base_commit"] = git(["merge-base", base, "HEAD"], cwd=dest)


def cmd_new(args: argparse.Namespace, config: Config) -> int:
    feature = args.feature
    check_feature_name(feature)
    ws = workspace_dir(config, feature)
    clone_meta(config, ws, feature)
    repos_spec = load_yaml(ws / REPOS_FILE)

    feature_path = ws / FEATURE_FILE
    if feature_path.exists():
        info(f"{FEATURE_FILE} exists on branch {feature!r}: using its repos and branches")
        data = load_feature(ws)
        ignored = [o for o, v in (("--repos", args.repos), ("--branch", args.branch), ("--base", args.base),
                                  ("--fork", args.fork), ("--no-fork", args.no_fork)) if v]
        if ignored:
            warn(f"ignoring {', '.join(ignored)}: the feature already exists")
        created = False
    else:
        data = new_feature_data(args, config, feature, repos_spec)
        created = True

    for name, entry in data["repos"].items():
        if name not in repos_spec:
            raise UserError(f"repo {name!r} is not listed in {REPOS_FILE}")
        clone_repo(config, ws, name, entry, repos_spec[name])

    for msg in branch_clashes(config, ws, data["repos"]):
        warn(msg + " (pushing both to the fork would clash)")

    if created:
        data["meta"]["base_commit"] = git(["merge-base", META_BASE, "HEAD"], cwd=ws)
        dump_yaml(data, feature_path)
        git(["add", FEATURE_FILE], cwd=ws, quiet=False)
        git(["commit", "-m", f"abimeta new: feature {feature}"], cwd=ws, quiet=False)

    info(f"\nworkspace ready: {ws}")
    run_doctor(ws, config, as_json=False)
    return EXIT_OK


def new_feature_data(args: argparse.Namespace, config: Config, feature: str,
                     repos_spec: dict[str, Any]) -> dict[str, Any]:
    names = [r.strip() for r in args.repos.split(",")] if args.repos else list(repos_spec)
    branches = parse_overrides(args.branch, "--branch")
    bases = parse_overrides(args.base, "--base")
    forks = parse_overrides(args.fork, "--fork")
    no_fork = set(config.no_fork()) | set(args.no_fork or [])
    for over in (branches, bases, forks):
        unknown = [r for r in over if r is not None and r not in names]
        if unknown:
            raise UserError(f"override for repo(s) not in this feature: {', '.join(unknown)}")
    if None in forks:
        raise UserError("--fork needs REPO=USER")

    repos: dict[str, Any] = {}
    for name in names:
        if name not in repos_spec:
            raise UserError(f"repo {name!r} is not listed in {REPOS_FILE}")
        spec = repos_spec[name]
        fork = None if name in no_fork else resolve_fork_url(spec, config, user=forks.get(name))
        repos[name] = {
            "branch": branches.get(name, branches.get(None, feature)),
            "fork": fork,
            "upstream": spec["upstream"],
            "base": bases.get(name, bases.get(None, spec["default_base"])),
            "base_commit": None,
            "review": None,
        }
        if not git_ok(["check-ref-format", "--branch", repos[name]["branch"]]):
            raise UserError(f"invalid branch name {repos[name]['branch']!r}")

    return {
        "name": feature,
        "description": args.description or "",
        "created": datetime.date.today().isoformat(),
        "meta": {"branch": feature, "base": META_BASE, "base_commit": None},
        "repos": repos,
        "plans": [],
        "contracts": [],
    }


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def repo_status(path: Path, base: str | None) -> dict[str, Any]:
    st: dict[str, Any] = {"path": str(path), "exists": is_git_repo(path)}
    if not st["exists"]:
        return st
    st["branch"] = current_branch(path)
    st["head"] = git(["rev-parse", "--short", "HEAD"], cwd=path)
    porcelain = git(["status", "--porcelain"], cwd=path)
    st["dirty"] = len(porcelain.splitlines()) if porcelain else 0
    st["unpushed"] = int(git(["rev-list", "--count", "HEAD", "--not", "--remotes"], cwd=path))
    st["base"] = base
    if base and ref_exists(path, base):
        behind, ahead = git(["rev-list", "--left-right", "--count", f"{base}...HEAD"], cwd=path).split()
        st["ahead"], st["behind"] = int(ahead), int(behind)
    return st


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    ws = find_workspace(args.workspace)
    data = load_feature(ws)
    result = {"workspace": str(ws), "feature": data.get("name"),
              "repos": {"meta": repo_status(ws, (data.get("meta") or {}).get("base", META_BASE))}}
    for name, entry in data["repos"].items():
        result["repos"][name] = repo_status(ws / name, entry.get("base"))
        result["repos"][name]["review"] = entry.get("review")

    if args.json:
        print(json.dumps(result, indent=2))
        return EXIT_OK

    print(f"feature {result['feature']}  ({ws})")
    for name, st in result["repos"].items():
        if not st["exists"]:
            print(f"  {name:8s} MISSING")
            continue
        vs = f"+{st['ahead']}/-{st['behind']} vs {st['base']}" if "ahead" in st else f"base {st['base']} not found"
        line = f"  {name:8s} {st['branch']:20s} {st['head']}  {vs}"
        if st["dirty"]:
            line += f"  dirty:{st['dirty']}"
        if st["unpushed"]:
            line += f"  unpushed:{st['unpushed']}"
        if st.get("review"):
            line += f"  {st['review']}"
        print(line)
    return EXIT_OK


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------

def cmd_freeze(args: argparse.Namespace, config: Config) -> int:
    """Record each repo's HEAD as pinned_commit (overwritten) and commit feature.yaml in the meta repo."""
    ws = find_workspace(args.workspace)
    data = load_feature(ws)
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    for name, entry in data["repos"].items():
        path = ws / name
        if not is_git_repo(path):
            raise UserError(f"{name}: no clone in {path}")
        if git(["status", "--porcelain", "--untracked-files=no"], cwd=path) and not args.allow_dirty:
            raise UserError(f"{name} has uncommitted changes: commit them, or pass --allow-dirty")
        entry["pinned_commit"] = git(["rev-parse", "HEAD"], cwd=path)
        entry["pinned_at"] = now
        info(f"{name}: pinned {entry['pinned_commit'][:12]}")

    dump_yaml(data, ws / FEATURE_FILE)
    if git(["status", "--porcelain", "--", FEATURE_FILE], cwd=ws):
        git(["commit", "-m", f"abimeta freeze: {data.get('name')}", "--", FEATURE_FILE], cwd=ws, quiet=False)
    else:
        info("nothing changed since the last freeze")
    return EXIT_OK


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

def unsaved_work(path: Path) -> list[str]:
    """Reasons why deleting this clone would lose work."""
    reasons = []
    if git(["status", "--porcelain"], cwd=path):
        reasons.append("uncommitted changes or untracked files")
    unpushed = git(["log", "--branches", "--not", "--remotes", "--format=%h %s"], cwd=path)
    if unpushed:
        reasons.append(f"{len(unpushed.splitlines())} unpushed commit(s), e.g. {unpushed.splitlines()[0]}")
    if git(["stash", "list"], cwd=path):
        reasons.append("stashed changes")
    return reasons


def _make_writable(func, path, _exc):
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    func(path)


def cmd_remove(args: argparse.Namespace, config: Config) -> int:
    check_feature_name(args.feature)
    ws = workspace_dir(config, args.feature)
    if not ws.exists():
        raise UserError(f"{ws} does not exist")
    if not (ws / FEATURE_FILE).is_file() or not is_git_repo(ws):
        raise UserError(f"{ws} is not a feature workspace (no {FEATURE_FILE}); refusing to delete it")
    if ws.resolve() == main_clone():
        raise UserError("refusing to delete the main clone")

    data = load_feature(ws)
    problems = []
    for name, path in [("meta", ws)] + [(n, ws / n) for n in data["repos"]]:
        if is_git_repo(path):
            problems += [f"{name}: {r}" for r in unsaved_work(path)]
    if problems:
        msg = "\n  ".join(problems)
        if not args.force:
            raise UserError(f"{ws} has work that would be lost:\n  {msg}\n"
                            f"Push it (the meta branch too, to keep {FEATURE_FILE}), or pass --force.")
        warn(f"--force: discarding\n  {msg}")

    if Path.cwd().resolve().is_relative_to(ws.resolve()):
        warn("the current directory is inside the workspace being removed")
    info(f"removing {ws}")
    if sys.version_info >= (3, 12):
        shutil.rmtree(ws, onexc=_make_writable)
    else:
        shutil.rmtree(ws, onerror=_make_writable)
    return EXIT_OK


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, str]] = []

    def add(self, level: str, check: str, msg: str = "") -> None:
        self.checks.append({"level": level, "check": check, "message": msg})

    def ok(self, check: str, msg: str = "") -> None:
        self.add("ok", check, msg)

    def warn(self, check: str, msg: str) -> None:
        self.add("warning", check, msg)

    def error(self, check: str, msg: str) -> None:
        self.add("error", check, msg)

    @property
    def has_errors(self) -> bool:
        return any(c["level"] == "error" for c in self.checks)


def claude_imports(path: Path) -> list[str]:
    """@path imports in a CLAUDE.md, skipping fenced code blocks."""
    out, fenced = [], False
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        m = re.match(r"^\s*@(\S+)\s*$", line)
        if m and not fenced:
            out.append(m.group(1))
    return out


def run_doctor(ws: Path, config: Config, as_json: bool) -> int:
    rep = Report()

    if config.path.exists():
        rep.ok("config", str(config.path))
    else:
        rep.warn("config", f"{config.path} not found")

    try:
        data = load_feature(ws)
        rep.ok("feature.yaml")
    except UserError as exc:
        rep.error("feature.yaml", str(exc))
        return finish_doctor(rep, as_json)

    meta_branch = (data.get("meta") or {}).get("branch")
    if current_branch(ws) != meta_branch:
        rep.warn("meta branch", f"on {current_branch(ws)!r}, feature.yaml says {meta_branch!r}")
    else:
        rep.ok("meta branch", meta_branch)

    gitlinks = [l for l in git(["ls-files", "-s"], cwd=ws).splitlines() if l.startswith("160000")]
    if gitlinks:
        rep.error("gitlinks", "meta repo records code repos as gitlinks: " + ", ".join(l.split()[-1] for l in gitlinks))

    for name, entry in data["repos"].items():
        path = ws / name
        check = f"repo {name}"
        if not is_git_repo(path):
            rep.error(check, f"no clone in {path}")
            continue
        if not git_ok(["check-ignore", "-q", name], cwd=ws):
            rep.error(check, f"{name}/ is not ignored by the meta repo .gitignore")
        branch = current_branch(path)
        if branch != entry.get("branch"):
            rep.warn(check, f"on branch {branch!r}, feature.yaml says {entry.get('branch')!r}")
        base = entry.get("base")
        if base and not ref_exists(path, base):
            rep.error(check, f"base {base!r} not found (fetch the remote?)")
        remotes = {}
        for rname in git(["remote"], cwd=path).split():
            remotes[rname] = git(["remote", "get-url", rname], cwd=path)
        expected = [entry.get("fork"), entry.get("upstream")]
        for url in filter(None, expected):
            if url not in remotes.values():
                rep.warn(check, f"no remote points to {url}")
        rep.ok(check, f"{branch} @ {git(['rev-parse', '--short', 'HEAD'], cwd=path)}")

    claude_md = ws / "CLAUDE.md"
    if claude_md.exists():
        missing = [p for p in claude_imports(claude_md) if not (ws / Path(p).expanduser()).exists()]
        if missing:
            rep.error("CLAUDE.md imports", "missing: " + ", ".join(missing))
        else:
            rep.ok("CLAUDE.md imports")
    else:
        rep.warn("CLAUDE.md", "not found")

    try:
        for msg in branch_clashes(config, ws, data["repos"]):
            rep.warn("branch clash", msg)
    except UserError as exc:
        rep.warn("branch clash", str(exc))

    return finish_doctor(rep, as_json)


def finish_doctor(rep: Report, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": not rep.has_errors, "checks": rep.checks}, indent=2))
    else:
        marks = {"ok": "ok  ", "warning": "WARN", "error": "FAIL"}
        for c in rep.checks:
            msg = f" {c['message']}" if c["message"] else ""
            info(f"[{marks[c['level']]}] {c['check']}:{msg}")
    return EXIT_DOCTOR if rep.has_errors else EXIT_OK


def cmd_doctor(args: argparse.Namespace, config: Config) -> int:
    return run_doctor(find_workspace(args.workspace), config, as_json=args.json)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abimeta", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="create (or resume) a feature workspace")
    p.add_argument("feature")
    p.add_argument("--repos", help="comma-separated repos (default: all in repos.yaml)")
    p.add_argument("--branch", action="append", metavar="[REPO=]NAME",
                   help="branch name for all repos, or for one repo (default: the feature name)")
    p.add_argument("--base", action="append", metavar="[REPO=]REF", help="base ref (default: default_base)")
    p.add_argument("--fork", action="append", metavar="REPO=USER", help="use USER's fork for REPO")
    p.add_argument("--no-fork", action="append", metavar="REPO",
                   help="clone REPO from the official repo and push there (no fork)")
    p.add_argument("--description", "-d", help="one-line description for feature.yaml")
    p.set_defaults(func=cmd_new)

    for name, func, help_ in [("status", cmd_status, "branch, ahead/behind, dirty and unpushed per repo"),
                              ("doctor", cmd_doctor, "check the workspace")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--workspace", "-w", help="workspace path (default: the one containing cwd)")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        p.set_defaults(func=func)

    p = sub.add_parser("freeze", help="record each repo's HEAD in feature.yaml and commit it")
    p.add_argument("--workspace", "-w", help="workspace path (default: the one containing cwd)")
    p.add_argument("--allow-dirty", action="store_true", help="pin even with uncommitted changes")
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("remove", help="delete a feature workspace if no work would be lost")
    p.add_argument("feature")
    p.add_argument("--force", action="store_true", help="delete even with uncommitted or unpushed work")
    p.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, Config.load())
    except UserError as exc:
        print(f"abimeta: {exc}", file=sys.stderr)
        return EXIT_USER
    except GitError as exc:
        print(f"abimeta: {exc}", file=sys.stderr)
        return EXIT_GIT


if __name__ == "__main__":
    sys.exit(main())
