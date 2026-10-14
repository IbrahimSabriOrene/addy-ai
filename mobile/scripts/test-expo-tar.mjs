import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, unlink, rmdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { extractAsync } = require("@expo/cli/build/src/utils/tar.js");
const root = await mkdtemp(join(tmpdir(), "addy-tar-"));
const source = join(root, "source"), target = join(root, "target"), archive = join(root, "fixture.tar");
await mkdir(source); await mkdir(target);
try {
  await writeFile(join(source, "template.txt"), "Addy template fixture");
  execFileSync("tar", ["-czf", archive, "-C", source, "template.txt"]);
  // Exercise the installed CLI extractor, independent of its archive library.
  await extractAsync(archive, target);
  assert.equal(await readFile(join(target, "template.txt"), "utf8"), "Addy template fixture");
  console.log("Installed Expo CLI extracts a standard gzip tar archive correctly");
} finally {
  for (const path of [join(source, "template.txt"), join(target, "template.txt"), archive]) await unlink(path).catch(() => {});
  await rmdir(source); await rmdir(target); await rmdir(root);
}
