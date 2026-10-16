const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ts = require("typescript");

test("two tabs rotate a shared refresh token only once", async () => {
  const values = new Map([["knowops.access", "old-access"], ["knowops.refresh", "old-refresh"]]);
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  let lock = Promise.resolve();
  const locks = { request: (_name, action) => {
    const result = lock.then(action);
    lock = result.catch(() => {});
    return result;
  } };
  let rotations = 0;
  const fetch = async (url, init) => {
    if (url.endsWith("/refresh")) {
      assert.equal(JSON.parse(init.body).refresh_token, "old-refresh");
      assert.equal(++rotations, 1, "a reused refresh token would revoke the session");
      return Response.json({ access_token: "new-access", refresh_token: "new-refresh" });
    }
    return init.headers.get("Authorization") === "Bearer new-access"
      ? Response.json({ id: "user" }) : Response.json({}, { status: 401 });
  };
  const code = ts.transpileModule(fs.readFileSync("src/lib/api.ts", "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  function tab() {
    const exports = {};
    vm.runInNewContext(code, {
      exports, process: { env: {} }, window: { localStorage: storage },
      navigator: { locks }, fetch, Headers, FormData, URLSearchParams, setTimeout,
    });
    exports.api.hasSession();
    return exports.api;
  }
  const first = tab();
  const second = tab();
  const users = await Promise.all([first.me(), second.me()]);
  assert.deepEqual(users.map((user) => user.id), ["user", "user"]);
  assert.equal(rotations, 1);
  assert.equal(values.get("knowops.refresh"), "new-refresh");
});
