# abinit_metarepo

A meta repo for developing features that span [ABINIT](https://gitlab.uliege.be/abinit/developers/trunk/abinit)
and [abipy](https://github.com/abinit/abipy) with Claude Code.

It holds **no application code**: only agent instructions (`AGENTS.md`, `CLAUDE.md`), plans, cross-repo contracts
and the `abimeta` tool. Each feature gets its own **workspace**: a clone of this repo on a feature branch, with full
clones of ABINIT and abipy inside it, each on its own feature branch.

```text
~/git_repos/
├── abinit_metarepo/      # main clone: runs abimeta, shared config is edited here
└── meta_gwr-mem/         # workspace for feature "gwr-mem" (meta repo on branch gwr-mem)
    ├── AGENTS.md         # cross-repo instructions for the agent
    ├── CLAUDE.md
    ├── feature.yaml      # what the feature is built on: branches, forks, base commits
    ├── repos.yaml        # the repos abimeta manages
    ├── plans/  contracts/
    ├── abinit/           # full clone, branch gwr-mem (ignored by the meta repo)
    └── abipy/            # full clone, branch gwr-mem (ignored by the meta repo)
```

The design and its status are in [plans/plan_metarepo.md](plans/plan_metarepo.md).

## Requirements

- git
- Python 3.11 or newer (PyYAML is installed by the bootstrap script)
- SSH access to your ABINIT fork on gitlab.uliege.be and to GitHub (or HTTPS, see the config below)

## Setup (once per machine)

1. Clone this repo; this clone is the **main clone**:

   ```sh
   git clone git@github.com:abinit/abinit_metarepo.git
   cd abinit_metarepo
   tools/bootstrap.sh
   ```

   `bootstrap.sh` creates a small venv in `~/.config/abinit_metarepo/venv`, installs the `abimeta` command in
   `~/.local/bin` (make sure it is on your `PATH`) and writes a config template. Rerunning it is safe. If it cannot
   find Python 3.11+, point it to one: `ABIMETA_PYTHON=/path/to/python3.11 tools/bootstrap.sh`.

2. Edit `~/.config/abinit_metarepo/config.yaml` and replace the `CHANGEME` usernames:

   ```yaml
   identities:
     gitlab.uliege.be: { user: gmatteo, protocol: ssh }   # your ABINIT fork: abinit/developers/<user>/abinit
     github.com:       { user: gmatteo, protocol: ssh }   # your abipy fork: <user>/abipy
   ```

   Optional settings, all commented in the template:

   | Key | Purpose |
   |---|---|
   | `workspace_root` | where `meta_<feature>/` workspaces go (default: next to the main clone) |
   | `no_fork: [abipy]` | repos you push to directly instead of through a fork |
   | `extra_remotes` | colleagues' forks to add as remotes, e.g. `abinit: { hexu: X.He }` |
   | `clone_filter: blob:none` | partial clones: faster and smaller (the ABINIT history is about 640 MB) |
   | `meta_remote` | URL of this repo (default: the main clone's `origin`) |

   The config file is personal and never committed. `ABINIT_METAREPO_CONFIG=/path/config.yaml` uses another one.

### How abimeta knows what to clone

Two files are combined:

| File | Edited by | Contents |
|---|---|---|
| [`repos.yaml`](repos.yaml) (shared, in this repo) | rarely, via `main` | per repo: `host`, official URL and remote name, fork URL **template** with `{user}`, default base |
| `~/.config/abinit_metarepo/config.yaml` (personal) | you, once per machine | your username and protocol per host, `no_fork`, `extra_remotes`, ... |

`abimeta` fills `{user}` in the fork template with your username for that host. `protocol: https` turns the template's
`git@host:path` form into `https://host/path`. For example, with `user: gmatteo, protocol: https` on
gitlab.uliege.be, `extra_remotes: { abinit: { hexu: X.He } }` and `no_fork: [abipy]`, `abimeta new gwr-mem` runs
the equivalent of:

```sh
# ABINIT: your fork is origin, the official repo is trunk
git clone -o origin https://gitlab.uliege.be/abinit/developers/gmatteo/abinit.git abinit
git -C abinit remote add trunk https://gitlab.uliege.be/abinit/developers/trunk/abinit.git
git -C abinit remote add hexu https://gitlab.uliege.be/abinit/developers/X.He/abinit.git
git -C abinit fetch trunk
git -C abinit switch -c gwr-mem --no-track trunk/develop

# abipy, listed in no_fork: the official repo is the only remote
git clone -o upstream https://github.com/abinit/abipy.git abipy
git -C abipy fetch upstream
git -C abipy switch -c gwr-mem --no-track upstream/develop
```

The base branch always comes from the official repo, so it does not matter if your fork is behind. The URLs that
were actually used are recorded in `feature.yaml`. You only edit `repos.yaml` to add a repo or to change an official
URL or default base; that change goes to `main` and applies to everyone.

## Working on a feature

```sh
abimeta new gwr-mem -d "Reduce memory footprint of GWR"
cd ../meta_gwr-mem
claude
```

`abimeta new` clones the meta repo and creates branch `gwr-mem`. It then clones ABINIT and abipy from your forks,
adds the official repos as `trunk` (ABINIT) and `upstream` (abipy), and creates branch `gwr-mem` in each from
`trunk/develop` and `upstream/develop`. Finally it records all this in `feature.yaml`, commits it and runs
`abimeta doctor`.

Useful options:

| Option | Effect |
|---|---|
| `--repos abinit` | only clone some repos |
| `--branch abipy=develop` | use another branch for one repo (or `--branch NAME` for all) |
| `--base abinit=trunk/some-branch` | start a branch from another ref |
| `--fork abinit=hexu` | work on a branch in someone else's fork |
| `--no-fork abipy` | clone the official repo and push there |

Start Claude Code at the **workspace root**: it reads `AGENTS.md` there, and the ABINIT or abipy instructions and
skills when it works inside `abinit/` or `abipy/`.

Git rules: `abinit/` and `abipy/` are separate repos. Commit and push inside each one as usual
(`git -C abinit push -u origin gwr-mem`). The meta repo only tracks the feature's plans, contracts and
`feature.yaml`. Push its branch too (`git push -u origin gwr-mem`): it is the record of the feature.

### Commands

Run them from anywhere inside a workspace, or pass `--workspace PATH`.

| Command | What it does |
|---|---|
| `abimeta status [--json]` | branch, commits ahead/behind the base, uncommitted and unpushed work, per repo |
| `abimeta doctor [--json]` | checks branches, remotes, ignores and `CLAUDE.md` imports; exits 3 on errors |
| `abimeta freeze` | records each repo's current commit in `feature.yaml` and commits it, e.g. before generating reference data |
| `abimeta remove <feature>` | deletes the workspace, refusing if any repo has uncommitted, unpushed or stashed work |

`remove --force` deletes anyway. Exit codes: 0 ok, 1 user error, 2 git error, 3 `doctor` found errors.

### Continuing a feature on another machine

Push the meta branch and the code branches, then on the other machine (after the one-time setup) run the same
command:

```sh
abimeta new gwr-mem
```

If the meta branch already exists on the remote, `abimeta new` uses its `feature.yaml` and checks out the existing
branches instead of creating new ones.

## Changing the shared setup

Improvements to instructions, skills or `abimeta` itself go to `main` of this repo, through the main clone. Feature
branches of the meta repo are never merged into `main`.

Run the tests before pushing changes to `abimeta`:

```sh
~/.config/abinit_metarepo/venv/bin/python -m pip install pytest   # or: tools/bootstrap.sh --dev
~/.config/abinit_metarepo/venv/bin/python -m pytest tests
```

The tests use local repos as remotes and need no network. CI runs them on Python 3.11 and 3.14.

## Status

Phases 1–2 of the plan are implemented: workspace creation, status, freeze, remove and doctor. Not yet available:
per-feature Python env and ABINIT build (Phase 3), shared skills, subagents and safety hooks (Phase 4), and
`abimeta sync` to bring `main` updates into a feature (Phase 5).
