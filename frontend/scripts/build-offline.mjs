import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
// Anchor literal file paths to this script, independent of the caller's cwd.
process.chdir(root);
const out = path.join(root,"out");
async function files(dir) {
  const entries = await readdir(dir,{withFileTypes:true});
  return (await Promise.all(entries.map(e => e.isDirectory() ? files(path.join(dir,e.name)) : path.join(dir,e.name)))).flat();
}
const assets = (await files(path.join(out,"_next","static")))
  .filter(file => !file.endsWith(".map")).map(file => "/" + path.relative(out,file).split(path.sep).join("/")).sort();
const manifest = ["/fitness/","/manifest.webmanifest","/fitness-icon-192.png","/fitness-icon-512.png",...assets];
const hash = createHash("sha256");
// Next.js versions static assets by content hash. Hash their manifest names,
// and hash the contents of the unversioned shell files explicitly.
hash.update(JSON.stringify(manifest));
hash.update(await readFile("out/fitness/index.html"));
hash.update(await readFile("out/manifest.webmanifest"));
hash.update(await readFile("out/fitness-icon-192.png"));
hash.update(await readFile("out/fitness-icon-512.png"));
const template = await readFile("public/sw.js","utf8");
hash.update(template);
await writeFile("out/sw.js",template
  .replace("const PRECACHE = [];",`const PRECACHE = ${JSON.stringify(manifest)};`)
  .replace("fitness-shell-development","fitness-shell-" + hash.digest("hex").slice(0,16)));
console.log(`Offline shell: ${manifest.length} assets precached.`);
