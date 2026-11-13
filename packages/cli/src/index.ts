/**
 * Crawlee Cloud CLI
 *
 * Commands:
 *   init             Create new Actor from template
 *   run              Run Actor locally
 *   dev              Run Actor with hot reload
 *   push             Push Actor to platform
 *   call <actor>     Call a remote Actor
 *   logs <run-id>    View run logs
 *   status <run-id>  Check run status
 *   login            Authenticate with platform
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Command } from 'commander';
import { initCommand } from './commands/init.js';
import { runCommand } from './commands/run.js';
import { devCommand } from './commands/dev.js';
import { pushCommand } from './commands/push.js';
import { callCommand } from './commands/call.js';
import { logsCommand } from './commands/logs.js';
import { statusCommand } from './commands/status.js';
import { loginCommand } from './commands/login.js';
import { listCommand } from './commands/list.js';
import { profileCommand } from './commands/profile.js';
import { infoCommand } from './commands/info.js';

// Resolve relative to the compiled file at runtime; both src/index.ts and
// dist/index.js sit one level below package.json, so '..' is the same in
// development (tsx) and after build.
const pkgPath = join(dirname(fileURLToPath(import.meta.url)), '..', 'package.json');
const { version } = JSON.parse(readFileSync(pkgPath, 'utf8')) as { version: string };

export const program = new Command();

program
  .name('crawlee-cloud')
  .description('CLI for Crawlee Cloud - create, run, and deploy Actors')
  .version(version);

// Register commands
program.addCommand(initCommand);
program.addCommand(runCommand);
program.addCommand(devCommand);
program.addCommand(pushCommand);
program.addCommand(callCommand);
program.addCommand(logsCommand);
program.addCommand(statusCommand);
program.addCommand(loginCommand);
program.addCommand(listCommand);
program.addCommand(profileCommand);
program.addCommand(infoCommand);

export { program as cli };
