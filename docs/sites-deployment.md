# Deploy the central dashboard with OpenAI Sites

This guide connects the existing application under `sites-hub/` to OpenAI Sites. In normal use, there is nothing to install *inside* Codex: open the repository in the desktop app and give the request directly to Codex in a conversation where Sites is available. ChatGPT on the web can manage the existing Site and can update source only when that source is available to the conversation.

OpenAI Sites is currently in public beta. Availability and limits can depend on the plan, region, and workspace configuration. Site creation, saved versions, deployments, access, and hosted settings are managed in ChatGPT web or desktop, not through a standalone Codex CLI or IDE management screen.

Official reference: [OpenAI Sites documentation](https://learn.chatgpt.com/docs/sites).

## What is already configured

The repository contains a compatible Sites application in `sites-hub/`:

- `sites-hub/.openai/hosting.example.json` declares the public logical D1 binding shape;
- ignored `sites-hub/.openai/hosting.json` links one local checkout to one Site without publishing its project ID;
- `sites-hub/app/` contains the hosted application;
- `sites-hub/db/` and `sites-hub/drizzle/` contain the checked-in database schema and migrations;
- the root `public/` directory remains the editable source of the shared dashboard UI;
- a Sites build regenerates and copies the same dashboard bundle used by the local and Docker deployments.

The repository deliberately contains no Sites project ID or production URL. On
first deployment, each user must create their own private Site. On later
updates, reuse only the Site linked by their ignored local `hosting.json`.

## Per-user privacy boundary

Keep the Site access policy private and limited to the deploying user's own
account unless they deliberately add another trusted account. Do not reuse
another user's project ID, Site URL, D1 database, ingress, or upstream token.
Separate Sites and D1 bindings make each deployment an independent data silo;
the application additionally scopes Mesh machines and reads to the authenticated
Site owner.

## Prerequisites

Before publishing, confirm that:

1. the repository is cloned and the intended branch or commit is checked out;
2. Sites is available for the current account and workspace in the desktop app or ChatGPT on the web;
3. Node.js 22.13 or newer is available if local verification is required;
4. the person deploying owns the private Site or is explicitly allowed to manage it;
5. secret values are available through an approved secret manager or Sites settings, never through committed files or chat attachments.

## Recommended deployment workflow

### 1. Open the repository and ask Codex to prepare a version

Open the repository as the active local project in the desktop app, then give Codex this request directly:

```text
@Sites Prepare the Sites application in sites-hub/. If the ignored
sites-hub/.openai/hosting.json exists, reuse only that linked Site. Otherwise,
create a new private Site in my account with access limited to me. Never commit
the project ID or production URL. Run the relevant tests and build, then save a
new version without deploying it. Show me the result before changing access,
secrets, or production.
```

This request matters: mentioning `@Sites` starts the Sites workflow explicitly,
while the conditional reuse instruction keeps new users isolated and prevents
existing users from accidentally creating a second project.

### 2. Review the saved version

Ask Codex to report:

- the source branch, commit, and changed files used for the build;
- test and build results;
- the saved Sites version and its status;
- whether a database migration or hosted-setting change is required;
- any difference from the currently deployed version.

A saved version is a deployment candidate. It is not a production publication.

### 3. Deploy the approved version

When the saved version is acceptable, give Codex a second request:

```text
Deploy the approved saved version. Keep the current access policy, database
binding, and runtime settings unchanged, then give me the production URL and
deployment status.
```

Every Sites deployment URL is a production URL. Do not ask for deployment until the version and intended audience have been reviewed.

### 4. Verify production

After deployment:

1. open the production URL as an intended visitor;
2. confirm the access or sign-in behavior;
3. open `/dashboard/index.html` and verify that the centralized dashboard loads;
4. sign in to `/admin` and confirm that the expected machines are listed;
5. verify that no confidential value, raw Codex log, prompt, response, username, or full local path is exposed.

## First deployment or hosted-setting changes

Each user's Site uses its own D1 database through a binding named `DB`. In that
Site's settings:

1. keep the D1 database bound as `DB`;
2. apply only reviewed, checked-in migrations;
3. configure `MESH_PUBLIC_INGRESS_URL` with the canonical HTTPS ingress origin and keep all secrets in Sites settings;
4. choose the narrowest access policy that fits the intended audience;
5. deploy the dedicated [public Mesh ingress](mesh-ingress.md), storing the Site bypass credential only as its encrypted server-side secret;
6. let `/admin` generate the ready-to-copy association command; do not manually provision a credential on reporting machines.

Keep `.openai/hosting.json` local and ignored: it may contain the deployment's
project ID but must never contain a secret. Do not paste secret values into
prompts, documentation, screenshots, or committed `.env` files.

## Local verification for maintainers

From `sites-hub/`:

```bash
npm ci
npm test
npm run lint
```

Run `npm run db:generate` only after a deliberate D1 schema change. Inspect the generated migration before saving or deploying a Sites version.

## Updating an existing deployment

For later releases, use the same two-step workflow: check out the intended
commit, ask Codex to save a new version without deploying, review it, then
authorize deployment. The ignored project linkage in `.openai/hosting.json`
allows a new conversation on that machine to find the user's existing Site.

Changing a secret or hosted environment value does not update a running deployment by itself. Ask Codex to redeploy the approved saved version after the setting is changed.

## Common mistakes

- **Sharing a deployment:** never copy another user's `hosting.json`, Site URL, D1 binding, ingress configuration, or upstream token.
- **Creating a duplicate Site:** when local `hosting.json` exists, explicitly say to reuse it.
- **Publishing while only asking for a preview:** explicitly ask to save without deploying.
- **Editing generated dashboard files:** edit root `public/`; the Sites build copies the generated bundle.
- **Committing deployment linkage:** commit only `hosting.example.json`; keep `hosting.json` ignored even though its project ID is not a credential.
- **Committing a secret:** keep hosted secrets in Sites settings and local secrets in ignored environment files.
- **Changing access unintentionally:** tell Codex to preserve the current access policy unless a change is separately approved.
- **Expecting the CLI to manage Sites:** use ChatGPT web or desktop for Sites operations; use the CLI or IDE only to edit and test source code.

## Next step: connect machines

Once both the private Site and public ingress are deployed, sign in with ChatGPT at `/admin`, select **Add a machine**, and copy the generated association command to the target computer. No Site credential is provisioned on that machine.
