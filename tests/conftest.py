"""Fixtures: a sandbox with local bare repos standing in for the meta, ABINIT and abipy remotes (no network)."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import abimeta  # noqa: E402

HOST = "forge.example"


def git(*args, cwd=None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr}"
    return proc.stdout.strip()


def commit_file(repo: Path, name: str, content: str, msg: str) -> str:
    (repo / name).write_text(content)
    git("add", name, cwd=repo)
    git("commit", "-q", "-m", msg, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


class Sandbox:
    """Remotes, personal config and workspace root under one tmp dir."""

    def __init__(self, root: Path):
        self.root = root
        self.ws_root = root / "ws"
        self.ws_root.mkdir()
        self.config_path = root / "config.yaml"
        self.config = {
            "identities": {HOST: {"user": "alice"}},
            "workspace_root": str(self.ws_root),
            "meta_remote": str(root / "remotes" / "meta.git"),
        }
        self.write_config()
        self.upstream_head = {}
        for name in ("abinit", "abipy"):
            self.make_code_remote(name)
        self.make_meta_remote()

    def write_config(self) -> None:
        abimeta.dump_yaml(self.config, self.config_path)

    def upstream(self, name: str) -> Path:
        return self.root / "remotes" / "official" / f"{name}.git"

    def fork(self, user: str, name: str) -> Path:
        return self.root / "remotes" / "forks" / user / f"{name}.git"

    def make_code_remote(self, name: str) -> None:
        work = self.root / "src" / name
        work.mkdir(parents=True)
        git("init", "-q", "-b", "develop", cwd=work)
        commit_file(work, "README", f"{name}\n", "initial")
        git("clone", "-q", "--bare", str(work), str(self.upstream(name)))
        for user in ("alice", "bob"):
            git("clone", "-q", "--bare", str(self.upstream(name)), str(self.fork(user, name)))
        # Upstream moves on after the forks were made: the base must come from upstream, not the fork.
        commit_file(work, "README", f"{name} v2\n", "upstream progress")
        git("push", "-q", str(self.upstream(name)), "develop", cwd=work)
        self.upstream_head[name] = git("rev-parse", "HEAD", cwd=work)

    def make_meta_remote(self) -> None:
        work = self.root / "src" / "meta"
        work.mkdir(parents=True)
        git("init", "-q", "-b", "main", cwd=work)
        forks = self.root / "remotes" / "forks"
        repos = {
            "abinit": {
                "host": HOST, "upstream_remote": "trunk", "upstream": str(self.upstream("abinit")),
                "fork": f"{forks}/{{user}}/abinit.git", "default_base": "trunk/develop",
            },
            "abipy": {
                "host": HOST, "upstream_remote": "upstream", "upstream": str(self.upstream("abipy")),
                "fork": f"{forks}/{{user}}/abipy.git", "default_base": "upstream/develop",
            },
        }
        abimeta.dump_yaml(repos, work / "repos.yaml")
        (work / ".gitignore").write_text("/abinit/\n/abipy/\n/build/\n/.venv/\n")
        (work / "AGENTS.md").write_text("# test\n")
        (work / "CLAUDE.md").write_text("@AGENTS.md\n")
        git("add", ".", cwd=work)
        git("commit", "-q", "-m", "meta skeleton", cwd=work)
        git("clone", "-q", "--bare", str(work), self.config["meta_remote"])

    def ws(self, feature: str) -> Path:
        return self.ws_root / f"meta_{feature}"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Test\n\temail = test@example.org\n"
                         "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    sb = Sandbox(tmp_path)
    monkeypatch.setenv("ABINIT_METAREPO_CONFIG", str(sb.config_path))
    monkeypatch.chdir(tmp_path)
    return sb


@pytest.fixture
def run(capsys):
    """Run abimeta in-process; return (exit code, stdout, stderr)."""
    def _run(*argv):
        code = abimeta.main(list(argv))
        out, err = capsys.readouterr()
        return code, out, err
    return _run
