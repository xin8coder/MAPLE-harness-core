# Public Login Preview

The login page replays two accepted turns from the existing public CNC scheduling
demonstration. `case-demo.json` retains its feasible candidates, Pareto schedules
and generation-level objective history without changing values. The Chinese
request summaries describe the initial task and the recorded J01 priority update.

This fixture contains no account, session identifier, provider trace, hidden
evaluator, credential or private deployment data. Rendering and selecting plans
here do not call a language model or run an optimizer.

The login uses a 112px transparent palette copy of the product logo and a Lucide bundle
containing only the displayed icons. Minified CSS, the small login script and
logo are embedded in the HTML, eliminating render-blocking asset requests.
The inline script is authorized by its exact SHA-256 CSP hash, not `unsafe-inline`.
Its ECharts bundle includes only line and
scatter plots, axes, legends, tooltips and the canvas renderer. The library versions
match the existing packaged assets. Their licenses are copied by the installer.
The login form initializes independently of the charts. Recorded data and charts
load together once the preview approaches the viewport, so a mobile login does
not wait for the below-fold preview. Chart failure never disables the form.
Playback defaults to 3x (1.4 seconds per selection) with 1x/2x/3x controls.
Manual browsing or focusing the login form pauses playback. Reduced-motion
preferences start the preview paused and disable chart/progress animation.
The paper grain is a small, deterministic embedded PNG built with sharp; headings
use available system serif fonts without downloading a webfont. Its visual tokens
follow neutral surfaces, thin borders and restrained accents inspired by shadcn/ui
and prompt-kit; the page retains its existing lightweight implementation.

Only explicitly allowed asset names can be served before login. Public assets
have a one-day browser cache and content-based ETags for revalidation. HTML,
workspace, API and download routes keep their existing authentication and cache
policy. The front gateway compresses pages/static assets, not streaming progress.
Text assets also have build-time Brotli/gzip representations, negotiated with
`Accept-Encoding`. Representations have distinct ETags and `Vary` headers.
Compressed sidecar filenames are not public routes. The compact JSON fixture
preserves all recorded values; source fixtures and editable JS/CSS stay readable.

Optional asset rebuild (Node.js is needed only during the build):

```sh
npm ci --prefix deploy/sandbox/asset-tools
node scripts/build_login_assets.mjs
```

The generated files are included in source releases; deployments need no npm
install or external CDN to display the login page.
