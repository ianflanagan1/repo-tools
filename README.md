# repo-tools

Command line tools for repositories, in steps that are safe to re-run:

| Command | What for |
|---|---|
| [`github`](#github-and-packagist) | Publishing, releasing, renaming, archiving and deleting repos on GitHub |
| [`bitbucket`](#bitbucket) | Publishing, releasing, renaming and deleting repos on Bitbucket Cloud |
| [`packagist`](#github-and-packagist) | Publishing packages on Packagist and keeping them current |
| [`npmjs`](#npmjs) | Publishing packages on npm, then publishing each version tag from GitHub Actions |
| [`repo-list`](#repo-list) | Reporting the state of every git repository under a directory |
| [`repo-fix`](#repo-fix) | Fixing what repo-list reports |

`github` and `bitbucket` also read a repo's [delivery data](#delivery-data): its deployments, merged pull requests and the commits between two revisions, the raw material for DORA metrics. They're built on [cli-kit](../cli-kit), so every command has the same help and ends with one status line, ✅ ➖ ⚠️ ❌ or 🛑.

## `github` and `packagist`

`github help` (or `-h`, `--help`, or no command at all) lists the commands with their arguments; `github help <command>` or `github <command> --help` shows one in full. The same goes for `packagist`.

### `github publish [<dir>] [<repo-name>] [--private] [--no-ci-wait]`

1. Creates the repo under the account `gh` is logged in as, with the description from the project's manifest when it has one: `composer.json`, `package.json`, `Cargo.toml`, `pyproject.toml`, `pom.xml`, `*.csproj` or `*.gemspec`. Without one, the model of the configured `description.provider` writes it from the tracked files' names and the README, CLAUDE.md, AGENTS.md and manifests among them, and the command prints it. Nothing untracked is read. A reply that isn't one line of at most 350 characters, or no reply, leaves the repo with no description. An existing repo is never edited; if its visibility differs from the one asked for, it stops.
2. Adds it as the `origin` remote, or checks that `origin` already points at it.
3. Pushes the current branch and all tags.
4. Waits for the CI run on the pushed commit, when the repo has a workflow, and prints the failing log on failure. `--no-ci-wait` skips this, such as when publishing many repos at once.

`dir` defaults to the current directory and `repo-name` to the directory's name. The repo is public unless you pass `--private`. Each step is skipped when it's already done, so after a failure you fix the cause and run it again. It refuses a work tree with uncommitted changes or a detached HEAD.

### `github release <dir> <patch|minor|major>`

1. Tags `HEAD` as the next version: the highest `[v]MAJOR.MINOR.PATCH` tag, bumped at the level you give. A project with no version tags starts from `0.0.0`, so its first `minor` release is `v0.1.0`. The tag keeps the highest tag's style, with or without the `v`.
2. Pushes the tag. Packagist's webhook then picks it up; run `packagist update <dir>` to wait until it has. For an npm package, its publish workflow publishes it; run `npmjs wait <dir>` to wait until it has.
3. Creates the GitHub release, with notes GitHub generates from the commits since the last one.

It fetches origin's tags first, so a tag pushed from another machine counts. It refuses uncommitted changes, a detached `HEAD`, and a `HEAD` not yet on origin, so a release is always of what's on GitHub. Pre-release tags such as `v2.0.0-beta1` don't count. A `HEAD` that already has a version tag is released as that version, whatever level you give, so running it again after a failure finishes the same release rather than making another, and no tag is ever moved.

Choosing the level is yours: `patch` for fixes, `minor` for new features, `major` for breaking changes. Below 1.0.0, Composer's `^0.2` treats each minor as possibly breaking.

### `github rename <dir> <new-name>`

1. Renames the GitHub repo that `dir`'s `origin` names, keeping its owner.
2. Points `origin` at the new name, in the same SSH or HTTPS form.
3. When `dir` is a Composer package that Packagist has, points the package at the new URL. This needs the Packagist main token.

GitHub redirects the old name to the new one, for git, web links and the API, until you or someone else creates a repo with the old name. Packagist, though, matches the webhook's pushes to a package by its stored repository URL, which is why step 3 exists. Each step is skipped when it's already done. The local directory keeps its name; rename it yourself if you want.

### `github view <repo>`

Prints a repo's visibility, description and topics as one JSON object, then a status line, so `grep '^{'` keeps only the data. `repo` is `owner/name`, or a name owned by you. It changes nothing.

### `github edit <repo> [--description <text>] [--add-topic <topic>]...`

Sets a repo's description and adds topics, repeating `--add-topic` for each. `repo` is `owner/name`, or a name owned by you. Only what differs is sent, and nothing is done when the repo already matches. It deliberately can't change anything else, such as visibility or the name, so it can be allowed where `gh repo edit` is denied.

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

## `npmjs`

Packagist reads a repo's tags, but npm only has what's uploaded to it. So once a package is on npm, its GitHub Actions workflow `.github/workflows/publish.yml` publishes it on each version tag, with provenance and no token, through npm's trusted publishing. `github release` is then the whole release: it pushes the tag, and the workflow sets `package.json`'s version from it and publishes.

npm runs from the package's own devbox (`devbox run -- npm`), which must have `nodejs` with npm 11.15 or later, logged in there as you. Nothing needs npm on the PATH, and `npmjs` never reads a token.

### `npmjs publish <dir>`

1. When npm doesn't have the package yet, publishes it from your clone as the version tag at `HEAD`, the highest if there are several, with `package.json` given that version for the publish and put back after. npm can't trust a workflow to publish a package that doesn't exist, so the first version goes from your machine. Run `github release <dir> minor` first; the tree must be clean.
2. Trusts the repo's `publish.yml` to publish the package (`npm trust github … --allow-publish`), unless npm already does.

Before changing anything it checks that `origin` is a public GitHub repo (provenance needs one), that `package.json` isn't private and names that repo as its `repository`, that the workflow and `devbox.json` exist, and that you're logged in to npm. npm asks for a one-time password for each step, in your terminal. If npm already trusts some other publisher for the package, it stops and gives the command that revokes it, rather than replacing it. Each step is skipped when it's already done.

npm is reported to drop a trusted publisher no publish has used within 48 hours (npm's own docs don't say so), so release again soon after the first `npmjs publish`.

### `npmjs wait <dir>`

Waits up to ten minutes until npm has every version tag on `origin`, which is how you know the workflow published what `github release` pushed. It compares against `git ls-remote origin` and the registry's own metadata; tags older than the package's first version on npm, and tags that aren't versions, don't count. On a timeout it gives the workflow's runs page.

There's no command for renaming or deprecating a package: run `npm deprecate` in the package's devbox.

## `bitbucket`

The same as `github`, for Bitbucket Cloud, through its REST API with your own API token (see [Bitbucket](#bitbucket-1)). A repo is `workspace/name`, or a bare name in the workspace set as `bitbucket.workspace` in the [config](#config). Git goes over SSH with your own key.

### `bitbucket publish [<dir>] [<repo-name>] [--private] [--project <key>] [--no-ci-wait]`

As `github publish`, creating the repo in the configured workspace, with the slug in lower case, in the workspace's default project unless `--project` names one. When the directory has a `bitbucket-pipelines.yml` it turns Pipelines on before pushing, since Pipelines runs only on pushes made while it's on, then waits for the pipeline on the pushed commit and prints the failed step's log on failure.

### `bitbucket release <dir> <patch|minor|major>`

As `github release`, but Bitbucket has no releases of its own: the pushed version tag is the release.

### `bitbucket rename <dir> <new-name>`

As `github rename`: renames the repo, which gives it the new name's slug, points `origin` at it, and points the package on Packagist at the new URL when Packagist has it from this repo. Unlike GitHub, Bitbucket doesn't redirect the old slug, for git or its API, so every other clone needs its `origin` pointed at the new one: `git remote set-url origin git@bitbucket.org:<workspace>/<new-name>.git`.

### `bitbucket delete <repo>`

As `github delete`: after you type `workspace/name` at the terminal, it deletes the repo with a separate token holding only the `delete:repository:bitbucket` scope, read from the credential store only after you've confirmed.

There's no `bitbucket archive`: Bitbucket Cloud can't archive a repo.

## Delivery data

`github` and `bitbucket` have the same four commands for reading what a repo delivered, written once against the interface in `repo_tools/forge.py`, so their output is alike whichever host it is:

| Command | Prints |
|---|---|
| `environments <repo>` | the repo's deployment environments |
| `deployments <repo> <environment> [--since <date>]` | the deployments there, newest first, each with its commit, status (`succeeded`, `failed`, `stopped`, `in_progress`), and when it started and finished |
| `merged <repo> [--base <branch>] [--since <date>]` | the pull requests merged since then, newest first, each with when it opened and merged and its merge commit |
| `commits <repo> <base> <head>` | the commits in `head` and not in `base`, as `git log base..head`, newest first, each with when it was written |

Each prints one JSON object per line, then its status line, so `grep '^{'` keeps only the data. `--since` is a date or time, in UTC unless it gives its offset, and 30 days ago unless given. The environment is matched ignoring case. Nothing is stored: each run asks the host.

They're the raw material for the DORA metrics. What a project needs for those, in Bitbucket and Jira, in its repository, in its team's habits and on the collecting machine, and which of those changes repo-tools can make with whose consent, is in dora-tools' [docs/requirements.md](../dora-tools/docs/requirements.md), and `dora check` checks a project against it.

The hosts differ underneath:

- **GitHub** deployments are its deployments API, which Actions fills for each job that names an `environment:`. A deployment's status is its latest; GitHub marks a successful one inactive once a newer one succeeds, so inactive counts as succeeded. A workflow with several jobs in one environment makes a deployment for each.
- **Bitbucket** deployments are those Pipelines records for each step with a `deployment:` environment. Bitbucket stops listing a deployment once its pipeline's artifacts expire, so older history can't be read back. It doesn't say when a pull request merged, so that's its merge commit's date, at a request per pull request.

## `repo-list`

Reports the state of every git repository under a directory, so nothing is left uncommitted or unpushed; [repo-fix](#repo-fix) fixes what it can.

```
$ repo-list --fetch
✘ 🏠 🐙 🌐 blog          main  📝 3 uncommitted files  📤 2 unpushed on main
✘          notes               📁 not a git repository
✘ 🔀 🔌    work/website  main  🔌 no remote

✘ 3 of 6 need attention
```

Each repository needing attention is listed by its path from the root, in name order, with ✘ and what needs attention. Clean ones are left out unless you ask for them with `-a` (`--all`), when they're listed with ✔:

- 📝 **uncommitted files**: changed, staged or untracked
- 📤 **unpushed on *branch***: commits on a local branch that are on no remote, whether or not the branch has an upstream: on the trunk in local mode, on any other branch in the PR modes (see [Worktrees and integration modes](#worktrees-and-integration-modes))
- 📥 **behind on *branch***: commits on the branch's upstream that it lacks, as of the last fetch
- 🛬 **unmerged on *branch***: in local mode, commits on a branch other than the trunk that aren't on it yet: work still to land
- ⛔ **commits on *trunk***: in the PR modes, commits made on the trunk, which belong on a branch
- 🔄 **behind *base***: HEAD lacks commits its base has, which repo-fix brings in
- ⚡ **conflicts with *base***: HEAD is behind its base, and bringing the base's commits in would conflict
- 🔃 **no pull request for *branch***, or ***host* couldn't say**: in the PR modes, with `--fetch` only, for the branch checked out
- 👻 **commits on detached HEAD**: commits reachable from no branch or remote
- 📦 **stashes**
- 🔌 **no remote**
- 📁 **not a git repository**: a directory that holds files but is in no repository, such as a project not yet initialised
- 📡 **fetch failed**: with `--fetch` only
- 💥 **git failed**: git couldn't read the repository
- 🔧 **Set `integration` in .workspace.toml under [repo-tools]**, or what's wrong with the mode set: shown alone, as nothing else can be judged without it, and repo-fix leaves the repository alone
- 🐘 **not on Packagist**, **Packagist lacks *versions or branches***, or **Packagist check failed**: with `--packagist` only, for a package of your vendor's (see [Packagist](#packagist))
- 🟥 **not on npm**, **npm lacks *versions***, or **npm check failed**: with `--npm` only, for a package of your scope's (see [npm](#npm))

Between the mark and the path, three icons say what kind of repository it is, explained here rather than on every line: its integration mode, the host of its remote, and who can see the remote.

| Mode | | Host | | Visibility | |
|---|---|---|---|---|---|
| 🏠 | `local` | 🐙 | GitHub | 🌐 | public |
| 📏 | `pr-rebase` | 🦊 | GitLab | 🔒 | private |
| 🔀 | `pr-merge` | 🧺 | Bitbucket | | |
| 🔧 | none set, or one that doesn't exist | 🗻 | Codeberg | | |
| | | 🔷 | Azure DevOps | | |
| | | ❔ | another host, such as your own server, or a path | | |
| | | 🔌 | no remote | | |

The host is told from the remote's URL. Who can see the remote is asked of GitHub or Bitbucket, so it's shown only with `--fetch`, and left blank for another host or one that can't say. A linked worktree leaves all three blank, as its main worktree shows them, unless its own `.workspace.toml` sets a different mode. Every icon is from Unicode 11 or earlier, the widths VS Code's terminal knows, so the columns line up there.

After the path is what each repository has checked out: its branch, or `@` and the commit for a detached HEAD, such as `@3f2a1c9`. It's shown, never counted as needing attention; commits only a detached HEAD has are reported as 👻. The default branch, as [git-default-branch](../git-default-branch) tells it, is grey, so any other stands out. 🤖 **Claude working** follows it when a Claude Code session is busy there, as recorded by the [worktree-hooks](../../claude/worktree-hooks) plugin; repo-fix then leaves the directory alone.

The last line totals them, listed or not, for when the list scrolls off the screen: `✘ 3 of 6 need attention`, or `✔ All 6 clean`, which is then the only line.

On a terminal the parent path is grey, the repository's name is bold, the default branch is grey and the problems are yellow. `NO_COLOR=1` turns colour off; `FORCE_COLOR=1` keeps it when piping.

### How it searches

It assumes repositories are not nested, so it stops descending at each one and never walks into `node_modules`, `vendor` and the like. A directory holding only directories, such as `work/`, is a group and is searched. A directory holding any file (other than `.DS_Store`) is a project, and is reported if it is not a repository. Empty directories, hidden directories and symlinks are skipped.

### Worktrees and integration modes

Each directory reports only on its own HEAD, and the main worktree also on every branch no worktree has checked out. So a repository's linked worktrees never repeat what its main worktree says about the branches they share, and each problem is listed where you'd fix it. The trunk is the repository's default branch, as [git-default-branch](../git-default-branch) tells it, never assumed to be `main`.

How a branch's work reaches the trunk is the integration mode, which each repository sets in the `[repo-tools]` table of its committed `.workspace.toml`, so its team shares it:

```toml
[repo-tools]
integration = "local"
```

There's no default, and no machine-wide setting, as a wrong guess would push or rewrite the wrong things: a repository that sets none is reported as 🔧 and left alone by repo-fix.

| Mode | The trunk | Other branches and detached HEADs |
|---|---|---|
| `local` | committed on, rebased onto its upstream, pushed | rebased onto the local trunk, never pushed; their work is landed by hand, and reported as 🛬 until it is |
| `pr-rebase` | only follows its upstream; commits on it are ⛔ | rebased onto the trunk on the remote, pushed with a lease, and given a draft pull request |
| `pr-merge` | the same | the trunk on the remote merged in, pushed, and given a draft pull request |

In the PR modes a detached HEAD isn't caught up or pushed: it needs a branch first, and its commits are reported as 👻.

### Packagist

A repository whose `composer.json` names a package of your Packagist vendor's, `packagist.vendor` in the [config](#config), should be on Packagist, offering every version tag and the latest commit of every branch on `origin`. Which repositories those are is read from the repositories themselves, so there's nothing to configure as packages come and go. The check is [`packagist update`](#packagist-update-dir)'s. It needs the network, so it runs only with `-p` (`--packagist`), and not for a repository whose fetch failed. A `composer.json` of `"type": "project"` is an app, not a package, so it isn't checked.

### npm

A repository whose `package.json` names a package in your npm scope, `npm.scope` in the [config](#config), and isn't `"private": true`, should be on npm with every version tag on `origin`, from the package's first version on npm. `private` is npm's own mark for what's never to be published, so a monorepo's root or an app stays out by saying so in its manifest, which it already does to stop an accidental `npm publish`. The check is [`npmjs wait`](#npmjs-wait-dir)'s. Like Packagist's it needs the network, so it runs only with `--npm`, and not for a repository whose fetch failed.

### Usage

```
repo-list [-a|--all] [-f|--fetch] [-p|--packagist] [--npm] [<root>]
```

`root` defaults to the configured root, wherever you run it from. `-a` lists clean repositories too. `-f` runs `git fetch --all` in every repository first, eight at a time, so the behind counts are current. `-p` checks each package against Packagist, and `--npm` against npm. Without any of them, nothing touches the network.

Exit status: 0 all clean, 1 something needs attention, 2 usage error.

## `repo-fix`

Fixes what repo-list reports, in one repository or in every one under a directory.

```
repo-fix [--init] [--no-ci-wait] [-p|--packagist] [--npm] [<path>]
```

`path` is a repository, or a directory to search as repo-list does; it defaults to the configured root, wherever you run it from. Every repository is fetched first, once for all of its worktrees. Then each directory is fixed, a repository's worktrees one after another, the one that updates the trunk first: the one with it checked out, or else the main worktree. So the others catch up with the trunk as it now is, and if updating it fails, nothing is caught up with it. In each:

| Problem | Fix |
|---|---|
| 📝 uncommitted files | Claude Code's `/ianf-commit` skill, run headless (`claude -p /ianf-commit`) |
| 🔌 no remote | `github publish`, so public and waiting for CI unless `--no-ci-wait` |
| 📥 behind | fast-forwarded to the upstream, whether the branch is checked out or not; in local mode, a trunk checked out here with commits of its own has them rebased onto the upstream |
| 🔄 behind its base | rebased onto it, or in `pr-merge` mode the base merged in; one that stops at a conflict is undone |
| 📤 unpushed | pushed to the upstream, with a lease after a rebase in `pr-rebase` mode; a branch with none is pushed to the only remote and tracks it |
| 🔃 no pull request | opened as a draft, through `gh` on GitHub or the API on Bitbucket, whose token then needs `write:pullrequest:bitbucket` |
| 📁 not a git repository | with `--init` only: `git init`, then committed and published |
| 🐘 Packagist | with `-p` only, after pushing: `packagist publish`, which also adds a missing webhook, then `packagist update`, which waits until Packagist has what was pushed |
| 🟥 npm | with `--npm` only, after pushing: for a package not on npm, `npmjs publish`, which needs your terminal for npm's one-time passwords and a version tag at `HEAD`; then `npmjs wait`, which waits until the package's publish workflow has published every version tag |

Everything but writing the commits is deterministic. The commit step is checked before and after: it doesn't start during a merge, rebase, cherry-pick or revert, or on the trunk in the PR modes, and it counts as done only if the work tree is then clean, on the same branch or detached HEAD, with the earlier commits untouched. It judges by git's state, not by what Claude says, because a skill that fails to load still ends in success with nothing done. If the commit step fails, nothing else happens in that repository.

Nothing is forced, except a branch rebased in `pr-rebase` mode, pushed `--force-with-lease --force-if-includes`, which git refuses if its upstream has commits never fetched here. A branch both behind and unpushed has diverged and is left alone, but for the trunk in local mode; so are stashes, and HEAD when catching up would conflict (⚡). A repository whose fetch failed is neither pushed nor pulled. A directory where a Claude Code session is busy is left alone entirely, except by the session running repo-fix itself.

Each repository it changed is listed with what was done, then it ends with repo-list's report of what's left:

```
$ repo-fix
blog
  ✔ Committed a1b2c3d Add the draft about devbox
  ✔ Pushed main to origin
work/website
  ✘ Not syncing main: it has diverged from origin/main

✘ work/website  main  📤 1 unpushed on main  📥 2 behind on main

✘ 1 of 3 need attention
```

On a terminal what was done is coloured as repo-list colours its report, with what failed in yellow and the details under it, such as what Claude said, in grey.

Packagist is checked again after pushing, since whatever was pushed is new to it. The Packagist step is skipped when committing or publishing to GitHub failed, and `packagist update` when `packagist publish` failed. npm is the same: `npmjs wait` is skipped when `npmjs publish` failed.

It needs `claude` on the PATH, logged in, and the commit skill at `~/.claude/skills/ianf-commit`. The skill's files may be symlinks into another repository; repo-fix lets Claude read wherever they lead.

Exit status: 0 all clean afterwards, 1 something still needs attention, 2 usage error.

## Setup

Once per machine:

```sh
cd ~/projects/cli/repo-tools
devbox run setup
```

That runs `uv sync`, which builds `.venv` with cli-kit (from GitHub) and these tools installed, then links each command into `~/.local/bin`, or `$XDG_BIN_HOME`. It says so if that directory isn't on your PATH, or if another command of the same name comes first. Run it again after moving the checkout.

The commands in `.venv/bin` are console scripts pointing at the Python devbox pins, so they start without devbox, which is slower and prints its own error line whenever a command fails. cli-kit puts this directory's devbox packages, such as `gh`, first on the PATH for the programs a command runs. After pulling changes, here or in cli-kit, run `devbox run -- uv sync` to bring `.venv` up to date.

### Config

Setup also copies `config.example.toml` to `config.toml`, if you have none, for your own settings. Git ignores `config.toml`, as a PHP project's `.env`, so the repository holds no one's personal settings. A setting left out takes its default:

| Setting | Default | What for |
|---|---|---|
| `root` | `~/projects` | where repo-list and repo-fix look when given no directory |
| `packagist.vendor` | none | whose packages `-p` checks; `-p` without it is a usage error |
| `npm.scope` | none | whose packages `--npm` checks, such as `@me`; `--npm` without it is a usage error |
| `bitbucket.workspace` | none | the workspace `bitbucket publish` creates repos in, and a bare repo name is in |
| `description.provider` | `claude` | who writes a new GitHub or Bitbucket repo's description when its manifest has none: `claude`, through Claude Code signed in as you; `openai`, `gemini` or `mistral`, through their APIs with a key from your credential store, which the first use says how to store; or `none` |

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

Only if you'll use `github delete`. Create a second classic token with only the `delete_repo` scope, and store it under your GitHub username. Until it's stored, `github delete` stops and prints the command that stores it on your system.

On macOS that command trusts no app with the token (`-T ''`), so each time `github delete` reads it, macOS asks for your login password. Choose **Allow**, never **Always Allow**, which would remove that check. The Secret Service keyring on Linux doesn't ask on each read, so there the typed confirmation is the only check.

### Bitbucket

Only if you'll use `bitbucket`. It needs two things from your Atlassian account:

1. **Your SSH key** on Bitbucket, at *Personal settings → SSH keys*, so `git push` reaches `git@bitbucket.org`. `ssh -T git@bitbucket.org` says whether it does.
2. **An API token with scopes**, at <https://id.atlassian.com/manage-profile/security/api-tokens>: choose *Create API token with scopes*, then Bitbucket, then only these:

   | Scope | Needed for |
   |---|---|
   | `read:repository:bitbucket` | reading repos and commits |
   | `admin:repository:bitbucket` | creating and renaming repos, and turning Pipelines on |
   | `read:pullrequest:bitbucket` | `merged` |
   | `read:pipeline:bitbucket` | waiting for pipelines, `environments` and `deployments` |

   Store it under the email you sign in to Atlassian with. The first command that needs it stops and prints the command that stores it on your system. App passwords no longer work, and Jira's unscoped token isn't accepted.

For `bitbucket delete`, create a second token with only `delete:repository:bitbucket`; `bitbucket delete` likewise says how to store it, on macOS so the keychain asks for your password on each read.

### Store the Packagist API tokens

Only if you'll use `packagist`. Sign in at <https://packagist.org> with GitHub; your first submission claims your vendor name. Your profile page has two tokens:

| Token | Used for | Why that one |
|---|---|---|
| Main | submitting a new package, and `github rename` | Only the main token can create packages or change their repository URL. It stays in your credential store. |
| Safe | the webhook secret, and `packagist update` | The secret is stored on GitHub. The safe token can only trigger package updates, so it does little harm if it leaks. |

Store both under your Packagist **username**, which can differ from your vendor name. A command that needs one that isn't stored stops and prints the command that stores it on your system, which prompts for the token so it never lands in your shell history.

Tokens are only ever held in memory: never put on a command line or written to a file.

### Log in to npm

Only if you'll use `npmjs`. Turn on two-factor authentication for your npm account, which `npm trust` needs, then in a package's directory run `devbox run -- npm login`. npm keeps the login in `~/.npmrc`, so every package's devbox shares it.

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
│   ├── forge.py          the interface every code host's delivery data is read through
│   ├── forge_commands.py the delivery commands, written once against it
│   ├── clone.py          a local clone's origin, and pushing from it, on any host
│   ├── versions.py       version tags, and the next one at each level
│   ├── manifest.py       a project's description and Composer package name
│   ├── github/
│   │   ├── api.py        GitHub operations, also called by packagist
│   │   ├── forge.py      GitHub's Forge
│   │   └── commands/     publish.py, release.py, rename.py, archive.py, delete.py
│   ├── bitbucket/
│   │   ├── api.py        Bitbucket Cloud's REST API
│   │   ├── forge.py      Bitbucket's Forge
│   │   └── commands/     publish.py, release.py, rename.py, delete.py
│   ├── packagist/
│   │   ├── api.py        Packagist operations, also called by repo-list
│   │   └── commands/     publish.py, update.py
│   └── npmjs/
│       ├── api.py        npm operations, through each package's devbox
│       └── commands/     publish.py, wait.py
└── repo_list/
    ├── scan.py           finding repositories, where each stands among its worktrees, and
    │                     running the plugins' checks of each
    ├── integration.py    the integration modes: what each directory reports about its branches,
    │                     what repo-fix does about it, and in what order; pure
    ├── agents.py         whether a Claude Code session is busy in a directory
    ├── hosts.py          GitHub and Bitbucket: a repo's visibility, and its pull requests
    ├── plugin.py         what a plugin is, and the stages repo-fix runs fixes in
    ├── plugins/          init, github, uncommitted, sync, proposal, detached, stashes,
    │                     packagist, npm
    ├── git.py
    ├── report.py
    ├── config.py
    └── fix.py            repo-fix: running the plugins' fixes, stage by stage
```

Everything repo-list reports, other than a failed fetch or git failing to read a repository, is found by a plugin, and everything repo-fix does is a plugin's fix. To add one, add a module to `plugins/` with a class following `Plugin` in `plugin.py`, whose problems each `describe()` themselves, and list it in `plugins/__init__.py`, in the order its problems should be shown. Its `stage` sets when its fix runs.

To read something new from every code host, add an abstract method to `Forge` in `forge.py`, implement it in each host's `forge.py`, and state it in `tests/repo_tools/test_forge_contract.py`, which runs every test against every host. A host left without it fails as soon as it's made. Adding a host is a subclass of `Forge` and a fake for it in that test.

To add a command to `github`, `bitbucket`, `packagist` or `npmjs`, add a module to the service's `commands/` with a `register(subparsers)` function, and list it in that service's `__main__.py`. Put GitHub or Packagist calls another command might need in its `api.py`, and call them from there rather than running the other command. What's the same on every host, such as git and version tags, goes in the modules beside the services, not in one service's.

## Development

```sh
devbox run test   # pytest
devbox run lint   # ruff check and format
```

`tests/repo_tools` and `tests/repo_list` are kept apart because repo-list's `conftest.py` has autouse fixtures, which point HOME at a temporary directory and fake Packagist and npm. Tests use `--import-mode=importlib`, so test files in the two directories can share names; share test helpers through fixtures in `conftest.py`, not by importing it.
