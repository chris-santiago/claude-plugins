# claude-plugins

Personal Claude Code plugin marketplace containing:

- **chris-code** — Workflow skills, coding agents, review gates, and quality campaigns
- **ml-lab** — ML hypothesis investigation with critique/defense/review
- **ml-journal** — Persistent session audit trail and research narrative synthesis

See [chris-code/README.md](chris-code/README.md) for the full skill/agent reference and workflow graph.

## Installation

Three methods, depending on what your environment supports.

### Method 1: GitHub Marketplace (recommended)

Add to `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "chris-code": {
      "source": {
        "source": "github",
        "repo": "chris-santiago/claude-plugins"
      }
    }
  },
  "enabledPlugins": {
    "chris-code@chris-code": true,
    "ml-lab@chris-code": true,
    "ml-journal@chris-code": true
  }
}
```

Claude Code fetches and caches the plugins automatically.

### Method 2: Local Directory

For machines with a local clone (e.g., Dropbox sync):

```json
{
  "extraKnownMarketplaces": {
    "chris-code": {
      "source": {
        "source": "directory",
        "path": "/path/to/claude-plugins"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "chris-code@chris-code": true,
    "ml-lab@chris-code": true,
    "ml-journal@chris-code": true
  }
}
```

### Method 3: Manual Cache Install

For machines where the marketplace/plugin system is blocked but `settings.json` is editable:

```bash
# Clone the repo
git clone https://github.com/chris-santiago/claude-plugins /tmp/claude-plugins

# Copy to plugin cache
mkdir -p ~/.claude/plugins/cache/chris-code
cp -r /tmp/claude-plugins/* ~/.claude/plugins/cache/chris-code/

# Clean up
rm -rf /tmp/claude-plugins
```

Then add to `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "chris-code@chris-code": true,
    "ml-lab@chris-code": true,
    "ml-journal@chris-code": true
  }
}
```

No `extraKnownMarketplaces` entry needed — the cache is already "installed."

To update later:

```bash
cd /tmp && git clone https://github.com/chris-santiago/claude-plugins
cp -r claude-plugins/* ~/.claude/plugins/cache/chris-code/
rm -rf claude-plugins
```

## Enabling Individual Plugins

You don't have to enable all three. Pick what you need:

| Plugin | enabledPlugins key | What you get |
|--------|-------------------|--------------|
| chris-code | `"chris-code@chris-code": true` | Workflow skills, coding agents, review gates |
| ml-lab | `"ml-lab@chris-code": true` | ML hypothesis investigation |
| ml-journal | `"ml-journal@chris-code": true` | Session journaling and audit trail |

## Plugin Sources

| Plugin | Canonical source | Notes |
|--------|-----------------|-------|
| chris-code | This repo | Primary development happens here |
| ml-lab | [chris-santiago/ml-lab](https://github.com/chris-santiago/ml-lab) | Copied here via sync hook. See [SYNC.md](SYNC.md) |
| ml-journal | [chris-santiago/ml-lab](https://github.com/chris-santiago/ml-lab) | Copied here via sync hook. See [SYNC.md](SYNC.md) |
