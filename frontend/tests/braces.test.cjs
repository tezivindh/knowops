const { test } = require("node:test");
const assert = require("node:assert/strict");
const braces = require("braces");

test("normal glob expansion still works", () => {
  assert.deepEqual(braces.expand("src/{app,lib}/*.{ts,tsx}"), [
    "src/app/*.ts", "src/app/*.tsx", "src/lib/*.ts", "src/lib/*.tsx",
  ]);
});

test("deep brace and parenthesis patterns are rejected before recursive processing", () => {
  for (const [open, close] of [["{", "}"], ["(", ")"]]) {
    for (const operation of [braces.compile, braces.expand, braces.stringify]) {
      assert.throws(() => operation(open.repeat(4000) + "a,b" + close.repeat(4000)),
        /nesting exceeds 128/);
    }
  }
});
