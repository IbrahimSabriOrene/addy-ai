// Default Expo Metro config. On SDK 51+ this resolves the `@/*` tsconfig
// paths automatically (experiments.tsconfigPaths is on by default).
const { realpathSync } = require("node:fs");
const { getDefaultConfig } = require("expo/metro-config");

// The workspace is exposed through a Windows junction. Metro must use the
// physical path too, otherwise web entry URLs escape the project root.
module.exports = getDefaultConfig(realpathSync(__dirname));
