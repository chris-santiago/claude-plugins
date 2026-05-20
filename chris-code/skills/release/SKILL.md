---
name: release
description: >
  Cut a new release: bump version across repo, generate changelog from conventional
  commits, update changelog file, create a GitHub release with tag. Triggered
  explicitly only — never auto-invoked. Use when the user says /release, "cut a release",
  "publish a new version", "bump version and release", or "release X.Y.Z".
---

# Release

Cut a versioned release. User-triggered only.

## Usage

```
/release <version | patch | minor | major>
```

Examples: `/release 0.9.0`, `/release minor`, `/release patch`

---

## Steps

### 1. Discover version files

Scan the project for files that contain version declarations:

| File | Field |
|---|---|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `Cargo.toml` | `version = "X.Y.Z"` |
| `package.json` | `"version": "X.Y.Z"` |
| `setup.cfg` | `version = X.Y.Z` |
| `__init__.py` / `_version.py` | `__version__ = "X.Y.Z"` |
| `VERSION` file | plain version string |

Present the discovered version files and current version to the user.

### 2. Parse version argument

- If arg is `patch`, `minor`, or `major`: read current version, compute next per semver.
- If arg is an explicit version string (e.g., `0.9.0`): validate it is valid semver and greater than current.
- If no arg provided: ask the user what version to release.

**Confirm the computed version with the user before modifying any files.** Show: current version, bump type, proposed new version. Do NOT proceed until confirmed.

### 3. Version consistency — bump all locations

Update the version string in **all** discovered version files.

After bumping, grep the repo for the **old** version string to catch any other references (README badges, docs, etc.). If found, update them or warn the user.

### 4. Generate changelog from commits

Collect commits since the last git tag (or all commits if no prior tag exists). Group by conventional commit prefix:

| Prefix | Section |
|---|---|
| `feat` | **Added** |
| `fix` | **Fixed** |
| `refactor`, `perf` | **Changed** |
| `docs`, `ci`, `chore`, `test`, `build` | **Other** |
| No prefix / unknown | **Other** |

Rules:
- Skip merge commits.
- Strip the prefix and scope from the message for display.
- One bullet per commit. Keep the one-liner — don't expand.
- Drop the **Other** section if empty; always include **Added** and **Fixed** even if empty (just say "None").

### 5. Update changelog file

Look for an existing changelog file (`CHANGELOG.md`, `docs/changelog.md`, `docs/site/changelog.md`, or similar). If found:
- Replace the `## Unreleased` content with `*No unreleased changes.*`
- Insert a `## X.Y.Z` section (with today's date) between `## Unreleased` and the previous release, containing the generated changelog.

If no changelog file exists, create `CHANGELOG.md` at the repo root.

### 6. Present for confirmation

Show the user:
- New version number
- Files modified (with diffs if small)
- Full changelog draft

Ask: **"Ready to commit, tag, push, and create the GitHub release?"**

Do NOT proceed until the user confirms.

### 7. On approval — commit, tag, push, release

```bash
git add -A
git commit -m "release: vX.Y.Z"
git tag vX.Y.Z
git push origin <current-branch>
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "<changelog body>"
```

### 8. Done

Report the release URL. If the project has a CI publish workflow, remind the user it will handle package publishing.

---

## Guardrails

- **Never auto-trigger.** This skill only runs when the user explicitly invokes it.
- **Never push without confirmation.** Step 6 is a hard gate.
- **Fail early on dirty working tree.** If there are uncommitted changes, abort and tell the user to commit or stash first.
- **Fail if on an unexpected branch.** Releases typically come from main/master — warn the user if on a different branch and get confirmation.
- **Run the project's test suite before proceeding.** If tests fail, abort.
- **Don't push before the release commit.** The version bump, changelog, tag, and push should all happen in one shot.
