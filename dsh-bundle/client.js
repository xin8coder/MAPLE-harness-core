window.__ModuleLoader__.load({
  id: 'liveopt-dsh-bundle',
  factory: (require) => {
    const module = { exports: {} }
    const React = require('react')

    const css = `
      .liveopt-card{border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-base);border-radius:6px;margin:4px 0;padding:10px 12px;color:var(--dsw-alias-label-primary);font-size:13px;line-height:18px}
      .liveopt-head{display:flex;align-items:center;gap:7px;min-width:0}
      .liveopt-dot{width:8px;height:8px;border-radius:50%;background:#139b8e;flex:none}
      .liveopt-dot[data-state=failed]{background:var(--dsw-alias-state-error-primary)}
      .liveopt-dot[data-state=queued]{background:var(--dsw-alias-label-caption)}
      .liveopt-title{font-weight:600;white-space:nowrap}
      .liveopt-phase{color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .liveopt-elapsed{margin-left:auto;color:var(--dsw-alias-label-caption);font-variant-numeric:tabular-nums;white-space:nowrap}
      .liveopt-track{height:6px;background:var(--dsw-alias-border-l2);border-radius:3px;margin-top:9px;overflow:hidden}
      .liveopt-fill{height:100%;background:#139b8e;border-radius:3px;transition:width .2s ease}
      .liveopt-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:9px}
      .liveopt-metric{min-width:0}
      .liveopt-value{display:block;font-weight:600;font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .liveopt-label{display:block;color:var(--dsw-alias-label-caption);font-size:11px;line-height:15px;white-space:nowrap}
      .liveopt-message{color:var(--dsw-alias-label-secondary);margin-top:7px}
      .liveopt-section{margin-top:10px;padding-top:9px;border-top:1px solid var(--dsw-alias-border-l2)}
      .liveopt-section-title{font-weight:600;margin-bottom:6px}
      .liveopt-table-wrap{overflow:auto;max-height:240px;border:1px solid var(--dsw-alias-border-l2);border-radius:4px}
      .liveopt-table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}
      .liveopt-table th,.liveopt-table td{text-align:left;padding:5px 7px;border-bottom:1px solid var(--dsw-alias-border-l2);font-variant-numeric:tabular-nums}
      .liveopt-table th{background:var(--dsw-alias-bg-layer-1);font-weight:600;position:sticky;top:0}
      .liveopt-table tr:last-child td{border-bottom:0}
      .liveopt-downloads{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
      .liveopt-download{display:inline-flex;align-items:center;min-height:28px;padding:0 9px;border:1px solid var(--dsw-alias-border-l1);border-radius:4px;color:var(--dsw-alias-label-primary);text-decoration:none;background:var(--dsw-alias-bg-layer-1);font:inherit;cursor:pointer}
      .liveopt-download:hover:not(:disabled){border-color:#139b8e;color:#087d73}
      .liveopt-download:disabled{cursor:wait;opacity:.65}
      .liveopt-download-error{width:100%;color:var(--dsw-alias-state-error-primary);font-size:11px;line-height:16px}
      .liveopt-chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}
      .liveopt-chart-panel{min-width:0}
      .liveopt-chart-name{font-size:11px;color:var(--dsw-alias-label-secondary);margin:0 0 3px 2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .liveopt-chart{display:block;width:100%;height:164px;border:1px solid var(--dsw-alias-border-l2);border-radius:4px;background:var(--dsw-alias-bg-base)}
      .liveopt-chart-line{fill:none;stroke-width:2;vector-effect:non-scaling-stroke}
      .liveopt-chart-band{stroke:none;opacity:.12}
      .liveopt-chart-mean{fill:none;stroke-width:1.4;stroke-dasharray:5 4;opacity:.8;vector-effect:non-scaling-stroke}
      .liveopt-chart-axis{stroke:var(--dsw-alias-border-l1);stroke-width:1;vector-effect:non-scaling-stroke}
      .liveopt-chart-text{fill:var(--dsw-alias-label-caption);font-size:9px}
      .liveopt-chart-pop{fill:var(--dsw-alias-label-caption);opacity:.48}
      .liveopt-chart-pareto{fill:#139b8e;stroke:var(--dsw-alias-bg-base);stroke-width:1;opacity:.95}
      .liveopt-legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:5px;color:var(--dsw-alias-label-caption);font-size:11px}
      .liveopt-legend-item{display:inline-flex;align-items:center;gap:4px}
      .liveopt-swatch{width:9px;height:9px;border-radius:50%;background:var(--dsw-alias-label-caption);opacity:.55}
      .liveopt-swatch[data-kind=pareto]{background:#139b8e;opacity:1}
      .liveopt-upload-button{height:28px;display:inline-flex;align-items:center;gap:5px;border:0;border-radius:6px;padding:0 8px;background:transparent;color:var(--dsw-alias-label-secondary);cursor:pointer;font:inherit;white-space:nowrap}
      .liveopt-upload-button:hover:not(:disabled){background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}
      .liveopt-upload-button:disabled{cursor:default;opacity:.5}
      .liveopt-upload-button[data-state=error]{color:var(--dsw-alias-state-error-primary)}
      .liveopt-upload-glyph{font-size:17px;line-height:1;font-weight:400}
      .liveopt-brand-mark{display:block;object-fit:contain;flex:none}
      .liveopt-brand-name{display:inline-flex;align-items:center;height:24px;color:var(--dsw-alias-label-primary);font-size:18px;font-weight:650;line-height:24px;letter-spacing:0;white-space:nowrap}
      .liveopt-about-trigger{box-sizing:border-box;width:100%;height:36px;display:flex;align-items:center;justify-content:center;gap:8px;border:0;border-radius:8px;padding:0 10px;background:transparent;color:var(--dsw-alias-label-secondary);cursor:pointer;font:inherit}
      .liveopt-about-trigger:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}
      .liveopt-about-trigger[data-wide=false]{width:36px;padding:0;border-radius:50%}
      .liveopt-about-icon{width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;border:1.5px solid currentColor;border-radius:50%;font-size:12px;font-weight:700;line-height:1;flex:none}
      .liveopt-about-overlay{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(9,18,31,.42);backdrop-filter:blur(2px)}
      .liveopt-about-dialog{box-sizing:border-box;width:min(440px,100%);border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:22px;background:var(--dsw-alias-bg-base);box-shadow:0 18px 60px rgba(9,18,31,.24);color:var(--dsw-alias-label-primary)}
      .liveopt-about-head{display:flex;align-items:center;gap:12px}
      .liveopt-about-heading{font-size:21px;font-weight:650;line-height:26px}
      .liveopt-about-subtitle{margin-top:1px;color:var(--dsw-alias-label-secondary);font-size:13px}
      .liveopt-about-close{margin-left:auto;width:30px;height:30px;border:0;border-radius:50%;background:transparent;color:var(--dsw-alias-label-secondary);cursor:pointer;font-size:22px;line-height:30px}
      .liveopt-about-close:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}
      .liveopt-about-copy{margin:17px 0 0;color:var(--dsw-alias-label-secondary);font-size:13px;line-height:19px}
      .liveopt-about-meta{display:grid;grid-template-columns:auto 1fr;gap:7px 14px;margin:17px 0 0;padding-top:14px;border-top:1px solid var(--dsw-alias-border-l2);font-size:12px;line-height:18px}
      .liveopt-about-meta dt{color:var(--dsw-alias-label-caption)}
      .liveopt-about-meta dd{margin:0;color:var(--dsw-alias-label-primary)}
      .liveopt-about-link{color:#087d73;text-decoration:none}
      .liveopt-about-link:hover{text-decoration:underline}
      .liveopt-settings{box-sizing:border-box;max-width:720px;color:var(--dsw-alias-label-primary);display:flex;flex-direction:column;gap:18px}
      .liveopt-settings h2{margin:0;font-size:18px;line-height:26px;font-weight:600}
      .liveopt-settings-intro{margin:-8px 0 0;color:var(--dsw-alias-label-secondary);font-size:13px;line-height:20px}
      .liveopt-settings-group{display:flex;flex-direction:column;gap:12px;padding:16px;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;background:var(--dsw-alias-bg-base)}
      .liveopt-settings-group h3{margin:0;font-size:14px;line-height:22px;font-weight:600}
      .liveopt-settings-field{display:grid;grid-template-columns:minmax(150px,200px) minmax(0,1fr);align-items:center;gap:12px}
      .liveopt-settings-label{color:var(--dsw-alias-label-secondary);font-size:13px}
      .liveopt-settings-input{box-sizing:border-box;width:100%;height:36px;border:1px solid var(--dsw-alias-border-l2);border-radius:6px;padding:0 10px;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);font:inherit}
      .liveopt-settings-input:focus{outline:2px solid rgba(19,155,142,.22);border-color:#139b8e}
      .liveopt-settings-readonly{color:var(--dsw-alias-label-secondary);font-size:13px;overflow-wrap:anywhere}
      .liveopt-settings-status{min-height:18px;color:var(--dsw-alias-label-secondary);font-size:12px}
      .liveopt-settings-status[data-state=error]{color:var(--dsw-alias-state-error-primary)}
      .liveopt-settings-actions{display:flex;justify-content:flex-end}
      .liveopt-primary-button,.liveopt-secondary-button{box-sizing:border-box;height:34px;border:0;border-radius:6px;padding:0 14px;font:inherit;cursor:pointer}
      .liveopt-primary-button{background:#087d73;color:white}
      .liveopt-primary-button:hover:not(:disabled){background:#066b63}
      .liveopt-secondary-button{border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary)}
      .liveopt-primary-button:disabled,.liveopt-secondary-button:disabled{opacity:.5;cursor:default}
      .liveopt-solutions-view{box-sizing:border-box;height:100%;overflow:auto;padding:18px 24px 40px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary)}
      .liveopt-solutions-inner{width:min(1040px,100%);margin:0 auto}
      .liveopt-solutions-toolbar{display:flex;align-items:center;gap:10px;margin-bottom:16px}
      .liveopt-solutions-heading{font-size:18px;font-weight:600;white-space:nowrap}
      .liveopt-solutions-toolbar .liveopt-secondary-button{margin-left:auto}
      .liveopt-solutions-empty{padding:48px 16px;text-align:center;color:var(--dsw-alias-label-secondary)}
      .liveopt-session-meta{display:flex;flex-wrap:wrap;gap:8px 16px;margin:0 0 12px;color:var(--dsw-alias-label-secondary);font-size:12px}
      .liveopt-turn{border:1px solid var(--dsw-alias-border-l2);border-radius:8px;margin:0 0 12px;background:var(--dsw-alias-bg-base);overflow:hidden}
      .liveopt-turn-summary{display:flex;align-items:center;gap:10px;min-height:46px;padding:0 14px;cursor:pointer;list-style:none;background:var(--dsw-alias-bg-layer-1)}
      .liveopt-turn-summary::-webkit-details-marker{display:none}
      .liveopt-turn-summary:before{content:'›';font-size:20px;color:var(--dsw-alias-label-secondary);transform:rotate(0deg);transition:transform .12s}
      .liveopt-turn[open]>.liveopt-turn-summary:before{transform:rotate(90deg)}
      .liveopt-turn-name{font-weight:600}
      .liveopt-turn-kind{color:var(--dsw-alias-label-secondary);font-size:12px}
      .liveopt-turn-summary-metric{margin-left:auto;color:var(--dsw-alias-label-secondary);font-size:12px;white-space:nowrap}
      .liveopt-turn-body{padding:14px}
      .liveopt-requirement{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--dsw-alias-label-primary);font-family:inherit;font-size:13px;line-height:20px}
      .liveopt-conclusion{margin:0;padding:10px 12px;border-left:3px solid #139b8e;background:rgba(19,155,142,.07);color:var(--dsw-alias-label-secondary);font-size:13px;line-height:19px}
      .liveopt-details{margin-top:8px;border-top:1px solid var(--dsw-alias-border-l2);padding-top:8px}
      .liveopt-details>summary{cursor:pointer;color:var(--dsw-alias-label-secondary);font-size:12px;font-weight:600}
      .liveopt-code{max-height:340px;overflow:auto;margin:8px 0 0;padding:10px;border:1px solid var(--dsw-alias-border-l2);border-radius:4px;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);white-space:pre;tab-size:2;font:11px/17px var(--ds-font-family-code,monospace)}
      [data-liveopt-hidden=true]{display:none!important}
      @media(max-width:620px){.liveopt-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media(max-width:620px){.liveopt-settings-field{grid-template-columns:1fr;gap:5px}.liveopt-solutions-view{padding:12px}.liveopt-solutions-toolbar{align-items:stretch;flex-direction:column}.liveopt-turn-summary-metric{display:none}}
      @media(max-width:620px){[role=dialog]:has(.liveopt-settings){flex-direction:column}[role=dialog]:has(.liveopt-settings)>nav{width:100%;gap:8px;padding:14px 12px 0}[role=dialog]:has(.liveopt-settings)>nav>div:last-child{flex-direction:row}[role=dialog]:has(.liveopt-settings)>div{min-height:0}.liveopt-settings-group{padding:12px}.liveopt-settings h2{font-size:17px}}
      @media(prefers-reduced-motion:reduce){.liveopt-fill{transition:none}}
    `
    if (typeof document !== 'undefined' && !document.querySelector('style[data-plugin-css="liveopt"]')) {
      const style = document.createElement('style')
      style.dataset.plugin = 'liveopt-dsh-bundle'
      style.dataset.pluginCss = 'liveopt'
      style.textContent = css
      document.head.appendChild(style)
    }


    const ZH = {
      "Generating the TSS Workbench from the public request and data.": "正在根据需求和数据生成 TSS 工作台。",
      "Searching the generated Workbench.": "正在搜索已生成的工作台。",
      "Persisting the accepted LiveOpt state.": "正在保存已接受的优化状态。",
      "Validating the edited Workbench slots against the accepted public state.": "正在根据已接受的数据验证工作台修改。",
      "Running the validated Workbench on the accepted public state.": "正在使用当前数据运行已验证的工作台。",
      "Searching the manually repaired Workbench.": "正在搜索手动修复的工作台。",
      "Grounding the update against accepted state before selecting restart and reuse.": "正在结合当前状态解析更新，并选择重启与复用策略。",
      "Searching the updated Workbench with the selected restart state.": "正在按选定的重启策略搜索更新后的工作台。",
      "Persisting the accepted updated state.": "正在保存已接受的更新状态。",
      "Solving the generated LP/MILP model with the exact-solver backend.": "正在使用精确求解器求解 LP/MILP 模型。",
      "Running typed Pareto evolutionary search.": "正在运行类型化帕累托进化搜索。",
      "Running typed scalar evolutionary search.": "正在运行类型化单目标进化搜索。",
      "Full restart selected: no previous solutions are reused; search starts from a fresh population.": "已选择全量重启：不复用历史解，从新种群开始搜索。",
      "Warm restart selected: reusing and repairing {count} previous solutions, then filling fresh seeds.": "已选择热启动：复用并修复 {count} 个历史解，其余位置使用新解。",
      "Population transfer selected: directly reusing {count} compatible previous solutions.": "已选择种群迁移：直接复用 {count} 个兼容的历史解。",
      "Uploading {count}": "正在上传 {count} 个文件",
      "Documents {count}": "文档 {count}",
      "Final population ({count})": "最终种群（{count}）",
      "Pareto set ({count})": "帕累托解集（{count}）",
      "Turn {turn} · {count} accepted solutions": "第 {turn} 轮 · {count} 个已接受解",
      "{count} accepted solutions · {generations} iterations": "{count} 个已接受解 · {generations} 次迭代",
      "{count} accepted optimization turns": "{count} 轮已接受优化",
      "{count} population · {generations} iterations": "种群 {count} · 迭代上限 {generations}",
      "Updated {time}": "更新于 {time}",
      "Configured ({key})": "已配置（{key}）",
      "Solutions": "方案",
      "Refresh": "刷新",
      "About MAPLE Harness": "关于 MAPLE Harness",
      "Close About dialog": "关闭关于窗口",
      "MAPLE Harness Settings": "MAPLE Harness 设置",
      "Language": "语言",
      "Application": "应用",
      "Host": "宿主",
      "Attribution": "致谢",
      "Memory-Augmented Planning with Language and Evolution": "融合语言、进化与记忆的优化规划",
      "Built on the MIT-licensed DeepSeek Harness": "基于 MIT 许可的 DeepSeek Harness",
      "MAPLE Harness turns public problem descriptions and data into exact or evolutionary optimization workflows, then adapts accepted state and search archives across natural-language updates.": "MAPLE Harness 将需求和数据转化为优化任务，使用精确或进化算法求解，并根据后续需求更新方案。",
      "Queued": "排队中",
      "Starting": "正在启动",
      "Building TSS Workbench": "正在构建 TSS 工作台",
      "Preparing solver": "正在准备求解器",
      "Applying public update": "正在应用需求更新",
      "Restart and reuse selected": "已选择重启与复用策略",
      "Evolutionary search": "进化搜索中",
      "Saving accepted state": "正在保存已接受状态",
      "Validating edited Workbench": "正在验证工作台",
      "Completed": "已完成",
      "Failed": "失败",
      "Interrupted": "已中断",
      "Cancelled": "已取消",
      "MAPLE job": "MAPLE 任务",
      "MAPLE result": "MAPLE 结果",
      "MAPLE progress": "MAPLE 进度",
      "Full": "全量重启",
      "Warm": "热启动",
      "Transfer": "种群迁移",
      "Restart": "重启策略",
      "Reused solutions": "复用解数量",
      "History share": "历史解占比",
      "Fresh share": "新解占比",
      "Generation": "迭代",
      "Feasible": "可行解",
      "Archive": "解集",
      "Population": "种群",
      "Submitted": "已提交",
      "Submitting": "正在提交",
      "MAPLE data": "MAPLE 数据",
      "Prepared": "已准备",
      "Preparing public tables": "正在准备数据表",
      "Tables": "数据表",
      "Rows": "行数",
      "Columns": "列数",
      "Documents": "文档",
      "Data ID": "数据编号",
      "Table": "数据表",
      "Public ID": "公开编号",
      "Document": "文档",
      "Characters": "字符数",
      "Status": "状态",
      "Truncated to context limit": "已按上下文长度截断",
      "Complete": "完整",
      "Upload failed": "上传失败",
      "Attach public documents or data to this optimization request": "为本次优化附加文档或数据",
      "Solid: best": "实线：最优值",
      "Dashed: mean": "虚线：均值",
      "Band: population range": "色带：种群范围",
      "Plot shows objectives 1 and 2; all objectives are exported.": "图中展示目标 1 和 2，导出文件包含全部目标。",
      "Loading accepted result...": "正在加载结果…",
      "MAPLE output": "MAPLE 输出",
      "Objective evolution": "各目标迭代曲线",
      "Final population and Pareto set": "最终种群与帕累托解集",
      "Solution set": "解集",
      "Saving settings...": "正在保存设置…",
      "Settings saved. New optimization jobs use these values.": "设置已保存。",
      "MAPLE Harness uses one application mode, the DeepSeek Flash model, and a fixed light appearance.": "MAPLE Harness",
      "API": "API",
      "DeepSeek API key": "DeepSeek API 密钥",
      "Enter API key": "输入 API 密钥",
      "Provider and model": "提供商与模型",
      "API endpoint": "API 地址",
      "Optimization": "优化",
      "Iterations per run": "每次运行的迭代上限",
      "Saving...": "正在保存…",
      "Save": "保存",
      "Default: 100. Existing accepted sessions retain their own search configuration.": "默认 100 代。已有会话保留各自的搜索配置。",
      "Full restart": "全量重启",
      "Warm restart": "热启动",
      "Population transfer": "种群迁移",
      "Initial search": "初始搜索",
      "Initialization": "初始化",
      "Initial requirement": "初始需求",
      "Natural-language update": "自然语言更新",
      "Requirement text was not retained for this legacy turn.": "该历史轮次未保留需求文本。",
      "Yes": "是",
      "No": "否",
      "Final population": "最终种群",
      "Iterations": "迭代次数",
      "History reused": "历史解复用比例",
      "Result and conclusion": "结果与结论",
      "Accepted solutions": "已接受解",
      "TSS Workbench and accepted history": "TSS 工作台与历史状态",
      "Segment": "片段",
      "Encoding": "编码",
      "Length": "长度",
      "Domain size": "取值域大小",
      "This turn reused the accepted TSS structure.": "本轮复用了已接受的 TSS 结构。",
      "Public data patch": "数据更新",
      "Patch and validation summary": "补丁与验证摘要",
      "Representative solution": "代表性方案",
      "Loading optimization history...": "正在加载优化历史…",
      "This conversation has no MAPLE solution history yet.": "当前会话暂无 MAPLE 优化记录。",
      "Attach optimization documents": "添加优化文档",
      "Interface and agent replies": "界面与智能体回复",
      "Downloading...": "正在下载…",
      "Solid: best; dashed: mean; band: population range": "实线：最优值；虚线：均值；色带：种群范围"
}
    let localeService
    function t(key, values = {}) {
      const template = localeService?.getSnapshot().active === 'zh' ? ZH[key] || key : key
      return template.replace(/\{(\w+)\}/g, (match, name) => String(values[name] ?? match))
    }
    function localized(Component) {
      return function LocalizedComponent(props) {
        React.useSyncExternalStore(
          (listener) => localeService.subscribe(listener),
          () => localeService.getSnapshot(),
        )
        return React.createElement(Component, props)
      }
    }

    const LIVEOPT_APP_VERSION = '0.1.1'
    const LIVEOPT_HOST_VERSION = '0.2.1-rc.2'

    function liveOptAssetUrl(filename) {
      return `/liveopt-api/brand/${filename}`
    }

    function liveOptApiEndpoints(path) {
      const normalized = String(path || '').startsWith('/') ? String(path) : `/${path}`
      return [`/liveopt-api${normalized}`]
    }

    async function liveOptApi(path, options = {}) {
      let lastError = null
      for (const endpoint of liveOptApiEndpoints(path)) {
        try {
          const response = await fetch(endpoint, {
            cache: 'no-store',
            credentials: 'same-origin',
            ...options,
          })
          const payload = await response.json().catch(() => null)
          if (!response.ok) throw new Error(payload?.error || `MAPLE request failed (${response.status})`)
          if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
            throw new Error('MAPLE endpoint did not return a JSON object')
          }
          return payload
        } catch (error) {
          lastError = error
        }
      }
      throw lastError || new Error('MAPLE application service is unavailable')
    }

    function liveOptDownloadEndpoints(url) {
      const value = String(url || '').trim()
      if (!value) return []
      if (/^(?:https?:|blob:)/i.test(value)) return [value]
      const apiPath = value.startsWith('/liveopt-api/')
        ? value.slice('/liveopt-api'.length)
        : value
      return liveOptApiEndpoints(apiPath)
    }

    async function downloadLiveOptArtifact(item) {
      let lastError = null
      for (const endpoint of liveOptDownloadEndpoints(item?.url)) {
        try {
          const response = await fetch(endpoint, {
            cache: 'no-store',
            credentials: 'same-origin',
          })
          if (!response.ok) throw new Error(`Download failed (${response.status})`)
          const blob = await response.blob()
          const objectUrl = URL.createObjectURL(blob)
          const anchor = document.createElement('a')
          anchor.href = objectUrl
          anchor.download = String(item?.name || 'liveopt-artifact')
          anchor.style.display = 'none'
          document.body.appendChild(anchor)
          anchor.click()
          anchor.remove()
          window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
          return
        } catch (error) {
          lastError = error
        }
      }
      throw lastError || new Error('Artifact download is unavailable')
    }

    function workspaceDownloadName(path) {
      const parts = String(path || '').split(/[\\/]/).filter(Boolean)
      return parts[parts.length - 1] || 'liveopt-artifact'
    }

    async function downloadWorkspaceArtifact(path) {
      const value = String(path || '').trim()
      if (!value || value === '.') throw new Error('A file path is required')
      await downloadLiveOptArtifact({
        name: workspaceDownloadName(value),
        url: `/liveopt-api/workspace-files/${encodeURIComponent(value)}`,
      })
    }

    function installRemoteDeliverableDownloads() {
      if (typeof document === 'undefined' || typeof window === 'undefined') return undefined
      const host = String(window.location.hostname || '').toLowerCase()
      if (host === 'localhost' || host === '127.0.0.1' || host === '::1') return undefined
      const onClick = (event) => {
        const origin = event.target
        const button = origin instanceof Element
          ? origin.closest('[data-produced-files-row] button[title]')
          : null
        if (!(button instanceof HTMLButtonElement)) return
        const path = String(button.getAttribute('title') || '').trim()
        if (!path || path === '.') return
        event.preventDefault()
        event.stopPropagation()
        event.stopImmediatePropagation()
        const original = button.textContent
        button.disabled = true
        button.textContent = `Downloading ${workspaceDownloadName(path)}...`
        downloadWorkspaceArtifact(path).catch((reason) => {
          window.alert(reason instanceof Error ? reason.message : String(reason))
        }).finally(() => {
          button.disabled = false
          button.textContent = original
        })
      }
      document.addEventListener('click', onClick, true)
      return () => document.removeEventListener('click', onClick, true)
    }

    function DownloadLinks({ items }) {
      const [active, setActive] = React.useState('')
      const [error, setError] = React.useState('')
      const downloads = Array.isArray(items) ? items : []
      if (!downloads.length) return null
      async function start(item) {
        setActive(item.url || item.name)
        setError('')
        try {
          await downloadLiveOptArtifact(item)
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason))
        } finally {
          setActive('')
        }
      }
      return React.createElement('div', { className: 'liveopt-downloads' },
        downloads.map((item) => {
          const pending = active === (item.url || item.name)
          return React.createElement('button', {
            type: 'button',
            className: 'liveopt-download',
            key: item.url || item.name,
            disabled: Boolean(active),
            onClick: (event) => {
              event.preventDefault()
              event.stopPropagation()
              start(item)
            },
          }, pending ? `Downloading ${item.name}...` : item.name)
        }),
        error ? React.createElement('div', { className: 'liveopt-download-error', role: 'alert' }, error) : null,
      )
    }

    const LIVEOPT_CONVERSATION_SESSION_PREFIX = 'liveopt:conversation-session:'
    const LIVEOPT_CONVERSATION_SESSION_EVENT = 'liveopt:conversation-session'

    function conversationSessionKey(conversationSessionId) {
      return `${LIVEOPT_CONVERSATION_SESSION_PREFIX}${encodeURIComponent(String(conversationSessionId || ''))}`
    }

    function readConversationLiveOptSession(conversationSessionId) {
      if (typeof window === 'undefined' || !conversationSessionId) return ''
      try {
        const stored = window.localStorage.getItem(conversationSessionKey(conversationSessionId))
        if (!stored) return ''
        const payload = JSON.parse(stored)
        return typeof payload?.liveopt_session_id === 'string' ? payload.liveopt_session_id : ''
      } catch {
        return ''
      }
    }

    function rememberConversationLiveOptSession(conversationSessionId, liveoptSessionId) {
      if (typeof window === 'undefined' || !conversationSessionId || !liveoptSessionId) return
      const current = readConversationLiveOptSession(conversationSessionId)
      if (current === liveoptSessionId) return
      const detail = {
        conversation_session_id: String(conversationSessionId),
        liveopt_session_id: String(liveoptSessionId),
        updated_at: Date.now(),
      }
      window.localStorage.setItem(conversationSessionKey(conversationSessionId), JSON.stringify(detail))
      window.dispatchEvent(new CustomEvent(LIVEOPT_CONVERSATION_SESSION_EVENT, { detail }))
    }

    function useConversationLiveOptBinding(conversationSessionId, liveoptSessionId) {
      React.useEffect(() => {
        rememberConversationLiveOptSession(conversationSessionId, liveoptSessionId)
      }, [conversationSessionId, liveoptSessionId])
    }

    function liveOptSessionFromToolBlock(block) {
      if (!block) return ''
      const name = 'kind' in block ? block.call?.name : block.name
      if (String(name || '').startsWith('mcp__liveopt__')) {
        const payload = 'kind' in block ? jsonResult(block) : null
        const args = callArgs(block)
        const candidate = payload?.session_id || payload?.job?.session_id || args.session_id
        if (candidate) return String(candidate)
      }
      const children = Array.isArray(block.subCalls) ? block.subCalls : []
      for (let index = children.length - 1; index >= 0; index -= 1) {
        const candidate = liveOptSessionFromToolBlock(children[index])
        if (candidate) return candidate
      }
      return ''
    }

    function inferConversationLiveOptSession(nodes, runningCalls) {
      const blocks = [...(nodes || []).filter((node) => node?.kind === 'tool-result'), ...(runningCalls || [])]
      blocks.sort((left, right) => Number(left.seq || left.time || 0) - Number(right.seq || right.time || 0))
      for (let index = blocks.length - 1; index >= 0; index -= 1) {
        const candidate = liveOptSessionFromToolBlock(blocks[index])
        if (candidate) return candidate
      }
      return ''
    }

    function installDocumentBrand() {
      if (typeof document === 'undefined') return () => {}
      const enforceTitle = () => {
        const current = document.title.trim()
        const branded = current
          ? current.replaceAll('DeepSeek Harness', 'MAPLE Harness').replaceAll('LiveOpt Harness', 'MAPLE Harness')
          : 'MAPLE Harness'
        if (document.title !== branded) document.title = branded
      }
      enforceTitle()
      document.querySelectorAll('link[rel~="icon"],link[rel="shortcut icon"]').forEach((icon) => icon.remove())
      const icon = document.createElement('link')
      icon.rel = 'icon'
      icon.type = 'image/png'
      icon.sizes = '64x64'
      icon.dataset.liveoptBrand = 'icon'
      icon.href = `${liveOptAssetUrl('maple-logo.png')}?brand=maple-v1`
      document.head.appendChild(icon)
      const observer = new MutationObserver(enforceTitle)
      observer.observe(document.head, { childList: true, characterData: true, subtree: true })
      return () => observer.disconnect()
    }

    function installFixedApplicationSurface() {
      if (typeof document === 'undefined') return () => {}
      let scheduled = false
      const synchronize = () => {
        scheduled = false
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const text = node.nodeValue?.trim()
          if (text === 'Into the Unknown' || text === '探索未至之境') node.nodeValue = 'MAPLE Harness'
          if (text === 'Preview' || text === '预览版') {
            const badge = node.parentElement
            if (badge) badge.dataset.liveoptHidden = 'true'
          }
        }
        const appearanceLabels = new Set(['Light', 'Dark', 'System', '浅色', '深色', '跟随系统'])
        for (const button of document.querySelectorAll('button[aria-pressed]')) {
          if (!appearanceLabels.has(button.textContent?.trim())) continue
          const row = button.parentElement?.parentElement
          const labels = Array.from(row?.querySelectorAll('button[aria-pressed]') || []).map((item) => item.textContent?.trim())
          if (labels.length === 3 && labels.every((label) => appearanceLabels.has(label))) row.dataset.liveoptHidden = 'true'
        }
      }
      const requestSync = () => {
        if (scheduled) return
        scheduled = true
        window.requestAnimationFrame(synchronize)
      }
      const observer = new MutationObserver(requestSync)
      observer.observe(document.body, { childList: true, subtree: true })
      requestSync()
      return () => observer.disconnect()
    }

    function LiveOptBrandMark({ size = 24, className = '' }) {
      return React.createElement('img', {
        className: `liveopt-brand-mark ${className}`.trim(),
        src: liveOptAssetUrl('maple-logo.png'),
        width: size,
        height: size,
        alt: '',
        draggable: false,
      })
    }

    function LiveOptBrandName() {
      return React.createElement('span', { className: 'liveopt-brand-name' }, 'MAPLE Harness')
    }

    function LiveOptAbout({ wide }) {
      const [open, setOpen] = React.useState(false)
      React.useEffect(() => {
        if (!open) return undefined
        function onKeyDown(event) { if (event.key === 'Escape') setOpen(false) }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
      }, [open])
      return React.createElement(React.Fragment, null,
        React.createElement('button', {
          type: 'button',
          className: 'liveopt-about-trigger',
          'data-wide': String(Boolean(wide)),
          'aria-label': t('About MAPLE Harness'),
          title: t('About MAPLE Harness'),
          onClick: () => setOpen(true),
        },
        React.createElement('span', { className: 'liveopt-about-icon', 'aria-hidden': true }, 'i'),
        wide ? React.createElement('span', null, t('About MAPLE Harness')) : null),
        open ? React.createElement('div', {
          className: 'liveopt-about-overlay',
          role: 'presentation',
          onMouseDown: (event) => { if (event.target === event.currentTarget) setOpen(false) },
        }, React.createElement('section', {
          className: 'liveopt-about-dialog',
          role: 'dialog',
          'aria-modal': true,
          'aria-labelledby': 'liveopt-about-title',
        },
        React.createElement('div', { className: 'liveopt-about-head' },
          React.createElement(LiveOptBrandMark, { size: 48 }),
          React.createElement('div', null,
            React.createElement('div', { id: 'liveopt-about-title', className: 'liveopt-about-heading' }, 'MAPLE Harness'),
            React.createElement('div', { className: 'liveopt-about-subtitle' }, t('Memory-Augmented Planning with Language and Evolution'))),
          React.createElement('button', {
            type: 'button',
            className: 'liveopt-about-close',
            'aria-label': t('Close About dialog'),
            onClick: () => setOpen(false),
          }, '\u00d7')),
        React.createElement('p', { className: 'liveopt-about-copy' },
          t('MAPLE Harness turns public problem descriptions and data into exact or evolutionary optimization workflows, then adapts accepted state and search archives across natural-language updates.')),
        React.createElement('dl', { className: 'liveopt-about-meta' },
          React.createElement('dt', null, t('Application')), React.createElement('dd', null, `MAPLE Harness ${LIVEOPT_APP_VERSION}`),
          React.createElement('dt', null, t('Host')), React.createElement('dd', null, `DeepSeek Harness ${LIVEOPT_HOST_VERSION}`),
          React.createElement('dt', null, t('Attribution')), React.createElement('dd', null,
            React.createElement('a', {
              className: 'liveopt-about-link',
              href: 'https://github.com/deepseek-ai/deepseek-harness',
              target: '_blank',
              rel: 'noreferrer',
            }, t('Built on the MIT-licensed DeepSeek Harness')))),
        )) : null)
    }

    function textResult(block) {
      if (!('kind' in block)) return ''
      return (block.content || []).map((item) => item.type === 'text' ? item.text : '').filter(Boolean).join('\n')
    }

    function jsonText(text) {
      const value = String(text || '').trim()
      const start = value.indexOf('{')
      const end = value.lastIndexOf('}')
      if (start < 0 || end < start) return null
      try { return JSON.parse(value.slice(start, end + 1)) } catch { return null }
    }

    function jsonResult(block) {
      return jsonText(textResult(block))
    }

    function callArgs(block) {
      const raw = ('kind' in block ? block.call?.argsRaw : block.argsRaw) || ''
      try { return JSON.parse(raw) } catch { return {} }
    }

    function phaseLabel(phase) {
      const labels = {
        queued: t('Queued'),
        starting: t('Starting'),
        generating_workbench: t('Building TSS Workbench'),
        solving: t('Preparing solver'),
        adapting_and_solving: t('Applying public update'),
        restart_selected: t('Restart and reuse selected'),
        evolutionary_search: t('Evolutionary search'),
        persisting_state: t('Saving accepted state'),
        validating_override: t('Validating edited Workbench'),
        completed: t('Completed'),
        failed: t('Failed'),
        interrupted: t('Interrupted'),
        cancelled: t('Cancelled'),
      }
      return labels[phase] || phase || t('MAPLE job')
    }

    function formatElapsed(seconds) {
      const value = Number(seconds)
      if (!Number.isFinite(value)) return ''
      if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)}s`
      const minutes = Math.floor(value / 60)
      const rest = Math.round(value % 60)
      return `${minutes}m ${rest}s`
    }

    function Metric({ label, value }) {
      return React.createElement('div', { className: 'liveopt-metric' },
        React.createElement('span', { className: 'liveopt-value' }, value ?? '-'),
        React.createElement('span', { className: 'liveopt-label' }, label),
      )
    }

    function useLiveJob(jobId, initialJob) {
      const [job, setJob] = React.useState(initialJob || null)
      React.useEffect(() => {
        if (!jobId) return undefined
        let active = true
        let timer = null
        const terminal = new Set(['succeeded', 'failed', 'cancelled', 'interrupted'])
        const endpoints = [`/liveopt-api/jobs/${encodeURIComponent(jobId)}`]
        if (typeof window !== 'undefined' && window.location.protocol === 'http:') {
          endpoints.push(`http://${window.location.hostname}:8766/jobs/${encodeURIComponent(jobId)}`)
        }
        async function refresh() {
          let payload = null
          for (const endpoint of endpoints) {
            try {
              const response = await fetch(endpoint, { cache: 'no-store', credentials: 'same-origin' })
              if (!response.ok) continue
              const candidate = await response.json()
              if (candidate && candidate.job_id) { payload = candidate; break }
            } catch {}
          }
          if (!active) return
          if (payload) setJob(payload)
          if (!payload || !terminal.has(payload.status)) timer = window.setTimeout(refresh, 750)
        }
        refresh()
        return () => {
          active = false
          if (timer !== null) window.clearTimeout(timer)
        }
      }, [jobId])
      return job
    }

    function LiveOptProgress({ block, sessionId: conversationSessionId }) {
      const settled = 'kind' in block
      const payload = settled ? jsonResult(block) : null
      const args = callArgs(block)
      const initialJob = payload?.job || (payload?.job_id ? payload : null)
      const jobId = args.job_id || payload?.job_id || payload?.job?.job_id
      const job = useLiveJob(jobId, initialJob) || initialJob || {}
      useConversationLiveOptBinding(conversationSessionId, job.session_id || payload?.session_id || payload?.job?.session_id)
      const progress = job && typeof job.progress === 'object' ? job.progress : {}
      const status = job.status || (settled ? (block.isError ? 'failed' : 'queued') : 'queued')
      const phase = job.phase || status
      const generation = Number(progress.generation)
      const total = Number(progress.total_generations)
      const hasGeneration = Number.isFinite(generation) && Number.isFinite(total) && total > 0
      const percent = hasGeneration ? Math.max(0, Math.min(100, Number(progress.percent) || generation * 100 / total)) : 0
      const title = status === 'succeeded' ? t('MAPLE result') : t('MAPLE progress')
      let message = progress.message || (settled && !payload ? textResult(block).split('\n')[0] : '')
      if (phase === 'restart_selected' && Number.isFinite(Number(progress.reused_solution_count))) {
        const count = progress.reused_solution_count
        if (progress.restart_skill === 'warm_restart_v1') {
          message = t('Warm restart selected: reusing and repairing {count} previous solutions, then filling fresh seeds.', { count })
        } else if (progress.restart_skill === 'population_transfer_v1') {
          message = t('Population transfer selected: directly reusing {count} compatible previous solutions.', { count })
        }
      }
      const restartSelected = phase === 'restart_selected' && progress.restart_skill
      const restartName = {
        full_restart_v1: t('Full'),
        warm_restart_v1: t('Warm'),
        population_transfer_v1: t('Transfer'),
      }[progress.restart_skill] || progress.restart_skill
      return React.createElement('section', { className: 'liveopt-card', 'data-status': status },
        React.createElement('div', { className: 'liveopt-head' },
          React.createElement('span', { className: 'liveopt-dot', 'data-state': status }),
          React.createElement('span', { className: 'liveopt-title' }, title),
          React.createElement('span', { className: 'liveopt-phase' }, phaseLabel(phase)),
          React.createElement('span', { className: 'liveopt-elapsed' }, formatElapsed(job.elapsed_seconds)),
        ),
        hasGeneration ? React.createElement('div', { className: 'liveopt-track', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': total, 'aria-valuenow': generation },
          React.createElement('div', { className: 'liveopt-fill', style: { width: `${percent}%` } }),
        ) : null,
        restartSelected
          ? React.createElement('div', { className: 'liveopt-metrics' },
              React.createElement(Metric, { label: t('Restart'), value: restartName }),
              React.createElement(Metric, { label: t('Reused solutions'), value: progress.reused_solution_count }),
              React.createElement(Metric, { label: t('History share'), value: Number.isFinite(Number(progress.history_population_ratio)) ? `${Math.round(Number(progress.history_population_ratio) * 100)}%` : '-' }),
              React.createElement(Metric, { label: t('Fresh share'), value: Number.isFinite(Number(progress.fresh_population_ratio)) ? `${Math.round(Number(progress.fresh_population_ratio) * 100)}%` : '-' }),
            )
          : React.createElement('div', { className: 'liveopt-metrics' },
              React.createElement(Metric, { label: t('Generation'), value: hasGeneration ? `${generation} / ${total}` : '-' }),
              React.createElement(Metric, { label: t('Feasible'), value: progress.feasible_count }),
              React.createElement(Metric, { label: t('Archive'), value: progress.archive_size }),
              React.createElement(Metric, { label: t('Population'), value: progress.population_size }),
            ),
        message ? React.createElement('div', { className: 'liveopt-message' }, t(message)) : null,
      )
    }

    function SubmissionCard({ block, sessionId: conversationSessionId }) {
      const payload = 'kind' in block ? jsonResult(block) : null
      const args = callArgs(block)
      useConversationLiveOptBinding(conversationSessionId, payload?.session_id || args.session_id)
      return React.createElement('section', { className: 'liveopt-card' },
        React.createElement('div', { className: 'liveopt-head' },
          React.createElement('span', { className: 'liveopt-dot', 'data-state': 'queued' }),
          React.createElement('span', { className: 'liveopt-title' }, t('MAPLE job')),
          React.createElement('span', { className: 'liveopt-phase' }, payload ? t('Submitted') : t('Submitting')),
          payload?.job_id ? React.createElement('span', { className: 'liveopt-elapsed' }, payload.job_id) : null,
        ),
      )
    }

    function DataCard({ block }) {
      const payload = 'kind' in block ? jsonResult(block) : null
      const tables = payload?.tables || []
      const documents = payload?.documents || []
      return React.createElement('section', { className: 'liveopt-card' },
        React.createElement('div', { className: 'liveopt-head' },
          React.createElement('span', { className: 'liveopt-dot' }),
          React.createElement('span', { className: 'liveopt-title' }, t('MAPLE data')),
          React.createElement('span', { className: 'liveopt-phase' }, payload ? t('Prepared') : t('Preparing public tables')),
        ),
        payload ? React.createElement('div', { className: 'liveopt-metrics' },
          React.createElement(Metric, { label: t('Tables'), value: tables.length }),
          React.createElement(Metric, { label: t('Rows'), value: tables.reduce((sum, item) => sum + Number(item.rows || 0), 0) }),
          React.createElement(Metric, { label: t('Columns'), value: tables.reduce((sum, item) => sum + (item.columns || []).length, 0) }),
          React.createElement(Metric, { label: t('Documents'), value: documents.length }),
          React.createElement(Metric, { label: t('Data ID'), value: payload.prepared_data_id }),
        ) : null,
        tables.length ? React.createElement('div', { className: 'liveopt-section' },
          React.createElement('div', { className: 'liveopt-table-wrap' },
            React.createElement('table', { className: 'liveopt-table' },
              React.createElement('thead', null, React.createElement('tr', null,
                [t('Table'), t('Rows'), t('Columns'), t('Public ID')].map((name) => React.createElement('th', { key: name }, name)),
              )),
              React.createElement('tbody', null, tables.map((item) => React.createElement('tr', { key: item.name },
                React.createElement('td', null, item.name),
                React.createElement('td', null, item.rows),
                React.createElement('td', null, (item.columns || []).map((column) => column.name).join(', ')),
                React.createElement('td', null, item.id_column || '-'),
              ))),
            ),
          ),
        ) : null,
        documents.length ? React.createElement('div', { className: 'liveopt-section' },
          React.createElement('div', { className: 'liveopt-table-wrap' },
            React.createElement('table', { className: 'liveopt-table' },
              React.createElement('thead', null, React.createElement('tr', null,
                [t('Document'), t('Characters'), t('Status')].map((name) => React.createElement('th', { key: name }, name)),
              )),
              React.createElement('tbody', null, documents.map((item) => React.createElement('tr', { key: item.upload_id },
                React.createElement('td', null, item.filename),
                React.createElement('td', null, item.retained_chars),
                React.createElement('td', null, item.truncated ? t('Truncated to context limit') : t('Complete')),
              ))),
            ),
          ),
        ) : null,
      )
    }

    function DocumentUploadButton({ input, inputActions }) {
      const fileInput = React.useRef(null)
      const draftRef = React.useRef(input?.draft || '')
      const [state, setState] = React.useState({ phase: 'idle', count: 0, error: '' })
      draftRef.current = input?.draft || ''
      const locked = input?.phase !== 'plain' || state.phase === 'uploading'

      async function uploadFiles(event) {
        const files = Array.from(event.target.files || []).slice(0, 12)
        event.target.value = ''
        if (!files.length) return
        setState({ phase: 'uploading', count: files.length, error: '' })
        try {
          const uploaded = []
          for (const file of files) {
            const endpoint = `/liveopt-api/uploads?filename=${encodeURIComponent(file.name)}`
            const response = await fetch(endpoint, {
              method: 'POST',
              body: file,
              cache: 'no-store',
              credentials: 'same-origin',
              headers: { 'Content-Type': file.type || 'application/octet-stream' },
            })
            const payload = await response.json().catch(() => ({}))
            if (!response.ok || !payload.upload_id) throw new Error(payload.error || `Upload failed (${response.status})`)
            uploaded.push(payload)
          }
          const references = uploaded.map((item) => `[LiveOpt upload: ${item.filename}; id=${item.upload_id}]`).join('\n')
          const draft = draftRef.current.trimEnd()
          inputActions.setDraft(draft ? `${draft}\n${references}` : references)
          setState({ phase: 'ready', count: uploaded.length, error: '' })
        } catch (error) {
          setState({ phase: 'error', count: 0, error: error instanceof Error ? error.message : String(error) })
        }
      }

      const label = state.phase === 'uploading'
        ? t('Uploading {count}', { count: state.count })
        : state.phase === 'ready'
          ? t('Documents {count}', { count: state.count })
          : state.phase === 'error'
            ? t('Upload failed')
            : t('Document')
      return React.createElement(React.Fragment, null,
        React.createElement('input', {
          ref: fileInput,
          type: 'file',
          multiple: true,
          hidden: true,
          accept: '.csv,.tsv,.json,.jsonl,.xlsx,.txt,.md,.markdown,.pdf,.docx',
          onChange: uploadFiles,
        }),
        React.createElement('button', {
          type: 'button',
          className: 'liveopt-upload-button',
          disabled: locked,
          'data-state': state.phase,
          title: state.error || t('Attach public documents or data to this optimization request'),
          onClick: () => fileInput.current?.click(),
        },
        React.createElement('span', { className: 'liveopt-upload-glyph', 'aria-hidden': true }, '+'),
        React.createElement('span', null, label)),
      )
    }

    const chartColors = ['#139b8e', '#3b6fd8', '#d18417', '#9a55b5', '#cc5268', '#548f3b']

    function numericExtent(values) {
      const finite = values.map(Number).filter(Number.isFinite)
      if (!finite.length) return null
      const minimum = Math.min(...finite)
      const maximum = Math.max(...finite)
      const padding = Math.max(1e-9, (maximum - minimum) * .06)
      return [minimum - padding, maximum + padding]
    }

    function scale(value, extent, start, end) {
      if (!extent || !Number.isFinite(Number(value))) return start
      const span = Math.max(1e-12, extent[1] - extent[0])
      return start + (Number(value) - extent[0]) * (end - start) / span
    }

    function formatNumber(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return '-'
      const magnitude = Math.abs(number)
      if (magnitude >= 10000 || (magnitude > 0 && magnitude < .001)) return number.toExponential(2)
      return Number(number.toPrecision(4)).toString()
    }

    function ObjectiveHistoryCharts({ series }) {
      if (!Array.isArray(series) || !series.length) return null
      return React.createElement('div', { className: 'liveopt-chart-grid' },
        series.map((item, index) => React.createElement(ObjectiveChart, { key: item.name || index, item, color: chartColors[index % chartColors.length] })),
      )
    }

    function ObjectiveChart({ item, color }) {
      const points = (item.points || []).filter((point) => Number.isFinite(Number(point.minimum)))
      if (!points.length) return null
      const xExtent = numericExtent(points.map((point) => point.generation))
      const yExtent = numericExtent(points.flatMap((point) => [point.minimum, point.mean, point.maximum]))
      function polylineFor(key) {
        return points.filter((point) => Number.isFinite(Number(point[key]))).map((point) => {
          const x = scale(point.generation, xExtent, 34, 294)
          const y = scale(point[key], yExtent, 128, 12)
          return `${x.toFixed(2)},${y.toFixed(2)}`
        }).join(' ')
      }
      const rangePoints = points.filter((point) => Number.isFinite(Number(point.maximum)))
      const rangePolygon = [
        ...rangePoints.map((point) => {
          const x = scale(point.generation, xExtent, 34, 294)
          const y = scale(point.maximum, yExtent, 128, 12)
          return `${x.toFixed(2)},${y.toFixed(2)}`
        }),
        ...[...rangePoints].reverse().map((point) => {
          const x = scale(point.generation, xExtent, 34, 294)
          const y = scale(point.minimum, yExtent, 128, 12)
          return `${x.toFixed(2)},${y.toFixed(2)}`
        }),
      ].join(' ')
      const minimumLine = points.map((point) => {
        const x = scale(point.generation, xExtent, 34, 294)
        const y = scale(point.minimum, yExtent, 128, 12)
        return `${x.toFixed(2)},${y.toFixed(2)}`
      }).join(' ')
      return React.createElement('div', { className: 'liveopt-chart-panel' },
        React.createElement('div', { className: 'liveopt-chart-name', title: item.name }, item.name),
        React.createElement('svg', { className: 'liveopt-chart', viewBox: '0 0 306 148', role: 'img', 'aria-label': `${item.name} by generation` },
          React.createElement('line', { className: 'liveopt-chart-axis', x1: 34, y1: 128, x2: 294, y2: 128 }),
          React.createElement('line', { className: 'liveopt-chart-axis', x1: 34, y1: 12, x2: 34, y2: 128 }),
          rangePolygon ? React.createElement('polygon', { className: 'liveopt-chart-band', style: { fill: color }, points: rangePolygon }) : null,
          React.createElement('polyline', { className: 'liveopt-chart-mean', style: { stroke: color }, points: polylineFor('mean') }),
          React.createElement('polyline', { className: 'liveopt-chart-line', style: { stroke: color }, points: minimumLine }),
          React.createElement('text', { className: 'liveopt-chart-text', x: 34, y: 141 }, `g ${Math.min(...points.map((point) => Number(point.generation)))}`),
          React.createElement('text', { className: 'liveopt-chart-text', x: 263, y: 141 }, `g ${Math.max(...points.map((point) => Number(point.generation)))}`),
          React.createElement('text', { className: 'liveopt-chart-text', x: 2, y: 17 }, formatNumber(yExtent?.[1])),
          React.createElement('text', { className: 'liveopt-chart-text', x: 2, y: 128 }, formatNumber(yExtent?.[0])),
        ),
        React.createElement('div', { className: 'liveopt-legend' },
          React.createElement('span', null, t('Solid: best')),
          React.createElement('span', null, t('Dashed: mean')),
          React.createElement('span', null, t('Band: population range')),
        ),
      )
    }

    function PopulationChart({ population, pareto, objectiveNames }) {
      const all = Array.isArray(population) ? population.filter((point) => point.feasible !== false) : []
      const front = Array.isArray(pareto) ? pareto.filter((point) => point.feasible !== false) : []
      const width = Math.max(...all.map((point) => (point.objectives || []).length), 0)
      if (!all.length || width < 1) return null
      const plotted = [...all, ...front]
      const xValues = plotted.map((point) => Number((point.objectives || [])[0])).filter(Number.isFinite)
      const yValues = width > 1
        ? plotted.map((point) => Number((point.objectives || [])[1])).filter(Number.isFinite)
        : plotted.map((_point, index) => index)
      const xExtent = numericExtent(xValues)
      const yExtent = numericExtent(yValues)
      function circles(points, className, radius) {
        return points.map((point, index) => {
          const objectives = point.objectives || []
          const x = scale(objectives[0], xExtent, 42, 294)
          const yValue = width > 1 ? objectives[1] : index
          const y = scale(yValue, yExtent, 128, 12)
          return React.createElement('circle', { key: `${className}-${point.solution_index}-${index}`, className, cx: x, cy: y, r: radius })
        })
      }
      const xName = objectiveNames?.[0] || 'objective 1'
      const yName = width > 1 ? (objectiveNames?.[1] || 'objective 2') : 'solutions'
      return React.createElement(React.Fragment, null,
        React.createElement('svg', { className: 'liveopt-chart', viewBox: '0 0 306 148', role: 'img', 'aria-label': 'Final population and Pareto solution set' },
          React.createElement('line', { className: 'liveopt-chart-axis', x1: 42, y1: 128, x2: 294, y2: 128 }),
          React.createElement('line', { className: 'liveopt-chart-axis', x1: 42, y1: 12, x2: 42, y2: 128 }),
          circles(all, 'liveopt-chart-pop', 2.6),
          circles(front, 'liveopt-chart-pareto', 4),
          React.createElement('text', { className: 'liveopt-chart-text', x: 185, y: 142 }, xName),
          React.createElement('text', { className: 'liveopt-chart-text', x: 3, y: 10 }, yName),
        ),
        React.createElement('div', { className: 'liveopt-legend' },
          React.createElement('span', { className: 'liveopt-legend-item' }, React.createElement('span', { className: 'liveopt-swatch' }), t('Final population ({count})', { count: all.length })),
          React.createElement('span', { className: 'liveopt-legend-item' }, React.createElement('span', { className: 'liveopt-swatch', 'data-kind': 'pareto' }), t('Pareto set ({count})', { count: front.length })),
          width > 2 ? React.createElement('span', null, t('Plot shows objectives 1 and 2; all objectives are exported.')) : null,
        ),
      )
    }

    function useLiveResult(sessionId, initialPayload) {
      const complete = initialPayload && Array.isArray(initialPayload.population_preview)
      const [result, setResult] = React.useState(complete ? initialPayload : null)
      const [error, setError] = React.useState('')
      React.useEffect(() => {
        if (!sessionId) return undefined
        if (complete) { setResult(initialPayload); return undefined }
        let active = true
        let endpoint = String(initialPayload?.result_url || `/results/${encodeURIComponent(sessionId)}`)
          .replace(/^\/liveopt-api/, '')
        const retainedTurn = Number(initialPayload?.turn)
        if (!endpoint.includes('?turn=') && Number.isInteger(retainedTurn)) {
          endpoint += `?turn=${retainedTurn}`
        }
        liveOptApi(endpoint)
          .then((payload) => { if (active) setResult(payload) })
          .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : String(reason)) })
        return () => { active = false }
      }, [sessionId, initialPayload?.turn, initialPayload?.result_url, complete])
      return { result, error }
    }

    function ExplorerLink({ sessionId, turn }) {
      if (!sessionId) return null
      const base = '/liveopt-api'
      const params = new URLSearchParams({ session: sessionId, lang: localeService.getSnapshot().active })
      if (Number.isInteger(turn)) params.set('turn', String(turn))
      const url = `${base}/explorer/?${params}`
      return React.createElement('a', {
        className: 'liveopt-download', style: { marginTop: 10, gap: 7 },
        href: url, target: '_blank', rel: 'noopener noreferrer',
        onClick: (event) => {
          if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
          event.preventDefault()
          window.open(url, '_blank', 'popup=yes,width=1360,height=900,noopener,noreferrer')
        },
        title: localeService.getSnapshot().active === 'zh' ? '在独立窗口选择方案' : 'Choose a plan in a separate window',
      }, React.createElement('img', { src: `${base}/explorer/external-link.svg`, width: 15, height: 15, alt: '' }),
      localeService.getSnapshot().active === 'zh' ? '查看并选择方案' : 'Explore and select a plan')
    }

    function ResultCard({ block, sessionId: conversationSessionId }) {
      const initialPayload = 'kind' in block ? jsonResult(block) : null
      const args = callArgs(block)
      const liveoptSessionId = initialPayload?.session_id || args.session_id
      useConversationLiveOptBinding(conversationSessionId, liveoptSessionId)
      const loaded = useLiveResult(liveoptSessionId, initialPayload)
      const payload = loaded.result
      if (!payload) return React.createElement('section', { className: 'liveopt-card' }, loaded.error || t('Loading accepted result...'))
      const preview = payload.solution_preview || []
      const columns = preview.length ? Object.keys(preview[0]) : []
      return React.createElement('section', { className: 'liveopt-card' },
        React.createElement('div', { className: 'liveopt-head' },
          React.createElement('span', { className: 'liveopt-dot' }),
          React.createElement('span', { className: 'liveopt-title' }, t('MAPLE output')),
          React.createElement('span', { className: 'liveopt-phase' }, t('Turn {turn} · {count} accepted solutions', { turn: payload.turn, count: payload.solution_count })),
        ),
        React.createElement('div', { className: 'liveopt-section' },
          React.createElement('div', { className: 'liveopt-section-title' }, t('Objective evolution')),
          React.createElement(ObjectiveHistoryCharts, { series: payload.objective_series }),
        ),
        React.createElement('div', { className: 'liveopt-section' },
          React.createElement('div', { className: 'liveopt-section-title' }, t('Final population and Pareto set')),
          React.createElement(PopulationChart, { population: payload.population_preview, pareto: payload.pareto_preview, objectiveNames: payload.objective_names }),
        ),
        preview.length ? React.createElement('div', { className: 'liveopt-section' },
          React.createElement('div', { className: 'liveopt-section-title' }, t('Solution set')),
          React.createElement('div', { className: 'liveopt-table-wrap' },
            React.createElement('table', { className: 'liveopt-table' },
              React.createElement('thead', null, React.createElement('tr', null,
                columns.map((name) => React.createElement('th', { key: name }, name.replaceAll('_', ' '))),
              )),
              React.createElement('tbody', null, preview.map((row, index) => React.createElement('tr', { key: index },
                columns.map((name) => React.createElement('td', { key: name }, String(row[name] ?? '-'))),
              ))),
            ),
          ),
        ) : null,
        React.createElement(ExplorerLink, { sessionId: liveoptSessionId, turn: payload.turn }),
        React.createElement(DownloadLinks, { items: payload.downloads }),
      )
    }

    function LiveOptSettings() {
      const [settings, setSettings] = React.useState(null)
      const [apiKey, setApiKey] = React.useState('')
      const [generations, setGenerations] = React.useState(100)
      const [state, setState] = React.useState({ phase: 'loading', message: '' })

      React.useEffect(() => {
        let active = true
        liveOptApi('/settings')
          .then((payload) => {
            if (!active) return
            setSettings(payload)
            setGenerations(Number(payload.generations) || 100)
            setState({ phase: 'ready', message: '' })
          })
          .catch((error) => {
            if (active) setState({ phase: 'error', message: error instanceof Error ? error.message : String(error) })
          })
        return () => { active = false }
      }, [])

      async function save(event) {
        event.preventDefault()
        setState({ phase: 'saving', message: t('Saving settings...') })
        try {
          const body = { generations: Number(generations) }
          if (apiKey.trim()) body.api_key = apiKey.trim()
          const payload = await liveOptApi('/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          })
          setSettings(payload)
          setGenerations(Number(payload.generations) || 100)
          setApiKey('')
          setState({ phase: 'saved', message: t('Settings saved. New optimization jobs use these values.') })
        } catch (error) {
          setState({ phase: 'error', message: error instanceof Error ? error.message : String(error) })
        }
      }

      return React.createElement('form', { className: 'liveopt-settings', onSubmit: save },
        React.createElement('h2', null, t('MAPLE Harness Settings')),
        React.createElement('section', { className: 'liveopt-settings-group' },
          React.createElement('label', { className: 'liveopt-settings-field' },
            React.createElement('span', { className: 'liveopt-settings-label' }, t('Interface and agent replies')),
            React.createElement('select', {
              className: 'liveopt-settings-input',
              'aria-label': t('Language'),
              value: localeService.getSnapshot().active,
              onChange: (event) => localeService.setLocale(event.target.value),
            },
              React.createElement('option', { value: 'en' }, 'English'),
              React.createElement('option', { value: 'zh' }, '简体中文'),
            ),
          ),
        ),
        React.createElement('section', { className: 'liveopt-settings-group' },
          React.createElement('h3', null, t('API')),
          React.createElement('label', { className: 'liveopt-settings-field' },
            React.createElement('span', { className: 'liveopt-settings-label' }, t('DeepSeek API key')),
            React.createElement('input', {
              className: 'liveopt-settings-input',
              type: 'password',
              autoComplete: 'new-password',
              value: apiKey,
              placeholder: settings?.api?.configured ? t('Configured ({key})', { key: settings.api.masked || '****' }) : t('Enter API key'),
              onChange: (event) => setApiKey(event.target.value),
            }),
          ),
          React.createElement('div', { className: 'liveopt-settings-field' },
            React.createElement('span', { className: 'liveopt-settings-label' }, t('Provider and model')),
            React.createElement('span', { className: 'liveopt-settings-readonly' }, `${settings?.provider || 'DeepSeek'} · ${settings?.model || 'deepseek-flash'}`),
          ),
          React.createElement('div', { className: 'liveopt-settings-field' },
            React.createElement('span', { className: 'liveopt-settings-label' }, t('API endpoint')),
            React.createElement('span', { className: 'liveopt-settings-readonly' }, settings?.endpoint || 'https://api.deepseek.com/v1'),
          ),
        ),
        React.createElement('section', { className: 'liveopt-settings-group' },
          React.createElement('h3', null, t('Optimization')),
          React.createElement('label', { className: 'liveopt-settings-field' },
            React.createElement('span', { className: 'liveopt-settings-label' }, t('Iterations per run')),
            React.createElement('input', {
              className: 'liveopt-settings-input',
              type: 'number',
              min: 1,
              max: 1000,
              step: 1,
              value: generations,
              onChange: (event) => setGenerations(event.target.value),
            }),
          ),
          React.createElement('div', { className: 'liveopt-settings-readonly' }, t('Default: 100. Existing accepted sessions retain their own search configuration.')),
        ),
        React.createElement('div', { className: 'liveopt-settings-status', 'data-state': state.phase }, state.message),
        React.createElement('div', { className: 'liveopt-settings-actions' },
          React.createElement('button', { className: 'liveopt-primary-button', type: 'submit', disabled: state.phase === 'loading' || state.phase === 'saving' }, state.phase === 'saving' ? t('Saving...') : t('Save')),
        ),
      )
    }

    function formatTimestamp(value) {
      const date = new Date(Number(value) * 1000)
      return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
    }

    function restartDisplay(value) {
      return {
        full_restart_v1: t('Full restart'),
        warm_restart_v1: t('Warm restart'),
        population_transfer_v1: t('Population transfer'),
      }[value] || value || t('Initial search')
    }

    function JsonDetails({ title, value }) {
      if (value === null || value === undefined || (typeof value === 'object' && !Object.keys(value).length)) return null
      return React.createElement('details', { className: 'liveopt-details' },
        React.createElement('summary', null, title),
        React.createElement('pre', { className: 'liveopt-code' }, JSON.stringify(value, null, 2)),
      )
    }

    function SolutionTurn({ turn, latestTurn, sessionId }) {
      const preview = turn.solution_preview || []
      const columns = preview.length ? Object.keys(preview[0]) : []
      const segments = turn.tss?.segments || []
      const slots = turn.tss?.slots || {}
      const restart = turn.restart || {}
      return React.createElement('details', { className: 'liveopt-turn', defaultOpen: turn.turn === latestTurn },
        React.createElement('summary', { className: 'liveopt-turn-summary' },
          React.createElement('span', { className: 'liveopt-turn-name' }, turn.update_id || `t${String(turn.turn).padStart(3, '0')}`),
          React.createElement('span', { className: 'liveopt-turn-kind' }, turn.turn === 0 ? t('Initialization') : restartDisplay(restart.skill)),
          React.createElement('span', { className: 'liveopt-turn-summary-metric' }, t('{count} accepted solutions · {generations} iterations', { count: turn.result?.archive_count ?? 0, generations: turn.result?.generations_completed ?? 0 })),
        ),
        React.createElement('div', { className: 'liveopt-turn-body' },
          React.createElement('div', { className: 'liveopt-section-title' }, turn.turn === 0 ? t('Initial requirement') : t('Natural-language update')),
          React.createElement('pre', { className: 'liveopt-requirement' }, turn.requirement || t('Requirement text was not retained for this legacy turn.')),
          React.createElement('div', { className: 'liveopt-metrics' },
            React.createElement(Metric, { label: t('Feasible'), value: turn.result?.feasible === true ? t('Yes') : turn.result?.feasible === false ? t('No') : '-' }),
            React.createElement(Metric, { label: t('Solution set'), value: turn.result?.archive_count }),
            React.createElement(Metric, { label: t('Final population'), value: turn.result?.population_count }),
            React.createElement(Metric, { label: t('Iterations'), value: turn.result?.generations_completed }),
            turn.turn > 0 ? React.createElement(Metric, { label: t('Restart'), value: restartDisplay(restart.skill) }) : null,
            turn.turn > 0 ? React.createElement(Metric, { label: t('History reused'), value: Number.isFinite(Number(restart.history_population_ratio)) ? `${Math.round(Number(restart.history_population_ratio) * 100)}%` : '-' }) : null,
          ),
          React.createElement('div', { className: 'liveopt-section' },
            React.createElement('div', { className: 'liveopt-section-title' }, t('Result and conclusion')),
            React.createElement('p', { className: 'liveopt-conclusion' }, turn.conclusion),
          ),
          (turn.objective_series || []).length ? React.createElement('div', { className: 'liveopt-section' },
            React.createElement('div', { className: 'liveopt-section-title' }, t('Objective evolution')),
            React.createElement(ObjectiveHistoryCharts, { series: turn.objective_series }),
          ) : null,
          (turn.population_preview || []).length ? React.createElement('div', { className: 'liveopt-section' },
            React.createElement('div', { className: 'liveopt-section-title' }, t('Final population and Pareto set')),
            React.createElement(PopulationChart, { population: turn.population_preview, pareto: turn.pareto_preview, objectiveNames: turn.objective_names }),
          ) : null,
          preview.length ? React.createElement('div', { className: 'liveopt-section' },
            React.createElement('div', { className: 'liveopt-section-title' }, t('Accepted solutions')),
            React.createElement('div', { className: 'liveopt-table-wrap' },
              React.createElement('table', { className: 'liveopt-table' },
                React.createElement('thead', null, React.createElement('tr', null, columns.map((name) => React.createElement('th', { key: name }, name.replaceAll('_', ' '))))),
                React.createElement('tbody', null, preview.map((row, index) => React.createElement('tr', { key: index }, columns.map((name) => React.createElement('td', { key: name }, formatNumber(row[name])))))),
              ),
            ),
          ) : null,
          React.createElement('div', { className: 'liveopt-section' },
            React.createElement('div', { className: 'liveopt-section-title' }, t('TSS Workbench and accepted history')),
            segments.length ? React.createElement('div', { className: 'liveopt-table-wrap' },
              React.createElement('table', { className: 'liveopt-table' },
                React.createElement('thead', null, React.createElement('tr', null, [t('Segment'), t('Encoding'), t('Length'), t('Domain size')].map((name) => React.createElement('th', { key: name }, name)))),
                React.createElement('tbody', null, segments.map((segment, index) => React.createElement('tr', { key: `${segment.name}-${index}` },
                  React.createElement('td', null, segment.name || '-'),
                  React.createElement('td', null, segment.kind || '-'),
                  React.createElement('td', null, segment.length ?? '-'),
                  React.createElement('td', null, (segment.options || 0) + (segment.values || 0) || '-'),
                ))),
              ),
            ) : React.createElement('div', { className: 'liveopt-settings-readonly' }, t('This turn reused the accepted TSS structure.')),
            Object.entries(slots).map(([name, source]) => React.createElement('details', { className: 'liveopt-details', key: name },
              React.createElement('summary', null, name),
              React.createElement('pre', { className: 'liveopt-code' }, source),
            )),
            React.createElement(JsonDetails, { title: t('Public data patch'), value: turn.public_data_patch }),
            React.createElement(JsonDetails, { title: t('Patch and validation summary'), value: turn.tss?.patch_summary }),
            React.createElement(JsonDetails, { title: t('Representative solution'), value: turn.result?.best_solution }),
          ),
          React.createElement(ExplorerLink, { sessionId, turn: turn.turn }),
          React.createElement(DownloadLinks, { items: turn.downloads }),
        ),
      )
    }

    const EMPTY_NODES = []
    function SolutionsView({ sessionId: conversationSessionId, useConversation }) {
      const settledNodes = useConversation((snapshot) => snapshot.views.get('chat')?.legacy.nodes || EMPTY_NODES)
      const runningCalls = useConversation((snapshot) => snapshot.views.get('chat')?.legacy.runningCalls || EMPTY_NODES)
      const inferredSession = React.useMemo(
        () => inferConversationLiveOptSession(settledNodes, runningCalls),
        [settledNodes, runningCalls],
      )
      const [selected, setSelected] = React.useState(() => readConversationLiveOptSession(conversationSessionId))
      const [timeline, setTimeline] = React.useState(null)
      const [state, setState] = React.useState({ phase: selected ? 'loading' : 'ready', message: '' })

      const refreshBinding = React.useCallback(() => {
        setSelected(inferredSession || readConversationLiveOptSession(conversationSessionId))
      }, [conversationSessionId, inferredSession])

      React.useEffect(() => {
        setTimeline(null)
        const linked = inferredSession || readConversationLiveOptSession(conversationSessionId)
        if (inferredSession) rememberConversationLiveOptSession(conversationSessionId, inferredSession)
        setSelected(linked)
      }, [conversationSessionId, inferredSession])

      React.useEffect(() => {
        if (typeof window === 'undefined') return undefined
        const onBinding = (event) => {
          if (event.detail?.conversation_session_id === String(conversationSessionId)) {
            setSelected(event.detail.liveopt_session_id || '')
          }
        }
        const onStorage = (event) => {
          if (event.key === conversationSessionKey(conversationSessionId)) refreshBinding()
        }
        window.addEventListener(LIVEOPT_CONVERSATION_SESSION_EVENT, onBinding)
        window.addEventListener('storage', onStorage)
        return () => {
          window.removeEventListener(LIVEOPT_CONVERSATION_SESSION_EVENT, onBinding)
          window.removeEventListener('storage', onStorage)
        }
      }, [conversationSessionId, refreshBinding])

      React.useEffect(() => {
        if (!selected) {
          setTimeline(null)
          setState({ phase: 'ready', message: '' })
          return undefined
        }
        let active = true
        setState({ phase: 'loading', message: '' })
        liveOptApi(`/solution-sessions/${encodeURIComponent(selected)}`)
          .then((payload) => { if (active) { setTimeline(payload); setState({ phase: 'ready', message: '' }) } })
          .catch((error) => { if (active) setState({ phase: 'error', message: error instanceof Error ? error.message : String(error) }) })
        return () => { active = false }
      }, [selected])

      const session = timeline?.session
      return React.createElement('div', { className: 'liveopt-solutions-view' },
        React.createElement('div', { className: 'liveopt-solutions-inner' },
          React.createElement('div', { className: 'liveopt-solutions-toolbar' },
            React.createElement('div', { className: 'liveopt-solutions-heading' }, t('Solutions')),
            React.createElement('button', { className: 'liveopt-secondary-button', type: 'button', onClick: refreshBinding }, t('Refresh')),
          ),
          state.phase === 'error' ? React.createElement('div', { className: 'liveopt-solutions-empty' }, state.message) : null,
          state.phase === 'loading' && !timeline ? React.createElement('div', { className: 'liveopt-solutions-empty' }, t('Loading optimization history...')) : null,
          !selected && state.phase !== 'loading' ? React.createElement('div', { className: 'liveopt-solutions-empty' }, t('This conversation has no MAPLE solution history yet.')) : null,
          session ? React.createElement(React.Fragment, null,
            React.createElement('div', { className: 'liveopt-session-meta' },
              React.createElement('span', null, session.task_id || session.session_id),
              React.createElement('span', null, t('{count} accepted optimization turns', { count: (timeline.turns || []).length })),
              React.createElement('span', null, t('{count} population · {generations} iterations', { count: session.search?.population_size || '-', generations: session.search?.generations || '-' })),
              session.updated_at ? React.createElement('span', null, t('Updated {time}', { time: formatTimestamp(session.updated_at) })) : null,
            ),
            (timeline.turns || []).map((turn) => React.createElement(SolutionTurn, { key: `${session.session_id}-${turn.turn}`, turn, latestTurn: session.turn, sessionId: session.session_id })),
          ) : null,
        ),
      )
    }

    const inject = ['slots', 'theme', 'locale']
    function register(ctx, key, component) {
      ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({
        name: 'tool.call.toolview',
        key,
      }, localized(component)))
    }

    function apply(ctx) {
      localeService = ctx.get('locale')
      ctx.effect(() => localeService.register('maple', { en: {}, zh: ZH }), 'maple: translations')
      ctx.effect(installDocumentBrand, 'liveopt: document brand')
      ctx.effect(installFixedApplicationSurface, 'liveopt: fixed application surface')
      ctx.effect(installRemoteDeliverableDownloads, 'liveopt: remote deliverable downloads')
      const theme = ctx.get('theme')
      const enforceLight = (snapshot = theme.getTheme()) => {
        if (snapshot?.preference !== 'light') theme.setTheme('light')
        if (typeof document !== 'undefined') document.documentElement.style.colorScheme = 'light'
      }
      enforceLight()
      ctx.on('theme/change', enforceLight)
      ctx.slots.inject('sidebar.brand.mark', () => ctx.slots.inject('sidebar.brand.name', () => ctx.slots.inject('conversation.hero.brand.mark', function* () {
        yield ctx.slots.register({ name: 'sidebar.brand.mark' }, LiveOptBrandMark)
        yield ctx.slots.register({ name: 'sidebar.brand.name' }, LiveOptBrandName)
        yield ctx.slots.register({ name: 'conversation.hero.brand.mark' }, LiveOptBrandMark)
      })))
      for (const key of [
        'mcp__liveopt__liveopt_wait',
        'mcp__liveopt__liveopt_inspect',
      ]) register(ctx, key, LiveOptProgress)
      register(ctx, 'mcp__liveopt__liveopt_start', SubmissionCard)
      register(ctx, 'mcp__liveopt__liveopt_update', SubmissionCard)
      register(ctx, 'mcp__liveopt__liveopt_override_slots', SubmissionCard)
      register(ctx, 'mcp__liveopt__liveopt_prepare_data', DataCard)
      register(ctx, 'mcp__liveopt__liveopt_prepare_uploads', DataCard)
      register(ctx, 'mcp__liveopt__liveopt_map_data', DataCard)
      register(ctx, 'mcp__liveopt__liveopt_export', ResultCard)
      ctx.slots.inject('conversation.input.left', () => ctx.slots.register({
        name: 'conversation.input.left',
        id: 'liveopt-document-upload',
        order: 80,
        label: 'Attach optimization documents',
        locale: 'maple',
      }, localized(DocumentUploadButton)))
      ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
        name: 'sidebar.footer.action',
        id: 'liveopt-about',
        order: 90,
        label: 'About MAPLE Harness',
        locale: 'maple',
      }, localized(LiveOptAbout)))
      ctx.slots.inject('settings.section', () => ctx.slots.register({
        name: 'settings.section',
        id: 'liveopt',
        order: 0,
        label: 'MAPLE Harness',
      }, localized(LiveOptSettings)))
      ctx.slots.inject('conversation.view', () => ctx.slots.register({
        name: 'conversation.view',
        id: 'solutions',
        order: 20,
        label: 'Solutions',
        locale: 'maple',
      }, localized(SolutionsView)))
    }

    module.exports = { apply, inject }
    return module.exports
  },
})
