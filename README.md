# repo-tools

Command line tools for repositories, in steps that are safe to re-run:

| Command | What for |
|---|---|
| [`github`](#github-and-packagist) | Publishing, releasing, renaming, archiving and deleting repos on GitHub |
| [`packagist`](#github-and-packagist) | Publishing packages on Packagist and keeping them current |
| [`repo-list`](#repo-list) | Reporting the state of every git repository under a folder |
| [`repo-fix`](#repo-fix) | Fixing what repo-list reports |

They're built on [cli-kit](../cli-kit), so every command has the same help and ends with one status line, ✅ ➖ ⚠️ ❌ or 🛑.

## `github` and `packagist`

`github help` (or `-h`, `--help`, or no command at all) lists the commands with their arguments; `github help <command>` or `github <command> --help` shows one in full. The same goes for `packagist`.

### `github publish [<dir>] [<repo-name>] [--private] [--no-ci-wait]`

1. Creates the repo under the account `gh` is logged in as, with the description from the project's manifest when it has one: `composer.json`, `package.json`, `Cargo.toml`, `pyproject.toml`, `pom.xml`, `*.csproj` or `*.gemspec`. An existing repo is never edited; if its visibility differs from the one asked for, it stops.
2. Adds it as the `origin` remote, or checks that `origin` already points at it.
3. Pushes the current branch and all tags.
4. Waits for the CI run on the pushed commit, when the repo has a workflow, and prints the failing log on failure. `--no-ci-wait` skips this, such as when publishing many repos at once.

`dir` defaults to the current directory and `repo-name` to the directory's name. The repo is public unless you pass `--private`. Each step is skipped when it's already done, so after a failure you fix the cause and run it again. It refuses a work tree with uncommitted changes or a detached HEAD.

### `github release <dir> <patch|minor|major>`

1. Tags `HEAD` as the next version: the highest `[v]MAJOR.MINOR.PATCH` tag, bumped at the level you give. A project with no version tags starts from `0.0.0`, so its first `minor` release is `v0.1.0`. The tag keeps the highest tag's style, with or without the `v`.
2. Pushes the tag. Packagist's webhook then picks it up; run `packagist update <dir>` to wait until it has.
3. Creates the GitHub release, with notes GitHub generates from the commits since the last one.

It fetches origin's tags first, so a tag pushed from another machine counts. It refuses uncommitted changes, a detached `HEAD`, and a `HEAD` not yet on origin, so a release is always of what's on GitHub. Pre-release tags such as `v2.0.0-beta1` don't count. A `HEAD` that already has a version tag is released as that version, whatever level you give, so running it again after a failure finishes the same release rather than making another, and no tag is ever moved.

Choosing the level is yours: `patch` for fixes, `minor` for new features, `major` for breaking changes. Below 1.0.0, Composer's `^0.2` treats each minor as possibly breaking.

### `github rename <dir> <new-name>`

1. Renames the GitHub repo that `dir`'s `origin` names, keeping its owner.
2. Points `origin` at the new name, in the same SSH or HTTPS form.
3. When `dir` is a Composer package that Packagist has, points the package at the new URL. This needs the Packagist main token.

GitHub redirects the old name to the new one, for git, web links and the API, until you or someone else creates a repo with the old name. Packagist, though, matches the webhook's pushes to a package by its stored repository URL, which is why step 3 exists. Each step is skipped when it's already done. The local folder keeps its name; rename it yourself if you want.

### `github archive <repo>`

Archives a repo, making it read-only. `repo` is `owner/name`, or a name owned by you. Skipped when it's already archived. It uses `gh`'s everyday login, since archiving needs no extra scope and you can undo it in the repo's settings.

### `github delete <repo>`

Deletes a repo after you type its full name, `owner/name`, at the terminal. `repo` is `owner/name`, or a name owned by you. The local clone is left alone.

It uses a separate token with the `delete_repo` scope, read from the credential store only after you've confirmed, so `gh`'s everyday login never has that scope. See [Guarding delete](#guarding-delete) for why.

### `packagist publish <dir>`

1. Submits the package to Packagist, reading the name from `composer.json` and the URL from `origin`, which must be a public GitHub repo. Publish it there first with `github publish <dir>`.
2. Adds the GitHub webhook that tells Packagist about new pushes and tags.

Each step is skipped when it's already done. Without a version tag Packagist only offers `dev-<branch>`, so it warns when there's none.

### `packagist update <dir>`

Asks Packagist to update a package it already has, then waits up to two minutes until it offers every version tag and the latest commit of every branch on `origin`. It asks nothing when Packagist already does. The webhook `packagist publish` adds normally keeps Packagist current on each push; this is for when it hasn't.

It compares against `git ls-remote origin`, so work not yet pushed isn't expected, and reads what Packagist offers from the Composer metadata at `repo.packagist.org`, which is what installs see. (The `packagist.org/packages/<name>.json` API is cached for up to twelve hours.) Tags that aren't versions, such as `latest`, are ignored.

There's no `packagist rename`: Packagist's API can't rename, abandon or delete a package, and Packagist has no rename at all. To rename one, change the name in `composer.json` and push, run `packagist publish` for the new name, then on the old package's page choose **Abandon** and name the new package as its replacement. The old page may also offer **Delete**, though Packagist can refuse it for a package others install. To rename only the GitHub repo, use `github rename`.

Every command ends with one status line, ✅ ➖ ⚠️ ❌ or 🛑, as [cli-kit's README](../cli-kit/README.md#how-every-command-behaves) describes.

## `repo-list`

Reports the state of every git repository under a folder, so nothing is left uncommitted or unpushed; [repo-fix](#repo-fix) fixes what it can.

```
$ repo-list
✘ blog          📝 3 uncommitted files  📤 2 unpushed on main
✔ dotfiles
✘ notes         📁 not a git repository
✔ work/api
✘ work/website  🔌 no remote

✘ 3 of 5 need attention
```

Each repository is listed by its path from the root, in name order, with ✔ when it is clean or ✘ and what needs attention:

- 📝 **uncommitted files**: changed, staged or untracked
- 📤 **unpushed on *branch***: commits on a local branch that are on no remote, whether or not the branch has an upstream
- 📥 **behind on *branch***: commits on the branch's upstream that it lacks, as of the last fetch
- 👻 **commits on detached HEAD**: commits reachable from no branch or remote
- 📦 **stashes**
- 🔌 **no remote**
- 📁 **not a git repository**: a folder that holds files but is in no repository, such as a project not yet initialised
- 📡 **fetch failed**: with `--fetch` only
- 💥 **git failed**: git couldn't read the repository
- 🐘 **not on Packagist**, **Packagist lacks *versions or branches***, or **Packagist check failed**: with `--packagist` only, for a package of your vendor's (see [Packagist](#packagist))

The last line totals them, for when the list scrolls off the screen: `✘ 3 of 5 need attention`, or `✔ All 5 clean`.

On a terminal the parent path is grey, the repository's name is bold and the problems are yellow. `NO_COLOR=1` turns colour off; `FORCE_COLOR=1` keeps it when piping.

### How it searches

It assumes repositories are not nested, so it stops descending at each one and never walks into `node_modules`, `vendor` and the like. A folder holding only folders, such as `work/`, is a group and is searched. A folder holding any file (other than `.DS_Store`) is a project, and is reported if it is not a repository. Empty folders, hidden folders and symlinks are skipped.

### Packagist

A repository whose `composer.json` names a package of your Packagist vendor's, `packagist.vendor` in the [config](#config), should be on Packagist, offering every version tag and the latest commit of every branch on `origin`. Which repositories those are is read from the repositories themselves, so there's nothing to configure as packages come and go. The check is [`packagist update`](#packagist-update-dir)'s. It needs the network, so it runs only with `-p` (`--packagist`), and not for a repository whose fetch failed.

### Usage

```
repo-list [-f|--fetch] [-p|--packagist] [<root>]
```

`root` defaults to the configured root, wherever you run it from. `-f` runs `git fetch --all` in every repository first, eight at a time, so the behind counts are current. `-p` checks each package against Packagist. Without either, nothing touches the network.

Exit status: 0 all clean, 1 something needs attention, 2 usage error.

## `repo-fix`

Fixes what repo-list reports, in one repository or in every one under a folder.

```
repo-fix [--init] [--no-ci-wait] [-p|--packagist] [<path>]
```

`path` is a repository, or a folder to search as repo-list does; it defaults to the configured root, wherever you run it from. Every repository is fetched first. Then, in each:

| Problem | Fix |
|---|---|
| 📝 uncommitted files | Claude Code's `/commit` skill, run headless (`claude -p /commit`) |
| 🔌 no remote | `github publish`, so public and waiting for CI unless `--no-ci-wait` |
| 📥 behind | fast-forwarded to the upstream, whether the branch is checked out or not |
| 📤 unpushed | pushed to the upstream; a branch with none is pushed to the only remote and tracks it |
| 📁 not a git repository | with `--init` only: `git init`, then committed and published |
| 🐘 Packagist | with `-p` only, after pushing: `packagist publish`, which also adds a missing webhook, then `packagist update`, which waits until Packagist has what was pushed |

Everything but writing the commits is deterministic. The commit step is checked before and after: it doesn't start on a detached HEAD or during a merge, rebase, cherry-pick or revert, and it counts as done only if the work tree is then clean, on the same branch, with the earlier commits untouched. It judges by git's state, not by what Claude says, because a skill that fails to load still ends in success with nothing done. If the commit step fails, nothing else happens in that repository.

Nothing is forced. A branch both behind and unpushed has diverged and is left alone, as are stashes and commits on a detached HEAD. A repository whose fetch failed is neither pushed nor pulled.

Each repository it changed is listed with what was done, then it ends with repo-list's report of what's left:

```
$ repo-fix
blog
  ✔ Committed a1b2c3d Add the draft about devbox
  ✔ Pushed main to origin
work/website
  ✘ Not syncing main: it has diverged from origin/main

✔ blog
✔ dotfiles
✘ work/website  📤 1 unpushed on main  📥 2 behind on main

✘ 1 of 3 need attention
```

Packagist is checked again after pushing, since whatever was pushed is new to it. The Packagist step is skipped when committing or publishing to GitHub failed, and `packagist update` when `packagist publish` failed.

It needs `claude` on the PATH, logged in, and the commit skill at `~/.claude/skills/commit`. The skill's files may be symlinks into another repository; repo-fix lets Claude read wherever they lead.

Exit status: 0 all clean afterwards, 1 something still needs attention, 2 usage error.

## Setup

Once per machine, with [cli-kit](../cli-kit) checked out next to this folder:

```sh
cd ~/projects/cli/repo-tools
devbox run setup
```

That runs `uv sync`, which builds `.venv` with cli-kit and these tools installed, then prints the commands that link each one onto your PATH:

```sh
ln -sf ~/projects/cli/repo-tools/.venv/bin/github ~/.local/bin/github
ln -sf ~/projects/cli/repo-tools/.venv/bin/packagist ~/.local/bin/packagist
ln -sf ~/projects/cli/repo-tools/.venv/bin/repo-list ~/.local/bin/repo-list
ln -sf ~/projects/cli/repo-tools/.venv/bin/repo-fix ~/.local/bin/repo-fix
```

The commands in `.venv/bin` are console scripts pointing at the Python devbox pins, so they start without devbox, which is slower and prints its own error line whenever a command fails. cli-kit puts this folder's devbox packages, such as `gh`, first on the PATH for the programs a command runs. After pulling changes, here or in cli-kit, run `devbox run -- uv sync` to bring `.venv` up to date.

### Config

Setup also copies `config.example.toml` to `config.toml`, if you have none, for your own settings. Git ignores `config.toml`, as a PHP project's `.env`, so the repository holds no one's personal settings. A setting left out takes its default:

| Setting | Default | What for |
|---|---|---|
| `root` | `~/projects` | where repo-list and repo-fix look when given no folder |
| `packagist.vendor` | none | whose packages `-p` checks; `-p` without it is a usage error |

### GitHub

```sh
devbox run -- gh config set git_protocol ssh   # push over your existing SSH key
```

`git_protocol` is saved in `gh`'s own config, which every `gh` on the machine shares; skip it if `devbox run -- gh config get git_protocol` already prints `ssh`.

### Log gh in with a limited token

Create a **classic** token at <https://github.com/settings/tokens>:

| Scope | Needed for |
|---|---|
| `public_repo` | creating public repos and pushing to them |
| `repo` | instead of `public_repo`, only if you'll publish private repos |
| `workflow` | pushing `.github/workflows/` files |
| `read:org` | nothing here; `gh auth login` refuses tokens without it. Read-only. |
| `admin:repo_hook` | adding the Packagist webhook |

Leave out `delete_repo`: that goes in its own token, below.

Log in, pasting the token at the hidden prompt so it never appears on screen:

```sh
read -rsp 'GitHub token: ' token && echo && printf '%s\n' "$token" | devbox run -- gh auth login --with-token; unset token
devbox run -- gh auth status
```

`gh` keeps the token in the system credential store, so you log in again only when it expires or you replace it.

### Store the delete token

Only if you'll use `github delete`. Create a second classic token with only the `delete_repo` scope, and store it under your GitHub username.

**macOS**:

```sh
security add-generic-password -a <github-username> -s github-delete-repo-token -T '' -w
```

`-T ''` trusts no app with the token, so each time `github delete` reads it, macOS asks for your login password. Choose **Allow**, never **Always Allow**, which would remove that check.

**Linux**, with `secret-tool` from the `libsecret-tools` package:

```sh
secret-tool store --label='GitHub delete_repo token' service github-delete-repo-token username <github-username>
```

The Secret Service keyring doesn't ask on each read, so on Linux the typed confirmation is the only check.

### Store the Packagist API tokens

Only if you'll use `packagist`. Sign in at <https://packagist.org> with GitHub; your first submission claims your vendor name. Your profile page has two tokens:

| Token | Used for | Why that one |
|---|---|---|
| Main | submitting a new package, and `github rename` | Only the main token can create packages or change their repository URL. It stays in your credential store. |
| Safe | the webhook secret, and `packagist update` | The secret is stored on GitHub. The safe token can only trigger package updates, so it does little harm if it leaks. |

Store both under your Packagist **username**, which can differ from your vendor name. Each command prompts for the token, so it never lands in your shell history.

**macOS**:

```sh
security add-generic-password -a <packagist-username> -s packagist-api-token -w       # main
security add-generic-password -a <packagist-username> -s packagist-safe-api-token -w  # safe
```

**Linux**:

```sh
secret-tool store --label='Packagist main API token' service packagist-api-token username <packagist-username>
secret-tool store --label='Packagist safe API token' service packagist-safe-api-token username <packagist-username>
```

Tokens are only ever held in memory: never put on a command line or written to a file.

## Guarding delete

When an agent such as Claude Code may run these commands, each check stops a different thing:

- **Typed confirmation** reads the terminal itself, not stdin, so piping `yes` in doesn't answer it, and an agent's shell has no terminal, so the command stops. It stops accidents, not a determined agent: tools like `script` and `expect` can supply a terminal.
- **A deny rule** in Claude Code's settings, such as `"Bash(github delete*)"` (and `"Bash(github archive*)"`, if agents shouldn't archive either), stops the agent running it by the usual name. It matches command prefixes, so it stops accidents too.
- **The keychain prompt** (macOS) is the check an agent can't pass: only you can type your login password. If it appears when you didn't run `github delete`, deny it.
- **The separate token** means nothing else on the machine holds the `delete_repo` scope, so getting around the command doesn't help.

## How it fits together

```
src/
├── repo_tools/
│   ├── github/
│   │   ├── api.py        GitHub operations, also called by packagist
│   │   ├── manifest.py
│   │   └── commands/     publish.py, release.py, rename.py, archive.py, delete.py
│   └── packagist/
│       ├── api.py        Packagist operations, also called by repo-list
│       └── commands/     publish.py, update.py
└── repo_list/
    ├── scan.py           finding repositories and what needs attention
    ├── report.py
    ├── config.py
    └── fix.py            repo-fix
```

To add a command to `github` or `packagist`, add a module to the service's `commands/` with a `register(subparsers)` function, and list it in that service's `__main__.py`. Put GitHub or Packagist calls another command might need in its `api.py`, and call them from there rather than running the other command.

## Development

```sh
devbox run test   # pytest
devbox run lint   # ruff check and format
```

`tests/repo_tools` and `tests/repo_list` are kept apart because repo-list's `conftest.py` has autouse fixtures, which point HOME at a temporary folder and fake Packagist. Tests use `--import-mode=importlib`, so test files in the two folders can share names; share test helpers through fixtures in `conftest.py`, not by importing it.
