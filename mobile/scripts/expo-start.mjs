import { spawn } from "node:child_process";
import { realpathSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const projectRoot = realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), ".."));
const expoCli = require.resolve("expo/bin/cli");

const child = spawn(
  process.execPath,
  [expoCli, "start", projectRoot, ...process.argv.slice(2)],
  { cwd: projectRoot, stdio: "inherit" },
);

child.on("exit", (code) => process.exit(code ?? 1));

