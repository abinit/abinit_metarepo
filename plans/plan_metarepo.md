# Meta-repo plan for ABINIT / abipy multi-repo development

*7 Oct 2026 · @Matteo*

**Contents**

1. [Context and goals](#1-context-and-goals)
2. [Design overview](#2-design-overview)
3. [Feature manifest](#3-feature-manifest)
4. [Agent configuration](#4-agent-configuration)
5. [The `metactl` CLI](#5-the-metactl-cli)
6. [Environments](#6-environments)
7. [Implementation phases](#7-implementation-phases)
8. [Things to verify and open decisions](#8-things-to-verify-and-open-decisions)
9. [Review findings (to address)](#9-review-findings-to-address)

---

## 1. Context and goals

We will build a home-made meta repo (`abinit_metarepo`) that holds **no application code**: only the agent
configuration, plans and tooling needed to develop features spanning ABINIT and abipy with Claude Code.
Each feature gets its own clone of the meta repo, with ABINIT and abipy checked out inside it on feature branches.

### Goals

- **One command** creates a ready-to-work feature workspace: meta clone, ABINIT and abipy on feature branches,
  Python env, build dir.
- **Shared agent config:** cross-repo instructions, skills, subagents and plans live in one versioned place and
  are shared by every feature.
- **Reuse, don't modify:** `AGENTS.md` files and skills shipped by ABINIT and abipy are reused as-is, without
  committing anything to those repos.
- **Third-party skills** from GitHub can be added, pinned and reviewed.
- **Traceability:** every feature records which ABINIT/abipy branches and base commits it was built on.
- **Portability:** works the same on a laptop and on the Slurm cluster.

### Non-goals (for now)

- No buildbot/testbot integration.
- No support for other agents beyond keeping `AGENTS.md` as the shared source.
- No GUI; CLI only.

### How Claude Code should use this plan

- Implement **phase by phase** (see [Implementation phases](#7-implementation-phases)); stop after each phase for review.
- **Verify every assumption** in [Things to verify](#8-things-to-verify-and-open-decisions) against the real repos
  and the installed Claude Code version before relying on it. Do not invent paths, flags or file names.
- Prefer **small, boring tooling**: one Python CLI, standard library plus PyYAML.
- **Keep this file updated:** tick off tasks and record decisions as they are made.

---

## 2. Design overview

A feature workspace is a clone of the meta repo on a feature branch, with full, independent clones of ABINIT and
abipy inside it. The clones are untracked by the meta repo, so each feature is self-contained and can be moved or
deleted on its own.

```text
~/dev/
├── abinit_metarepo/            # main clone of the meta repo (runs metactl, edit shared config here)
└── meta_gwr-mem/               # one feature workspace = meta clone on branch gwr-mem
    ├── CLAUDE.md               # imports AGENTS.md files (see Agent configuration)
    ├── AGENTS.md               # cross-repo instructions (source of truth)
    ├── feature.yaml            # manifest: repos, branches, base commits
    ├── repos.yaml              # list of managed repos + remotes (shared)
    ├── plans/                  # shared plans + this feature's plan
    ├── contracts/              # cross-repo interface specs
    ├── config/hosts/           # per-host configure options and Slurm settings
    ├── .claude/
    │   ├── settings.json       # permissions, hooks, plugin marketplaces
    │   ├── skills/             # own skills + generated links to repo skills + vendored skills
    │   ├── agents/             # subagents (abinit-dev, abipy-dev, reviewer)
    │   └── hooks/              # hook scripts
    ├── skills.lock.yaml        # pinned third-party skills
    ├── tools/metactl.py        # the CLI
    ├── abinit/                 # full clone, branch gwr-mem     (untracked by meta)
    ├── abipy/                  # full clone, branch gwr-mem     (untracked by meta)
    ├── build/<host>/           # ABINIT out-of-tree build       (untracked)
    └── .venv/                  # per-feature Python env         (untracked)
```

### Key decisions

| Decision | Details |
|---|---|
| **Meta repo per feature** | Clone the meta repo once per feature and create a meta branch with the same name. Feature plans, the manifest and feature-specific tweaks are committed there. Feature meta branches are **never merged into `main`**. Generic improvements (skills, hooks, `metactl`) go to `main`: commit them in the feature clone, push or cherry-pick them to `main`, and other features pick them up with `metactl sync`. |
| **Code repos as full clones** | `metactl new` clones each repo from the user's fork (`origin`) into the feature directory and adds `upstream` for the official repo. Nothing is shared between features. An optional `--reference-dir` can speed up cloning from a local copy; it is off by default. |
| **Same branch name everywhere** (default) | Feature `gwr-mem` uses branch `gwr-mem` in meta, ABINIT and abipy. A repo may override it in `feature.yaml` (e.g. abipy stays on `develop`). |
| **Start Claude Code at the workspace root** | Root instructions and skills then apply everywhere; nested `CLAUDE.md` files and `.claude/skills/` in the repos load when Claude works in those directories. |
| **The meta repo ignores the code** | `.gitignore` lists `abinit/`, `abipy/`, `.venv/` and `build/`, plus the generated skill symlinks (`.claude/skills/abinit-*`, `.claude/skills/abipy-*`). |
| **Bootstrap** | `metactl` runs from the main clone (`abinit_metarepo`) in a small tooling venv with PyYAML; `tools/bootstrap.sh` creates it and puts a `metactl` wrapper on `PATH`. Feature clones are cloned from the meta remote on GitHub, so generic fixes must be pushed to `main` before `metactl sync` can bring them in. |

---

## 3. Feature manifest

### `feature.yaml`

Committed on the meta feature branch; the **single record of what a feature is built on**. `metactl` writes it at
creation and updates the recorded commits on request.

```yaml
# illustrative values
name: gwr-mem
description: Reduce memory footprint of GWR (W streaming over q)
created: 2026-10-07

repos:
  abinit:
    branch: gwr-mem
    base: upstream/develop        # where the branch was created from
    base_commit: <sha>            # filled by metactl
  abipy:
    branch: develop               # override: no feature branch in abipy
    base: upstream/develop
    base_commit: <sha>

env:
  python: "3.12"
  abinit_config: config/hosts/<host>.ac9     # host-specific configure options
  abinit_configure_extra:                    # per-feature additions
    - enable_gw_dpc="yes"

plans:
  - plans/gwr_memory.md

contracts:
  - contracts/gwr-netcdf-output.md
```

### `repos.yaml`

Shared, on meta `main`. Lists every repo the meta repo can manage, so adding a third repo later needs no code change.

```yaml
# {github_user} comes from ~/.config/metactl.yaml, so this file can be shared
abinit:
  origin: git@github.com:{github_user}/abinit.git
  upstream: https://github.com/abinit/abinit.git
  default_base: upstream/develop      # verify

abipy:
  origin: git@github.com:{github_user}/abipy.git
  upstream: https://github.com/abinit/abipy.git
  default_base: upstream/develop      # verify
  python_install: editable
```

### `metactl freeze`

Records the current `HEAD` of each repo into `feature.yaml` (as `pinned_commit`), so results such as reference
outputs can be tied to an exact ABINIT/abipy pair.

---

## 4. Agent configuration

> `AGENTS.md` is the source of truth for instructions; `CLAUDE.md` only imports.
> Nothing is ever written into the ABINIT or abipy repos except code.

### 4.1 Instructions

- **Root `AGENTS.md`** (meta): repo map, how the repos connect, git rules (*"`abinit/` and `abipy/` are separate
  repos; run git inside the right one"*), cluster rules, where plans and contracts live. Keep it short.
- **Root `CLAUDE.md`** (meta, committed):

  ```markdown
  @AGENTS.md
  @abinit/AGENTS.md
  @abipy/AGENTS.md

  ## Claude Code specifics
  - Active plans: see feature.yaml `plans:`; read them when relevant, do not import them.
  - When compacting, keep the list of modified files per repo and the test commands.
  ```

- The repo imports work only if those files exist; `metactl doctor` warns when an import target is missing.
- Personal, uncommitted notes go in `CLAUDE.local.md` at the workspace root (gitignored).

### 4.2 Skills

| Source | Location in workspace | How it gets there |
|---|---|---|
| Own integration skills | `.claude/skills/meta-<name>/` | Committed in meta |
| Repo-provided skills in `.claude/skills/` | `abinit/.claude/skills/`, `abipy/.claude/skills/` | Found by Claude Code when working in those dirs; nothing to do *(verify)* |
| Repo-provided skills elsewhere | `.claude/skills/abinit-<name>`, `.claude/skills/abipy-<name>` (symlinks) | Generated by `metactl skills link` during `new`; gitignored, because the targets exist only in feature clones |
| Third-party plain skills | `.claude/skills/vendor-<name>/` | Copied at a pinned commit by `metactl skills sync` from `skills.lock.yaml`; committed |
| Third-party plugins | Plugin cache | `extraKnownMarketplaces` + `enabledPlugins` in `.claude/settings.json`; `metactl new` runs the project-scope install |

- **Prefixes are mandatory:** `meta-` for own skills, `abinit-`/`abipy-` for links to repo skills, `vendor-` for
  third-party. Same-named skills shadow each other by scope.
- **`skills.lock.yaml` entries:** `repo`, `path`, `commit`, `name`, `reviewed_by`, `notes`.
  Updating = bump commit, review diff, commit.
- **Planned own skills:** `meta-abinit-tests`, `meta-param-tests`, `meta-inputvar-lookup`,
  `meta-build-submit-check` (Slurm), `meta-abipy-parser-update`.

### 4.3 Subagents (`.claude/agents/`)

| Agent | Scope |
|---|---|
| `abinit-dev` | Works only inside `abinit/`; knows the build and test commands. |
| `abipy-dev` | Works only inside `abipy/`; knows pytest and the editable install. |
| `reviewer` | Read-only; reviews a diff against the plan and the contract; reports gaps, not style. |

### 4.4 Hooks (`.claude/settings.json` + `.claude/hooks/`)

1. **Login-node guard** — `PreToolUse` on `Bash`, active only on login nodes (detected from
   `config/hosts/<host>.yaml`, e.g. a hostname pattern and no `SLURM_JOB_ID`).
   - Block commands that launch `mpirun`/`mpiexec`, run the `abinit` executable, or run `make` with more than
     4 jobs, unless they go through `srun` or `sbatch`.
   - Match executable tokens, not substrings: `cd abinit`, `git -C abinit status` and `ls abinit/` must pass.
2. **Wrong-repo guard** — `PreToolUse` on `Bash`: at the workspace root, block `git add -f/--force` of paths
   under `abinit/` or `abipy/`, and any meta commit that would record them as gitlinks.
3. **Hooks are a safety net, not the only control.** Keep a table of commands that must pass and must be blocked,
   and test the hooks against it.

### 4.5 Plans and contracts

- **`plans/`** holds shared plans (on `main`) and feature plans (on the feature branch).
  Plans are referenced, never imported.
- **`contracts/<topic>.md`** specifies an interface between repos (e.g. a new netCDF variable written by ABINIT
  and parsed by abipy): owner, consumers, format, status, test that proves it. Both subagents implement against
  the contract.

---

## 5. The `metactl` CLI

`tools/metactl.py` is a single Python file (stdlib + PyYAML) with subcommands. Every command is **idempotent** and
**prints what it does**. It never pushes, deletes branches or force-anything without an explicit flag.

### Commands

| Command | What it does |
|---|---|
| `metactl new <feature> [--repos abinit,abipy] [--branch NAME] [--base REF]` | Clone meta into `../meta_<feature>`, create meta branch, clone each repo and create its feature branch, write `feature.yaml`, create venv, install abipy editable, link skills, install plugins, run `doctor` |
| `metactl status` | Branch, ahead/behind vs base, dirty files, for meta and each repo |
| `metactl sync [--rebase]` | Fetch all remotes; pull meta `main` into the feature; optionally rebase repo branches on their base |
| `metactl exec -- <cmd>` | Run a command in every repo clone (e.g. `git log -1`) |
| `metactl freeze` | Record each repo's `HEAD` as `pinned_commit` in `feature.yaml` |
| `metactl add-repo <name>` / `remove-repo <name>` | Add or drop a repo in an existing feature |
| `metactl skills link` | Create/refresh symlinks to repo-provided skills |
| `metactl skills sync` | Copy pinned third-party skills from `skills.lock.yaml`; show diff on version bumps |
| `metactl doctor` | Check imports resolve, symlinks valid, venv ok, abipy importable from this workspace, hooks executable |
| `metactl remove <feature> [--delete-branches]` | Delete the workspace directory after checking nothing is uncommitted or unpushed |

### Behaviour rules

- **Branch clash warning:** warn when another workspace under the workspace root already uses the same branch name
  for a repo, since pushing both to the fork would clash.
- **Safe remove:** `remove` refuses if any repo has uncommitted or unpushed work, unless `--force`.
- **No hard-coded paths:** all paths come from `repos.yaml`, `feature.yaml` and one config file
  `~/.config/metactl.yaml` (workspace root, host name, GitHub user, meta remote URL, optional reference dir).
- **Machine-readable output:** exit codes `0` ok, `1` user error, `2` git error; `--json` output for `status` and
  `doctor` so Claude Code can parse them.

---

## 6. Environments

Each feature has its own Python env and its own ABINIT build, so features never import or link each other's code.

### 6.1 Python

- `.venv/` per workspace; abipy installed editable from `./abipy`. `doctor` checks that `import abipy` resolves
  inside this workspace.
- Pin the Python version in `feature.yaml`; prefer `uv` if available, else `python -m venv`.

### 6.2 ABINIT build

- Out-of-tree build in `build/<host>/` at the workspace root (gitignored), so the ABINIT clone stays clean.
- Configure from `config/hosts/<host>.ac9` in the meta repo plus `abinit_configure_extra` from `feature.yaml`
  (e.g. `enable_gw_dpc`); Scalapack on.
- Build and test commands live in one script, `tools/abinit_build.sh`, that the skills and subagents call, so the
  command is defined once.

### 6.3 Cluster (Slurm)

- **Host config** `config/hosts/<host>.yaml`: module loads, partitions, default account, resource caps
  (e.g. debug partition, at most 2 nodes, at most 30 minutes unless the user says otherwise).
- **Where things run:** Claude Code runs on the login node inside tmux; heavy work goes through `srun` (builds) or
  `sbatch` (runs, tests). The login-node hook enforces this.
- **Permissions allowlist** in `.claude/settings.json`: `sbatch`, `squeue -u $USER`, `sacct`, `scancel` on own
  jobs. Never `--dangerously-skip-permissions`.
- **Job flow:** submit → record job IDs → poll → compare. Long jobs end the turn and are resumed with `claude -c`.
  Reuse `runtemplate.py submit/compare` where it fits.
- **Reading outputs:** through `fldiff`, `grep` or `tail`, never whole `.abo` or Slurm logs.

---

## 7. Implementation phases

Five phases, each ending with a review stop. Phases 1–2 already give a usable workflow; later phases add safety
and automation.

### Phase 1 — Skeleton meta repo

- [ ] Create `abinit_metarepo` with the layout above, `.gitignore`, `repos.yaml`, root `AGENTS.md` and `CLAUDE.md`.
- [ ] Verify the items in [Things to verify](#8-things-to-verify-and-open-decisions) and record the answers here.

**Acceptance:** starting `claude` at the root of a manual setup shows the root `AGENTS.md` and both repo
`AGENTS.md` files under memory files in `/context`.

### Phase 2 — `metactl` core

- [ ] `new`, `status`, `freeze`, `remove`, `doctor`, using full clones.
- [ ] `feature.yaml` written and committed on the meta feature branch.

**Acceptance:** `metactl new demo` then `metactl remove demo` leaves nothing behind; `remove` refuses while work is
unpushed; reusing a branch name already used by another workspace prints a warning.

### Phase 3 — Environments

- [ ] venv creation and editable abipy install; `tools/abinit_build.sh`; host config files.

**Acceptance:** two features side by side import their own abipy and build their own ABINIT.

### Phase 4 — Skills, agents, hooks

- [ ] `skills link`, `skills sync` with `skills.lock.yaml`; plugin settings and install in `new`.
- [ ] Subagents `abinit-dev`, `abipy-dev`, `reviewer`; login-node and wrong-repo hooks.
- [ ] First own skills: build-submit-check and ABINIT test writing.

**Acceptance:** `/context` lists the expected skills with no name clashes; on a login node the hooks block a bare
`mpirun` and a forced `git add abinit/...` at the root, while `cd abinit` and `git -C abinit status` pass.

### Phase 5 — Sync and cross-repo workflow

- [ ] `sync`, `exec`, `add-repo`/`remove-repo`; contract template in `contracts/`.
- [ ] Pilot on one real feature touching ABINIT and abipy, then update this plan with lessons learned.

**Acceptance:** a skill fix made on meta `main` reaches an active feature through `metactl sync` without conflicts.

### Testing `metactl` itself

pytest with temporary local git repos as remotes (no network); run in CI of the meta repo.

---

## 8. Things to verify and open decisions

Check these against the real repos and the installed Claude Code version **before Phase 2**; record each answer
next to the item.

### Verify

- [ ] Where ABINIT and abipy keep agent files today: `AGENTS.md`, `CLAUDE.md`, `.claude/skills/`,
      `.agents/skills/` or other.
      - *ABINIT (checked 7 Oct 2026):* `AGENTS.md` and `CLAUDE.md` at the root; skills in `.agents/skills/`,
        with `.claude/skills` a symlink to it. About 13 skills, mostly `abinit-*`, plus `netcdf` and
        `python-virtual-env`. abipy still to check.
- [ ] Whether `abinit/CLAUDE.md` or `abipy/CLAUDE.md` already imports its `AGENTS.md`, which would load it twice
      next to the root imports.
      - *ABINIT:* yes, `abinit/CLAUDE.md` is `@AGENTS.md`. See R2. abipy still to check.
- [ ] Claude Code loads `@abinit/AGENTS.md` imports and nested `.claude/skills/` when started at the workspace root
      (check with `/context`).
- [ ] Default branches and remote names of ABINIT and abipy: is `develop` the right base for both?
      - *ABINIT:* hosted on gitlab.uliege.be; fork is `origin`, official repo is `trunk`, base `trunk/develop`.
        See R1. abipy still to check.
- [ ] ABINIT config-file format and option names (`.ac9`, Scalapack, `enable_gw_dpc`) for the version in use.
- [ ] Time and disk cost of a full ABINIT clone on laptop and cluster, to decide whether `--reference-dir` is worth
      using.
      - *Laptop:* ABINIT `.git` is about 640 MB. Clone time and cluster numbers still to measure. See R5.
- [ ] Whether abipy's tests or install need anything from a sibling ABINIT checkout or build.
- [ ] How plugins declared in project `.claude/settings.json` get installed in a fresh clone
      (`claude plugin install … --scope project`).
- [ ] Cluster: disk quota for N full clones plus builds; whether `uv` and PyYAML are available; login-node policy
      on running agents.

### Open decisions

- [ ] **Workspace naming:** `meta_<feature>` siblings of `abinit_metarepo`, or a `features/` directory.
- [ ] **Default branch policy for abipy:** always a feature branch, or `develop` unless the feature changes abipy.
- [ ] **Where third-party skills live:** vendored copies only, or also plugin marketplaces.
- [ ] **Expose `metactl` as a skill?** e.g. `/meta-status`.

---

## 9. Review findings (to address)

Review of this plan on 7 Oct 2026, partly checked against a local ABINIT clone. Each item is a known problem to
resolve before or during the phase noted. Record the decision next to the item and update the affected sections.

### Contradicted by the real ABINIT repo

- [ ] **R1 — Hosting and remote names are wrong** *(before Phase 2)*. ABINIT forks live on gitlab.uliege.be, not
      GitHub, and the official remote is conventionally `trunk`, not `upstream`. `repos.yaml` needs a per-repo host,
      the `{github_user}` setting must be generalized, and the remote name for the official repo must be
      configurable (affects `base:` values in `feature.yaml`).
- [ ] **R2 — `AGENTS.md` loaded twice** *(Phase 1)*. `abinit/CLAUDE.md` already imports `@AGENTS.md`, so the root
      import `@abinit/AGENTS.md` duplicates it. Options: drop the root repo imports and rely on nested `CLAUDE.md`
      loading on demand, or keep them and accept the duplication.
- [ ] **R3 — Skill naming scheme collides with ABINIT's own skills** *(Phase 4)*. ABINIT already ships skills named
      `abinit-*` in `.agents/skills/` (exposed via a `.claude/skills` symlink). Generated `abinit-<name>` links
      would shadow them or produce names like `abinit-abinit-build`. The "repo-provided skills elsewhere" path may
      be unnecessary for ABINIT. Some repo skills (`netcdf`, `python-virtual-env`) have no prefix, so "prefixes
      are mandatory" cannot apply to repo skills.
- [ ] **R4 — Planned own skills overlap existing ABINIT skills** *(Phase 4)*. `meta-abinit-tests` and
      `meta-param-tests` duplicate `abinit-run-tests` and `abinit-parametrized-tests`; `meta-inputvar-lookup`
      overlaps `abinit-navigate` / `abinit-add-input-variable`. Prefer improving the upstream skills and keep
      `meta-*` skills for truly cross-repo work.
- [ ] **R5 — Cloning strategy** *(Phase 2)*. With a ~640 MB `.git`, consider partial clones
      (`--filter=blob:none`) as a simpler default than `--reference-dir`.

### Internal inconsistencies

- [ ] **R6 — Which `metactl` runs?** The Bootstrap decision says `metactl` runs from the main clone, but each
      feature clone also contains `tools/metactl.py`. Define which copy `sync` and other commands use when versions
      differ.
- [ ] **R7 — Host-specific path in `feature.yaml`.** `abinit_config: config/hosts/<host>.ac9` ties a committed
      manifest to one host, contradicting "works the same on laptop and cluster". Resolve the host config at
      runtime and keep only `abinit_configure_extra` per feature.
- [ ] **R8 — Committed `CLAUDE.md` vs optional repos.** With `metactl new --repos abinit`, the committed
      `@abipy/AGENTS.md` import dangles and `doctor` warns permanently. Consider generating `CLAUDE.md` per feature
      branch from the repos actually present.
- [ ] **R9 — CLI spec gaps.** `--force` for `remove` is in the behaviour rules but not the command table; no exit
      code is defined for `doctor` check failures.
- [ ] **R10 — Skill names drift.** Phase 4 says "build-submit-check" and "ABINIT test writing"; section 4.2 says
      `meta-build-submit-check` and `meta-abinit-tests`. Align them (after R4).
- [ ] **R11 — `freeze` semantics.** Specify whether `pinned_commit` is overwritten and whether `freeze` commits
      `feature.yaml` (git history would then record every freeze).

### Workflow and risk

- [ ] **R12 — Promoting generic fixes is clumsy.** Fixes made in a feature clone must be cherry-picked to `main`
      and pushed before `sync` sees them. Add a `metactl promote <commit>` command, or a rule that shared files are
      edited only in the main clone.
- [ ] **R13 — Bash hooks are easy to bypass.** Pipes, `bash -c`, `env`, aliases and `xargs` defeat token matching.
      Pair hooks with `permissions.deny` rules and make the must-pass / must-block table part of the pytest suite.
- [ ] **R14 — Tests and CI come too late.** `new` and `remove` touch real directories; move pytest + CI for
      `metactl` into Phase 2.
- [ ] **R15 — Unverified Claude Code behaviour on the critical path.** Nested `.claude/skills/` discovery when
      started at the workspace root, and project-scope plugin install in a fresh clone, must be tested in Phase 1
      before building on them.
