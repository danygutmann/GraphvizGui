import { cp, mkdir } from "node:fs/promises";
import { build } from "esbuild";

const staticDir = new URL("../graphviz_gui/static/", import.meta.url);
const vendorDir = new URL("../graphviz_gui/static/vendor/", import.meta.url);

await mkdir(vendorDir, { recursive: true });
await build({
  entryPoints: [new URL("../frontend/editor.js", import.meta.url).pathname],
  bundle: true,
  minify: true,
  format: "iife",
  target: ["es2020"],
  outfile: new URL("editor.js", staticDir).pathname,
});

const swaggerPackage = new URL("../node_modules/swagger-ui-dist/", import.meta.url);
for (const file of ["swagger-ui-bundle.js", "swagger-ui.css"]) {
  await cp(new URL(file, swaggerPackage), new URL(file, vendorDir));
}
