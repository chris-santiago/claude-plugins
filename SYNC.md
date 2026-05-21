# Plugin Sync: ml-lab and ml-journal

## Canonical Source

The `ml-lab/` and `ml-journal/` directories in this repo are **copies**, not canonical sources.

**Canonical source:** `https://github.com/chris-santiago/ml-lab`
- `ml-lab/` ← `ml-lab repo: plugins/ml-lab/`
- `ml-journal/` ← `ml-lab repo: plugins/ml-journal/`

**Do not edit these directories here.** Edits will be overwritten on the next sync.

## How Sync Works

A PostToolUse hook in the ml-lab repo (`ml-lab/.claude/hooks/sync-plugin-cache.sh`) fires on every Edit or Write to files under `plugins/ml-lab/` or `plugins/ml-journal/`. It rsyncs to two destinations:

1. **Plugin cache** (`~/.claude/plugins/cache/ml-lab/...`) — for local plugin loading
2. **This directory** (`~/Dropbox/claude-config/plugins/ml-lab/` and `ml-journal/`) — for git distribution

The hook runs automatically during any ml-lab Claude Code session. No manual sync needed.

## Why Copies Exist Here

This marketplace (`chris-code`) bundles all personal plugins for deployment to machines where the plugin install mechanism is blocked. On such machines, one clone of this repo provides access to chris-code, ml-lab, and ml-journal via a single marketplace entry.

On the home machine, ml-lab and ml-journal are loaded from the ml-lab marketplace (canonical source). The copies here are inert unless explicitly enabled in settings.json.

## Manual Sync (if needed)

```bash
rsync -a --exclude='.orphaned_at' \
  ~/Dropbox/GitHub/ml-lab/plugins/ml-lab/ \
  ~/Dropbox/claude-config/plugins/ml-lab/

rsync -a --exclude='.orphaned_at' \
  ~/Dropbox/GitHub/ml-lab/plugins/ml-journal/ \
  ~/Dropbox/claude-config/plugins/ml-journal/
```
