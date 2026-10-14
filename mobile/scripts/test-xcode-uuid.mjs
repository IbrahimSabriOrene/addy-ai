import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const xcode = require("xcode");
const parser = require("xcode/lib/parser/pbxproj");
const project = xcode.project("unused.pbxproj");
project.hash = parser.parse(`// !$*UTF8*$!
{
  archiveVersion = 1;
  classes = {};
  objectVersion = 54;
  objects = {
    /* Begin PBXGroup section */
    AAAAAAAAAAAAAAAAAAAAAAAA = { isa = PBXGroup; children = (); sourceTree = "<group>"; };
    /* End PBXGroup section */
  };
  rootObject = AAAAAAAAAAAAAAAAAAAAAAAA;
}
`);
// Use the consumer's real CommonJS import, ID generation, writer and parser.
const group = project.addPbxGroup([], "AddyAssets", "Assets");
assert.match(group.uuid, /^[A-F0-9]{24}$/);
const ids = new Set(Array.from({ length: 1000 }, () => project.generateUuid()));
assert.equal(ids.size, 1000);
for (const id of ids) assert.match(id, /^[A-F0-9]{24}$/);
const saved = parser.parse(project.writeSync());
assert.equal(saved.project.objects.PBXGroup[group.uuid].name, "AddyAssets");
assert.equal(saved.project.objects.PBXGroup[group.uuid].path, "Assets");
console.log("Xcode UUID generation and project write/parse round trip passed");
