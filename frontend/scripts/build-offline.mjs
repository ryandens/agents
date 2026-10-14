import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const out = path.join(root,"out");
async function files(dir) {
  const entries = await readdir(dir,{withFileTypes:true});
  return (await Promise.all(entries.map(e => e.isDirectory() ? files(path.join(dir,e.name)) : path.join(dir,e.name)))).flat();
}
const assets = (await files(path.join(out,"_next","static")))
  .filter(file => !file.endsWith(".map")).map(file => "/" + path.relative(out,file).split(path.sep).join("/")).sort();
const manifest = ["/fitness/","/manifest.webmanifest","/fitness-icon-192.png","/fitness-icon-512.png",...assets];
const hash = createHash("sha256");
for (const url of manifest) {
  // Paths come only from the fixed manifest and this build's _next/static listing.
  // no-dd-sa:javascript-node-security/detect-non-literal-fs-filename
  hash.update(await readFile(path.join(out,url === "/fitness/" ? "fitness/index.html" : url)));
}
// Fixed repository template path, anchored to this script rather than user input.
// no-dd-sa:javascript-node-security/detect-non-literal-fs-filename
const template = await readFile(path.join(root,"public/sw.js"),"utf8");
hash.update(template);
// Fixed output file in the static export directory; no runtime input is accepted.
// no-dd-sa:javascript-node-security/detect-non-literal-fs-filename
await writeFile(path.join(out,"sw.js"),template
  .replace("const PRECACHE = [];",`const PRECACHE = ${JSON.stringify(manifest)};`)
  .replace("fitness-shell-development","fitness-shell-" + hash.digest("hex").slice(0,16)));
console.log(`Offline shell: ${manifest.length} assets precached.`);
