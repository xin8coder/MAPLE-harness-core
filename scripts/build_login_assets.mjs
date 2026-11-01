import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFile, writeFile, readdir } from 'node:fs/promises';
import { brotliCompressSync, gzipSync, constants } from 'node:zlib';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const modules = process.env.LANCHOU_BUILD_NODE_MODULES || resolve(root, 'deploy/sandbox/asset-tools/node_modules');
const require = createRequire(resolve(modules, '../package.json'));
const { build, transform } = require('esbuild');
const sharp = require('sharp');
const output = resolve(root, 'deploy/sandbox/public');

const iconSource = `import { createIcons, ArrowDownRight, ArrowRight, Factory, Pause, Play,
      MessageSquareText, CircleCheck, MessagesSquare, ChevronRight, ChartScatter,
      RefreshCw, UserRound, LockKeyhole, Eye, EyeOff, ShieldCheck } from 'lucide';
      const icons = { ArrowDownRight, ArrowRight, Factory, Pause, Play, MessageSquareText,
        CircleCheck, MessagesSquare, ChevronRight, ChartScatter, RefreshCw, UserRound,
        LockKeyhole, Eye, EyeOff, ShieldCheck };
      window.lucide = { createIcons: () => createIcons({ icons }) };`;
await build({
  stdin: {
    contents: iconSource,
    resolveDir: root,
  },
  nodePaths: [modules], bundle: true, minify: true, charset: 'utf8', target: 'es2020', format: 'iife',
  outfile: resolve(output, 'login-icons.min.js'), legalComments: 'inline',
});
await build({
  stdin: { contents: iconSource + '\n' + await readFile(resolve(output, 'login.js'), 'utf8'), resolveDir: root },
  nodePaths: [modules], bundle: true, minify: true, charset: 'utf8', target: 'es2020', format: 'iife',
  outfile: resolve(output, 'login.min.js'), legalComments: 'inline',
});
const grain = Buffer.alloc(64 * 64 * 4);
let seed = 1907;
for (let i = 0; i < grain.length; i += 4) {
  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
  grain[i] = grain[i + 1] = grain[i + 2] = 56;
  grain[i + 3] = (seed >>> 28) & 7;
}
const texture = await sharp(grain, { raw: { width: 64, height: 64, channels: 4 } })
  .png({ palette: true, compressionLevel: 9 }).toBuffer();
const style = (await readFile(resolve(output, 'login.css'), 'utf8'))
  .replace('__PAPER_TEXTURE__', `data:image/png;base64,${texture.toString('base64')}`);
const css = await transform(style, { loader: 'css', minify: true, target: 'es2020' });
await writeFile(resolve(output, 'login.min.css'), css.code);
await build({
  stdin: {
    contents: `import * as echarts from 'echarts/core';
      import { LineChart, ScatterChart } from 'echarts/charts';
      import { GridComponent, LegendPlainComponent, TooltipComponent } from 'echarts/components';
      import { CanvasRenderer } from 'echarts/renderers';
      echarts.use([LineChart, ScatterChart, GridComponent, LegendPlainComponent, TooltipComponent, CanvasRenderer]);
      window.echarts = { init: echarts.init, getInstanceByDom: echarts.getInstanceByDom };`,
    resolveDir: root,
  },
  nodePaths: [modules], bundle: true, minify: true, charset: 'utf8', target: 'es2020', format: 'iife',
  outfile: resolve(output, 'login-charts.min.js'), legalComments: 'inline',
});
await sharp(resolve(root, 'src/liveopt_dsh/assets/lanchou-logo.png'))
  .resize(112, 112).png({ compressionLevel: 9, palette: true, colours: 96, dither: 0 })
  .toFile(resolve(output, 'login-logo.png'));
const demo = JSON.parse(await readFile(resolve(output, 'case-demo.json'), 'utf8'));
await writeFile(resolve(output, 'case-demo.min.json'), JSON.stringify(demo));
for (const name of await readdir(output)) {
  if (!/\.(?:js|css|json)$/.test(name)) continue;
  const bytes = await readFile(resolve(output, name));
  await writeFile(resolve(output, name + '.gz'), gzipSync(bytes, { level: 9 }));
  await writeFile(resolve(output, name + '.br'), brotliCompressSync(bytes, { params: {
    [constants.BROTLI_PARAM_QUALITY]: 11,
    [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT,
  } }));
}
console.log('Built minified first-paint assets, palette logo, compact case data and Brotli/gzip variants.');
