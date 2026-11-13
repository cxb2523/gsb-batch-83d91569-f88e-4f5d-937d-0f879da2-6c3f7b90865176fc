# Installation & Setup Guide

Welcome to **BuildSite**! This guide walks you through setting up BuildSite to display your evolving residential villa inside your GitHub Profile README.

---

## Quick Start (3 Steps)

### Step 1: Create or Open Your Profile Repository
GitHub allows you to show a profile README by creating a repository that matches your GitHub username:
`https://github.com/<your-username>/<your-username>`

If you haven't created it yet:
1. Create a public repository named exactly `<your-username>`.
2. Initialize it with a `README.md`.

### Step 2: Add the BuildSite Workflow
In your profile repository, create a workflow file at `.github/workflows/buildsite.yml`:

```yaml
name: BuildSite

on:
  schedule:
    # Runs daily at 06:00 UTC
    - cron: "0 6 * * *"
  workflow_dispatch: # Allows manual trigger from the Actions tab

permissions:
  contents: write

jobs:
  build:
    name: Evolve Property
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Run BuildSite Action
        uses: buildsite/buildsite@v1
        with:
          username: ${{ github.repository_owner }}
          token: ${{ secrets.GITHUB_TOKEN }}
          output_dir: "assets/buildsite"
          commit_message: "chore(buildsite): update property evolution [skip ci]"
```

### Step 3: Embed in Your README
Add this Markdown reference anywhere in your profile `README.md`:

```markdown
## 🏡 My GitHub Builds My Home

![My Property](assets/buildsite/buildsite.svg)
```

Now head to **Actions** in your repository, select **BuildSite**, and click **Run workflow**.

Within 30 seconds, BuildSite will retrieve your verified contributions, composite your custom architectural villa, commit `assets/buildsite/buildsite.svg`, and your README will display your property!

---

## Configuration Options

To customize your property, create a `buildsite.yml` in the root of your repository:

```yaml
version: 1

github:
  visibility: public

property:
  style: modern       # modern | timber | slate | coastal | auto
  palette: natural
  lighting: dusk      # dusk | daytime | night
  pool: true
  garden: true
  garage: true

render:
  animation: subtle   # subtle | none
  png_fallback: true
```

See [docs/customization.md](customization.md) for full configuration options.

---

## Token Permissions & Privacy

### Built-in `GITHUB_TOKEN`
By default, the workflow uses the repository's built-in `${{ secrets.GITHUB_TOKEN }}`.
The only permission required is `contents: write` so the bot can commit the generated SVG into your `assets/buildsite/` folder.

### Private Contributions
To count contributions from private repositories:
1. Ensure you have enabled **"Private contributions"** in your public GitHub profile settings.
2. If using standard GitHub Actions, public metrics are queried automatically.
3. If you want BuildSite to query private metadata directly, supply a Personal Access Token (PAT) with `read:user` scope as a secret `PAT_TOKEN` in your repository secrets and pass `token: ${{ secrets.PAT_TOKEN }}`.

---

## Local Installation (CLI)

BuildSite can also be installed as a local Python CLI utility:

```bash
pip install buildsite
```

Or from source:

```bash
git clone https://github.com/buildsite/buildsite.git
cd buildsite
pip install -e .
```

Verify the installation:

```bash
buildsite validate
buildsite demo --count 350
buildsite preview
```
