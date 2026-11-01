# Third-party notices

LiveOpt Harness integrates with DeepSeek Harness as an MIT-licensed host. The
upstream host remains a separate dependency and retains its original copyright,
license, and About-page attribution. LiveOpt's source, brand assets, sidecar,
skills, case explorer, and deployment scripts are distributed under the ISC
license in this repository.

The release builder vendors a pinned snapshot of the LiveOpt research core so a
standalone Harness checkout can be installed reproducibly. That snapshot is
generated from the corresponding LiveOpt research repository revision and uses
the same ISC license.

The solution explorer includes Apache ECharts and Lucide. Their license files
and ECharts notice are distributed in `src/liveopt_dsh/assets/explorer/` and
included in installed Python wheels. The remote client packages Electron with
its upstream license notices. It is not the official DSH Desktop distribution.

The public login bundles a subset of ECharts 6.1.0 (Apache-2.0) and Lucide 1.48.0
(ISC). Their upstream license comments are retained in the generated bundles;
the sandbox installer also copies ECharts' LICENSE/NOTICE and Lucide's LICENSE
alongside them. The optional asset build uses esbuild (MIT) and sharp (Apache-2.0),
which are build-time tools and are not loaded by the login page or server.
