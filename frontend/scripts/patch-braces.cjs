// Temporary mitigation for GHSA-vfj7-8cjw-p6xm until upstream ships a fix.
// Limit AST nesting before recursive compile/stringify/expand can exhaust the stack.
const fs = require("node:fs");
let filename;
try {
  filename = require.resolve("braces/lib/parse");
} catch (error) {
  // Production installs omit the lint toolchain, including braces.
  if (error.code === "MODULE_NOT_FOUND") process.exit(0);
  throw error;
}
let source = fs.readFileSync(filename, "utf8");
const marker = "KnowOps nesting limit";
if (!source.includes(marker)) {
  const needle = "      stack.push(block);";
  if (source.split(needle).length !== 3) {
    throw new Error("braces parser changed; review the nesting-limit patch before installing");
  }
  source = source.replaceAll(needle, [
    "      // KnowOps nesting limit: bound recursive AST consumers.",
    "      if (stack.length >= 128) throw new SyntaxError('Brace pattern nesting exceeds 128');",
    needle,
  ].join("\n"));
  fs.writeFileSync(filename, source);
}
