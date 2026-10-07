# ABINIT / abipy feature workspace

This directory is a feature workspace of the `abinit_metarepo` meta repo. The meta repo holds no application code:
only agent configuration, plans, contracts and tooling. The code lives in two separate git repos checked out inside
it.

## Repo map

| Path | What | Remotes |
|---|---|---|
| `.` | meta repo: `AGENTS.md`, `plans/`, `contracts/`, `repos.yaml`, `feature.yaml`, `.claude/` | `origin` on github.com |
| `abinit/` | ABINIT (Fortran), on the feature branch | `origin` = user's fork, `trunk` = official, gitlab.uliege.be |
| `abipy/` | abipy (Python), on the feature branch or `develop` | `origin` = user's fork, `upstream` = official, github.com |
| `build/<host>/` | out-of-tree ABINIT build | not a repo |
| `.venv/` | per-feature Python env, abipy installed editable from `./abipy` | not a repo |

`feature.yaml` (on feature branches) records each repo's branch, fork and base commit.

## Git rules

- `abinit/` and `abipy/` are **separate repos**, ignored by the meta repo. Run git inside the right one
  (`git -C abinit ...`, `git -C abipy ...`). Never `git add -f` them from the root.
- Commit to the meta repo only meta files (plans, contracts, skills, config).
- Never push, force-push or delete branches unless the user asks.

## How the repos connect

- abipy writes ABINIT inputs (`abipy/abipy/abio/inputs.py`) and parses ABINIT outputs: netCDF files (`*_GSR.nc`, ...) and
  text output (`.abo`).
- abipy keeps a copy of ABINIT's input-variable database in `abipy/abipy/abio/abivar_database/`, copied from
  `abinit/abimkdocs/variables_*.py`. A new or changed ABINIT variable needs
  `invoke update-vars ../abinit` run inside `abipy/`.
- abipy runs ABINIT through `TaskManager`, configured by `manager.yml` in the current directory, else
  `~/.abinit/abipy/manager.yml`. That config is shared by all features: check which `abinit` it actually runs.
- A change that crosses the boundary (new netCDF variable, new output section) needs a contract in `contracts/`.

## Plans and contracts

- `plans/`: shared plans and this feature's plan. Read the plans listed in `feature.yaml` when relevant.
- `contracts/<topic>.md`: interface specs between the repos. Both sides implement against the contract.

## Repo-specific instructions

- ABINIT: `abinit/AGENTS.md` (loaded via `abinit/CLAUDE.md` when working there), skills in `abinit/.agents/skills/`.
- abipy: no `AGENTS.md` yet; skills in `abipy/.agents/skills/`. Tests run with `pytest`.
- Both repos ship skills named `netcdf` and `python-virtual-env` with different content: use the one from the repo
  you are working in.
