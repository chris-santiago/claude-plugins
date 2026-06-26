# Cut a release

Use this to publish a new version. It is triggered explicitly only — never auto-invoked.

## Steps

1. **Invoke the release skill:**

    ```
    /release
    ```

    or say "cut a release" / "release X.Y.Z".

2. **It bumps the version** across the repo's version-bearing files.

3. **It generates the changelog** from conventional commits since the last release and updates the changelog file.

4. **It creates the GitHub release** with the tag.

## You have now

Published a versioned release: the version is bumped consistently across the repo, the changelog reflects the conventional commits since the last tag, and a tagged GitHub release is live.

!!! tip "Conventional commits"
    The changelog quality depends on commit hygiene — `feat:`, `fix:`, `chore:` prefixes in imperative mood. The release skill reads those prefixes to group and categorize the changelog.
