# Meta-repo plan for ABINIT / abipy multi-repo development

*7 Oct 2026 · @Matteo*

**Contents**

1. [Context and goals](#1-context-and-goals)
2. [Design overview](#2-design-overview)
3. [Feature manifest](#3-feature-manifest)
4. [Agent configuration](#4-agent-configuration)
5. [The `abimeta` CLI](#5-the-abimeta-cli)
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
├── abinit_metarepo/            # main clone of the meta repo (runs abimeta, edit shared config here)
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
    ├── tools/abimeta.py        # the CLI
    ├── abinit/                 # full clone, branch gwr-mem     (untracked by meta)
    ├── abipy/                  # full clone, branch gwr-mem     (untracked by meta)
    ├── build/<host>/           # ABINIT out-of-tree build       (untracked)
    └── .venv/                  # per-feature Python env         (untracked)
```

### Key decisions

| Decision | Details |
|---|---|
| **Meta repo per feature** | Clone the meta repo once per feature and create a meta branch with the same name. Feature plans, the manifest and feature-specific tweaks are committed there. Feature meta branches are **never merged into `main`**. Generic improvements (skills, hooks, `abimeta`) go to `main`: commit them in the feature clone, push or cherry-pick them to `main`, and other features pick them up with `abimeta sync`. |
| **Code repos as full clones** | `abimeta new` clones each repo from the user's fork (`origin`) into the feature directory and adds the official repo under its configured remote name (`trunk` for ABINIT, `upstream` for abipy; see [Forges and identities](#forges-and-identities)). Clones always come from the remotes, never from a local copy or worktree, and nothing is shared between features (R16). |
| **Same branch name everywhere** (default) | Feature `gwr-mem` uses branch `gwr-mem` in meta, ABINIT and abipy. A repo may override it in `feature.yaml` (e.g. abipy stays on `develop`). |
| **Start Claude Code at the workspace root** | Root instructions and skills then apply everywhere; nested `CLAUDE.md` files and `.claude/skills/` in the repos load when Claude works in those directories. |
| **The meta repo ignores the code** | `.gitignore` lists `abinit/`, `abipy/`, `.venv/` and `build/`. No generated skill symlinks: both repos already expose their skills through `.claude/skills` (see R3). |
| **Bootstrap** | `abimeta` runs from the main clone (`abinit_metarepo`) in a small tooling venv with PyYAML; `tools/bootstrap.sh` creates it and puts a `abimeta` wrapper on `PATH`. Feature clones are cloned from the meta remote on GitHub, so generic fixes must be pushed to `main` before `abimeta sync` can bring them in. |

---

## 3. Feature manifest

### `feature.yaml`

Committed on the meta feature branch; the **single record of what a feature is built on**. `abimeta` writes it at
creation and updates the recorded commits on request.

```yaml
# illustrative values
name: gwr-mem
description: Reduce memory footprint of GWR (W streaming over q)
created: 2026-10-07

repos:
  abinit:
    branch: gwr-mem
    fork: git@gitlab.uliege.be:abinit/developers/gmatteo/abinit.git   # resolved URL, recorded
    base: trunk/develop           # where the branch was created from
    base_commit: <sha>            # filled by abimeta
  abipy:
    branch: develop               # override: no feature branch in abipy
    fork: git@github.com:gmatteo/abipy.git
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
# No usernames here: {user} is resolved per host from the personal config, so this file can be shared.
abinit:
  host: gitlab.uliege.be
  upstream_remote: trunk
  upstream: https://gitlab.uliege.be/abinit/developers/trunk/abinit.git
  fork: git@gitlab.uliege.be:abinit/developers/{user}/abinit.git
  default_base: trunk/develop

abipy:
  host: github.com
  upstream_remote: upstream
  upstream: https://github.com/abinit/abipy.git
  fork: git@github.com:{user}/abipy.git
  default_base: upstream/develop      # verify
  python_install: editable
```

### Forges and identities

Repos may live on different forges (gitlab.uliege.be, github.com), and the username can differ between them. Three
files keep the concerns apart:

| File | Scope | Holds |
|---|---|---|
| `repos.yaml` | shared, committed on `main` | per repo: `host`, upstream URL and remote name, fork URL **template** with `{user}` |
| `$XDG_CONFIG_HOME/abinit_metarepo/config.yaml` (default `~/.config/...`) | personal, never committed | per host: username and protocol; workspace root, host name, meta remote URL, optional extra remotes |
| `feature.yaml` | per feature, committed | the **resolved** fork URL actually used, so the record does not depend on the reader's config |

```yaml
# ~/.config/abinit_metarepo/config.yaml
identities:
  gitlab.uliege.be: { user: gmatteo, protocol: ssh }
  github.com:       { user: gmatteo, protocol: ssh }
extra_remotes:                      # optional, added to new ABINIT clones
  abinit: [hexu, siyu, torrent]
```

- The fork template must be a full path: ABINIT forks live under `abinit/developers/<user>/`, not `<user>/`.
- `ABINIT_METAREPO_CONFIG` overrides the config path (tests, unusual cluster homes). The directory also holds
  other personal state (tooling venv, caches).
- To work on a branch in someone else's fork: `abimeta new <feature> --fork abinit=<user>` resolves `{user}` for that
  repo only; `origin` stays the user's own fork for pushing.
- Credentials (SSH keys, credential helpers) are left to git; `abimeta` never stores tokens.
- Branches in the user's fork are the user's own namespace, so the branch-clash check only compares the user's own
  workspaces.
- MR/PR links (R21): the host picks the tool (`glab` or `gh`); store the link in `feature.yaml`, neither tool is a
  hard dependency.

### `abimeta freeze`

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

  ## Claude Code specifics
  - `abinit/AGENTS.md` is not imported here: `abinit/CLAUDE.md` loads it when you work in `abinit/`.
  - Active plans: see `feature.yaml` `plans:`; read them when relevant, do not import them.
  - When compacting, keep the list of modified files per repo and the test commands.
  ```

- Repo instructions are **not** imported at the root (R2): `abinit/CLAUDE.md` already imports `abinit/AGENTS.md`
  and loads on demand, and abipy has no `AGENTS.md`. The same `CLAUDE.md` therefore works for any set of repos (R8).
- abipy-specific notes the agent needs live in the root `AGENTS.md` until abipy ships its own `AGENTS.md`.
- Personal, uncommitted notes go in `CLAUDE.local.md` at the workspace root (gitignored).

### 4.2 Skills

| Source | Location in workspace | How it gets there |
|---|---|---|
| Own integration skills | `.claude/skills/meta-<name>/` | Committed in meta |
| Repo-provided skills in `.claude/skills/` | `abinit/.claude/skills/`, `abipy/.claude/skills/` | Found by Claude Code when working in those dirs; nothing to do *(verify)* |
| Repo-provided skills elsewhere | — | None today: ABINIT and abipy both keep skills in `.agents/skills/` with `.claude/skills` a symlink to it. Add `abimeta skills link` only if a repo stops doing that (R3). |
| Third-party plain skills | `.claude/skills/vendor-<name>/` | Copied at a pinned commit by `abimeta skills sync` from `skills.lock.yaml`; committed |
| Third-party plugins | Plugin cache | `extraKnownMarketplaces` + `enabledPlugins` in `.claude/settings.json`; `abimeta new` runs the project-scope install |

- **Prefixes are mandatory** for skills the meta repo owns: `meta-` for own skills, `vendor-` for third-party. Repo
  skills keep their own names. Same-named skills shadow each other by scope; note that both repos ship `netcdf` and
  `python-virtual-env` with different content.
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

## 5. The `abimeta` CLI

`tools/abimeta.py` is a single Python file (stdlib + PyYAML) with subcommands. Every command is **idempotent** and
**prints what it does**. It never pushes, deletes branches or force-anything without an explicit flag.

### Commands

| Command | What it does |
|---|---|
| `abimeta new <feature> [--repos abinit,abipy] [--branch NAME] [--base REF] [--fork REPO=USER]` | Clone meta into `../meta_<feature>`, create meta branch, clone each repo and create its feature branch, write `feature.yaml`, create venv, install abipy editable, link skills, install plugins, run `doctor` |
| `abimeta status` | Branch, ahead/behind vs base, dirty files, for meta and each repo |
| `abimeta sync [--rebase]` | Fetch all remotes; pull meta `main` into the feature; optionally rebase repo branches on their base |
| `abimeta exec -- <cmd>` | Run a command in every repo clone (e.g. `git log -1`) |
| `abimeta freeze` | Record each repo's `HEAD` as `pinned_commit` in `feature.yaml` |
| `abimeta add-repo <name>` / `remove-repo <name>` | Add or drop a repo in an existing feature |
| `abimeta skills link` | Create/refresh symlinks to repo-provided skills |
| `abimeta skills sync` | Copy pinned third-party skills from `skills.lock.yaml`; show diff on version bumps |
| `abimeta doctor` | Check imports resolve, symlinks valid, venv ok, abipy importable from this workspace, hooks executable |
| `abimeta remove <feature> [--delete-branches]` | Delete the workspace directory after checking nothing is uncommitted or unpushed |

### Behaviour rules

- **Branch clash warning:** warn when another workspace under the workspace root already uses the same branch name
  for a repo, since pushing both to the fork would clash.
- **Safe remove:** `remove` refuses if any repo has uncommitted or unpushed work, unless `--force`.
- **No hard-coded paths:** all paths come from `repos.yaml`, `feature.yaml` and the personal config
  `~/.config/abinit_metarepo/config.yaml` (see [Forges and identities](#forges-and-identities)).
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

- [x] Create `abinit_metarepo` with `.gitignore`, `repos.yaml`, root `AGENTS.md` and `CLAUDE.md`, and
      `contracts/README.md`. Other directories (`config/hosts/`, `.claude/`, `tools/`) are created by the phase that
      fills them.
- [x] Verify the items in [Things to verify](#8-things-to-verify-and-open-decisions) that can be checked without
      Claude Code or the cluster; answers recorded there.
- [ ] Manual acceptance check below (needs an interactive `claude`).

**Acceptance:** in a manual setup (meta clone with `abinit/` and `abipy/` cloned inside from their remotes), `claude` started at the
root shows the root `AGENTS.md` and `CLAUDE.md` in `/context`. After asking it to read a file in `abinit/`,
`abinit/CLAUDE.md` (and through it `abinit/AGENTS.md`) and the `abinit-*` skills appear; the same for the `abipy-*`
skills after reading a file in `abipy/`.

### Phase 2 — `abimeta` core

- [ ] `new`, `status`, `freeze`, `remove`, `doctor`, using full clones.
- [ ] `feature.yaml` written and committed on the meta feature branch.

**Acceptance:** `abimeta new demo` then `abimeta remove demo` leaves nothing behind; `remove` refuses while work is
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

**Acceptance:** a skill fix made on meta `main` reaches an active feature through `abimeta sync` without conflicts.

### Testing `abimeta` itself

pytest with temporary local git repos as remotes (no network); run in CI of the meta repo.

---

## 8. Things to verify and open decisions

Check these against the real repos and the installed Claude Code version **before Phase 2**; record each answer
next to the item.

### Verify

- [x] Where ABINIT and abipy keep agent files today: `AGENTS.md`, `CLAUDE.md`, `.claude/skills/`,
      `.agents/skills/` or other.
      - *ABINIT (checked 7 Oct 2026):* `AGENTS.md` and `CLAUDE.md` at the root; skills in `.agents/skills/`,
        with `.claude/skills` a symlink to it. 13 skills: 11 `abinit-*` plus `netcdf` and `python-virtual-env`.
      - *abipy (checked 7 Oct 2026):* **no `AGENTS.md` or `CLAUDE.md`** anywhere in the repo. Skills in
        `.agents/skills/`, `.claude/skills` a symlink to it. 16 skills: 14 `abipy-*` plus `netcdf` and
        `python-virtual-env`, which **differ** from ABINIT's skills of the same name.
- [x] Whether `abinit/CLAUDE.md` or `abipy/CLAUDE.md` already imports its `AGENTS.md`, which would load it twice
      next to the root imports.
      - *ABINIT:* yes, `abinit/CLAUDE.md` is `@AGENTS.md`. *abipy:* no `CLAUDE.md`. Resolved by R2.
- [ ] Claude Code loads nested `CLAUDE.md` and nested `.claude/skills/` (a symlink in both repos) when started at the
      workspace root (check with `/context`; installed version 2.1.293). This is the Phase 1 acceptance check.
- [x] Default branches and remote names of ABINIT and abipy: is `develop` the right base for both?
      - *ABINIT:* hosted on gitlab.uliege.be; fork is `origin`, official repo is `trunk`, base `trunk/develop`
        (`trunk/main` exists but is older). See R1.
      - *abipy:* github.com; default branch `develop`. In the local clone `origin` is the **official** repo (the
        user has push access) and the fork `github.com/gmatteo/abipy` also exists. `repos.yaml` uses the fork
        layout; see R1 note.
- [ ] ABINIT config-file format and option names (`.ac9`, Scalapack, `enable_gw_dpc`) for the version in use.
      - *Partial:* `abinit/doc/build/config-template.ac9` is the reference; it has `enable_gw_dpc` and
        `with_linalg_flavor`, and Scalapack goes through `LINALG_LIBS`. Host files to be written in Phase 3.
- [ ] Time and disk cost of a full ABINIT clone on laptop and cluster, to decide whether partial clones (R5) are
      worth using.
      - *Laptop:* ABINIT `.git` is about 640 MB. Clone time and cluster numbers still to measure. See R5.
- [x] Whether abipy's tests or install need anything from a sibling ABINIT checkout or build.
      - Install: no. Tests: tests that run ABINIT check `has_abinit()` (through `TaskManager`) and are skipped when
        it is missing. `invoke update-vars <abinit_repo>` copies ABINIT's variable database
        (`abimkdocs/variables_*.py`) into `abipy/abio/abivar_database/`, so it needs the sibling checkout.
- [x] Python tooling on this laptop: `uv` not installed; system `python3` has PyYAML 6.0.3.
- [ ] How plugins declared in project `.claude/settings.json` get installed in a fresh clone
      (`claude plugin install … --scope project`).
- [ ] Cluster: disk quota for N full clones plus builds; whether `uv` and PyYAML are available; login-node policy
      on running agents.

### Open decisions

- [ ] **Workspace naming:** `meta_<feature>` siblings of `abinit_metarepo`, or a `features/` directory.
- [ ] **Default branch policy for abipy:** always a feature branch, or `develop` unless the feature changes abipy.
- [ ] **Where third-party skills live:** vendored copies only, or also plugin marketplaces.
- [ ] **Expose `abimeta` as a skill?** e.g. `/meta-status`.

---

## 9. Review findings (to address)

Review of this plan on 7 Oct 2026, partly checked against a local ABINIT clone. Each item is a known problem to
resolve before or during the phase noted. Record the decision next to the item and update the affected sections.

### Contradicted by the real ABINIT repo

- [ ] **R1 — Hosting and remote names are wrong** *(before Phase 2)*. ABINIT forks live on gitlab.uliege.be, not
      GitHub, and the official remote is conventionally `trunk`, not `upstream`. `repos.yaml` needs a per-repo host,
      the `{github_user}` setting must be generalized, and the remote name for the official repo must be
      configurable (affects `base:` values in `feature.yaml`).
      - *Decision (7 Oct 2026):* per-repo `host`, `upstream_remote` and `{user}` fork templates in `repos.yaml`;
        per-host identities in `~/.config/abinit_metarepo/config.yaml`; resolved fork URL recorded in
        `feature.yaml`. See [Forges and identities](#forges-and-identities).
      - *Note:* for abipy the user may push directly to the official repo instead of a fork. Supporting
        `fork: null` (origin = official repo, no second remote) is a small addition for Phase 2.
- [x] **R2 — `AGENTS.md` loaded twice** *(Phase 1)*. `abinit/CLAUDE.md` already imports `@AGENTS.md`, so the root
      import `@abinit/AGENTS.md` duplicates it. Options: drop the root repo imports and rely on nested `CLAUDE.md`
      loading on demand, or keep them and accept the duplication.
      - *Decision (7 Oct 2026):* root repo imports dropped; root `CLAUDE.md` imports only `@AGENTS.md`. abipy has
        no `AGENTS.md`, so its import would dangle anyway. Easy to revert if on-demand loading proves too late.
- [ ] **R3 — Skill naming scheme collides with ABINIT's own skills** *(Phase 4)*. ABINIT already ships skills named
      `abinit-*` in `.agents/skills/` (exposed via a `.claude/skills` symlink). Generated `abinit-<name>` links
      would shadow them or produce names like `abinit-abinit-build`. The "repo-provided skills elsewhere" path may
      be unnecessary for ABINIT. Some repo skills (`netcdf`, `python-virtual-env`) have no prefix, so "prefixes
      are mandatory" cannot apply to repo skills.
      - *Update (7 Oct 2026):* abipy uses the same layout (`.agents/skills/` + `.claude/skills` symlink), so the
        "elsewhere" path and `skills link` are dropped for now (sections 2 and 4.2 updated). `netcdf` and
        `python-virtual-env` exist in **both** repos with different content: decide in Phase 4 whether to rename
        upstream, merge them, or rely on the nested scope.
- [ ] **R4 — Planned own skills overlap existing ABINIT skills** *(Phase 4)*. `meta-abinit-tests` and
      `meta-param-tests` duplicate `abinit-run-tests` and `abinit-parametrized-tests`; `meta-inputvar-lookup`
      overlaps `abinit-navigate` / `abinit-add-input-variable`. Prefer improving the upstream skills and keep
      `meta-*` skills for truly cross-repo work.
- [ ] **R5 — Cloning strategy** *(Phase 2)*. With a ~640 MB `.git`, consider partial clones
      (`--filter=blob:none`) as a simpler default than `--reference-dir`.
      - *Update:* `--reference-dir` dropped with R16; partial clones are the only speed-up still on the table.

### Internal inconsistencies

- [ ] **R6 — Which `abimeta` runs?** The Bootstrap decision says `abimeta` runs from the main clone, but each
      feature clone also contains `tools/abimeta.py`. Define which copy `sync` and other commands use when versions
      differ.
- [ ] **R7 — Host-specific path in `feature.yaml`.** `abinit_config: config/hosts/<host>.ac9` ties a committed
      manifest to one host, contradicting "works the same on laptop and cluster". Resolve the host config at
      runtime and keep only `abinit_configure_extra` per feature.
- [ ] **R8 — Committed `CLAUDE.md` vs optional repos.** With `abimeta new --repos abinit`, the committed
      `@abipy/AGENTS.md` import dangles and `doctor` warns permanently. Consider generating `CLAUDE.md` per feature
      branch from the repos actually present.
      - *Resolved by R2:* root `CLAUDE.md` no longer imports repo files, so it is the same for any set of repos.
- [ ] **R9 — CLI spec gaps.** `--force` for `remove` is in the behaviour rules but not the command table; no exit
      code is defined for `doctor` check failures.
- [ ] **R10 — Skill names drift.** Phase 4 says "build-submit-check" and "ABINIT test writing"; section 4.2 says
      `meta-build-submit-check` and `meta-abinit-tests`. Align them (after R4).
- [ ] **R11 — `freeze` semantics.** Specify whether `pinned_commit` is overwritten and whether `freeze` commits
      `feature.yaml` (git history would then record every freeze).

### Workflow and risk

- [ ] **R12 — Promoting generic fixes is clumsy.** Fixes made in a feature clone must be cherry-picked to `main`
      and pushed before `sync` sees them. Add a `abimeta promote <commit>` command, or a rule that shared files are
      edited only in the main clone.
- [ ] **R13 — Bash hooks are easy to bypass.** Pipes, `bash -c`, `env`, aliases and `xargs` defeat token matching.
      Pair hooks with `permissions.deny` rules and make the must-pass / must-block table part of the pytest suite.
- [ ] **R14 — Tests and CI come too late.** `new` and `remove` touch real directories; move pytest + CI for
      `abimeta` into Phase 2.
- [ ] **R15 — Unverified Claude Code behaviour on the critical path.** Nested `.claude/skills/` discovery when
      started at the workspace root, and project-scope plugin install in a fresh clone, must be tested in Phase 1
      before building on them. ABINIT's `.claude/skills` is a symlink to `.agents/skills`: also check that nested
      discovery follows it.

### Second pass (7 Oct 2026)

- [x] **R16 — Full clones vs `git worktree`** *(before Phase 2)*. Keeping one main clone each of meta, ABINIT and
      abipy, with a worktree per feature, removes the ~640 MB per-feature cost (R5). It also turns promoting a fix to
      `main` into a local cherry-pick that needs no push before `sync` (R6, R12). And it keeps extra remotes
      (colleague forks such as `hexu`, `siyu`, `torrent`), which a fresh clone loses. The cost: workspaces can no
      longer be moved freely and features are less isolated. Decide, and record the reasoning under Key decisions
      either way.
      - *Decision (7 Oct 2026):* full clones from the remotes. Workspaces must not depend on local clones
        (no worktrees, no `--reference-dir`), so each feature is self-contained and can be moved or deleted. R6
        and R12 stay open; colleague remotes come from `extra_remotes` in the personal config.
- [ ] **R17 — abipy config is global** *(Phase 3)*. `~/.abinit/abipy/manager.yml` and `scheduler.yml` are shared by
      all features, so abipy may run another feature's ABINIT build or the system one. Define how abipy finds this
      feature's `abinit` (e.g. the venv activate script puts `build/<host>/src/98_main` first on `PATH`, or a
      per-feature config override if abipy supports one). `doctor` should check `which abinit`.
      - *Checked (7 Oct 2026):* `TaskManager.from_user_config` reads `manager.yml` from the **current directory**
        first, then `~/.abinit/abipy/`; the `ABIPY_TASK_MANAGER_PATH` override is commented out. Options: a
        `manager.yml` at the workspace root (works only when the cwd is the root), `PATH` set by the venv activate
        script (works if `manager.yml` does not hard-code the executable), or re-enable the env var in abipy.
- [ ] **R18 — Allowlist rules that cannot be expressed** *(Phase 4)*. Permission rules match literal patterns:
      `$USER` is not expanded, and "`scancel` on own jobs" cannot be a rule. Use `Bash(squeue:*)` and
      `Bash(sacct:*)`, and leave `scancel` on ask, or guard it with a hook.
- [ ] **R19 — Subagent scope is not enforced** *(Phase 4)*. "Works only inside `abinit/`" is only an instruction.
      State that in section 4.3, or enforce it with a hook that checks the paths in subagent tool calls.
- [ ] **R20 — End of a feature's life** *(Phase 2)*. After `remove`, `feature.yaml` and the feature plan survive only
      on the remote meta branch, and only if it was pushed. `remove` should require the meta branch to be pushed.
      Optionally, archive the manifest and plan to `main:features/<name>/`.
- [ ] **R21 — Record upstream review links** *(Phase 2)*. Add the ABINIT GitLab MR and abipy GitHub PR URLs to
      `feature.yaml`, and show them in `status`.
- [ ] **R22 — `base_commit` goes stale** *(Phase 5)*. `sync --rebase` must update `base_commit`, following the same
      commit-or-not rule as `freeze` (R11).
- [ ] **R23 — `sync` merge conflicts on per-feature files** *(Phase 5)*. If `CLAUDE.md` is generated per feature
      (R8), merging `main` into feature branches will conflict on it. Keep per-feature content in a file that `main`
      never touches (e.g. `CLAUDE.feature.md`), imported from a stable `CLAUDE.md`.
- [ ] **R24 — venv cost** *(Phase 3)*. abipy pulls in pymatgen and its dependencies (about 1–2 GB per venv). Make
      `uv` the default, since its cache shares packages across venvs, and fall back to `python -m venv` only when
      `uv` is missing.
- [ ] **R25 — Scope before first real use** *(Phase 2)*. Run the pilot by hand right after Phase 2 (`new`, `status`,
      `remove`). Build `skills link`, `add-repo`, `exec` and `promote` only when the pilot shows a need; R3 already
      suggests `skills link` may be unnecessary for ABINIT.

Smaller points from the same pass:

- R2: prefer dropping the root `@abinit/AGENTS.md` / `@abipy/AGENTS.md` imports; nested `CLAUDE.md` files load on
  demand, and this also resolves R8.
- R9: `new` runs `doctor` but must not fail on warnings; give `doctor` distinct exit codes for warnings and errors.
- Section 6.2: "Scalapack on" is a host or feature setting; move it into the host `.ac9`.
- Section 4.4: the login-node guard should fail closed: on a known cluster hostname with no host config, treat the
  machine as a login node.
