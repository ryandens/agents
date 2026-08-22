/* eslint-disable @typescript-eslint/no-require-imports */
const Module = require("node:module");

const load = Module._load;

// TypeScript 7 does not expose a JavaScript API until 7.1. Keep ESLint on the
// official TypeScript 6 compatibility package while the project CLI uses TS7.
Module._load = function loadWithTypeScript6(request, parent, isMain) {
  if (request === "typescript") {
    return load.call(this, "@typescript/typescript6", parent, isMain);
  }

  return load.call(this, request, parent, isMain);
};
