// Light macOS-style workspace (canon: global.md §L, frontend-ui-standards DEFAULT VISUAL STANDARD).
// Same tokens as the Operator Wall (src/health/wall.css). Old variable names stay as aliases so
// render_*.js inline styles keep working. No gradients, glow, decorative motion or icon fonts.
function getStyles() {
  return `
:root{color-scheme:light;
--bg:#F5F5F7;--card:#FFFFFF;--line:rgba(0,0,0,.06);--sep:rgba(60,60,67,.12);--txt:#1D1D1F;--sec:#6E6E73;--ter:#86868B;
--blue:#0071E3;--blue-hover:#0A84FF;--blue-soft:rgba(0,113,227,.1);--green:#34C759;--orange:#FF9F0A;--red:#FF3B30;
--grey:#E8E8ED;--grey-hover:#DEDEE3;--fill:#F2F2F5;--row-hover:#F7F7F9;--focus:rgba(0,113,227,.35);
--shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.05);--r-card:16px;--r-btn:10px;--r-list:12px;
--sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Inter",system-ui,sans-serif;
--card-bg:var(--card);--border:var(--line);--border-focus:var(--blue);--text:var(--txt);--text-muted:var(--sec);--text-faint:var(--ter);
--cyan:var(--blue);--emerald:#1F7A3A;--amber:#8A5300;--purple:#5E5CE6;--rose:#B4231A;--cyan-glow:var(--blue-soft);--rose-glow:rgba(255,59,48,.08);
--code-bg:#F5F5F7;--good-bg:rgba(52,199,89,.12);--warn-bg:rgba(255,159,10,.12);--bad-bg:rgba(255,59,48,.1)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
button,input,textarea,select{font:inherit;color:inherit}
button,a,input,textarea,select{outline-offset:2px}
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:3px solid var(--focus)}
button{cursor:pointer}
a{color:var(--blue);text-decoration:none}
h1,h2,h3,h4,h5,p{margin:0}
h1{font-size:30px;font-weight:700;letter-spacing:-.02em}
h2{font-size:19px;font-weight:600;letter-spacing:-.01em}
h3{font-size:16px;font-weight:600}
small{font-size:12px}
.mono,code,pre{font-family:ui-monospace,"SF Mono",SFMono-Regular,Menlo,monospace}
.muted{color:var(--sec)}
.eyebrow{display:block;color:var(--sec);font-size:13px;font-weight:600;margin-bottom:4px}

.sidebar{position:fixed;inset:0 auto 0 0;width:224px;padding:22px 12px;background:rgba(246,246,248,.92);
  backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);
  border-right:1px solid var(--sep);display:flex;flex-direction:column;z-index:20}
.workspace-brand{display:flex;gap:10px;align-items:center;padding:0 8px 20px;font-weight:600}
.workspace-brand small{display:block;font-weight:400;color:var(--ter);font-size:12px}
.brand-mark{display:grid;place-items:center;width:30px;height:30px;background:var(--blue);color:#fff;border-radius:8px;font-weight:700;font-size:15px}
.sidebar-project{padding:16px 10px 20px;border-top:1px solid var(--sep)}
.sidebar-project strong{display:block;font-size:15px;font-weight:600;text-transform:capitalize}
.sidebar-project .mono{display:block;margin-top:4px;font-size:11px;color:var(--ter);overflow-wrap:anywhere}
.nav-tabs{display:flex;flex-direction:column;gap:2px}
.tab-btn{display:flex;align-items:center;gap:10px;border:0;border-radius:8px;padding:8px 10px;min-height:34px;background:none;color:var(--txt);text-align:left;font-size:14px;font-weight:500}
.tab-btn svg{flex-shrink:0;color:var(--blue)}
.tab-btn:hover{background:rgba(0,0,0,.04)}
.tab-btn.active{background:var(--blue);color:#fff}
.tab-btn.active svg{color:#fff}
.tab-badge{margin-left:auto;color:var(--ter);font-size:12px}
.tab-btn.active .tab-badge{color:rgba(255,255,255,.85)}
.sidebar-foot{margin-top:auto;padding:16px 10px 0;border-top:1px solid var(--sep);font-size:12px;color:var(--sec)}
.sidebar-foot small{display:block;color:var(--ter);margin-top:6px;font-size:11px;line-height:1.6}
.local-dot{display:inline-block;width:8px;height:8px;background:var(--green);border-radius:50%;margin-right:6px}

.workspace{margin-left:224px}
.top-header{position:sticky;top:0;z-index:10;height:56px;border-bottom:1px solid var(--sep);padding:0 32px;display:flex;align-items:center;justify-content:space-between;
  background:rgba(245,245,247,.78);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);gap:16px}
.breadcrumb{color:var(--sec);font-size:13px;display:flex;gap:10px;align-items:center}
.breadcrumb strong{font-weight:600;color:var(--txt)}
.breadcrumb span{color:var(--ter)}
.header-actions{display:flex;gap:8px;align-items:center}
.main-content{padding:28px 32px;max-width:1440px;margin:auto}
.page-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;gap:20px}
.page-heading .eyebrow{margin-bottom:4px}
.project-path{font-size:12px;color:var(--ter);margin-top:6px;overflow-wrap:anywhere}
.snapshot-meta{font-size:12px;color:var(--ter);text-align:right;line-height:1.8;flex-shrink:0}
.snapshot-meta strong{font-weight:500;color:var(--sec)}
.page-footer{border-top:1px solid var(--sep);padding-top:16px;margin-top:32px;color:var(--ter);font-size:12px;display:flex;justify-content:space-between;gap:12px}
.tab-pane{display:none}
.tab-pane.active{display:block}

.btn,.filter-btn,.chip-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;color:var(--txt);background:var(--grey);border:0;border-radius:var(--r-btn);
  padding:0 14px;min-height:32px;font-size:13px;font-weight:500;line-height:1.3;text-decoration:none;white-space:nowrap}
.btn:hover,.filter-btn:hover,.chip-btn:hover{background:var(--grey-hover)}
.btn-primary,.btn-accent,.filter-btn.active{background:var(--blue);color:#fff}
.btn-primary:hover,.btn-accent:hover,.filter-btn.active:hover{background:var(--blue-hover)}
.btn-sm{min-height:26px;padding:0 10px;font-size:12px}
.full-width{width:100%;margin-top:14px}
.pill{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;background:var(--fill);color:var(--sec);font-size:12px;font-weight:500;
  white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}
.pill-emerald,.pill-cyan{color:var(--emerald);background:var(--good-bg)}
.pill-amber{color:var(--amber);background:var(--warn-bg)}
.pill-purple{color:var(--purple);background:rgba(94,92,230,.1)}
.progress-bar-wrap{background:var(--grey);border-radius:999px;overflow:hidden;height:6px}
.progress-bar-fill{height:100%;background:var(--blue);border-radius:999px}

.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--shadow);padding:20px;min-width:0;margin-bottom:18px}
.card-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}
.card-heading .eyebrow{margin-bottom:2px}
.card-title{font-size:15px;font-weight:600;color:var(--txt);display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}
.source-meta{font-size:12px;color:var(--ter);line-height:1.6;overflow-wrap:anywhere;margin:10px 0}
.notice{background:var(--blue-soft);color:#00438A;padding:10px 12px;border-radius:var(--r-list);font-size:13px;margin:12px 0;line-height:1.55}
.summary-strip{display:grid;grid-template-columns:1.7fr 1fr 1fr;border:1px solid var(--line);border-radius:var(--r-card);background:var(--card);box-shadow:var(--shadow);margin-bottom:24px;overflow:hidden}
.summary-strip>div{padding:16px 20px;border-right:1px solid var(--sep)}
.summary-strip>div:last-child{border:0}
.summary-strip strong{font-size:16px;font-weight:600;display:block;line-height:1.45}
.summary-strip small{color:var(--ter);font-weight:400;font-size:12px}
.overview-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(330px,1fr);gap:20px;align-items:start}
.overview-aside{min-width:0}
.document-body{font-size:14px;line-height:1.7;color:#424245;overflow-wrap:anywhere}
.document-body h2,.document-body h3,.document-body h4,.document-body h5{color:var(--txt);font-weight:600;margin:22px 0 8px}
.document-body h2{font-size:19px}
.document-body h3{font-size:16px}
.document-body h4,.document-body h5{font-size:14px}
.document-body p{margin:6px 0}
.document-bullet{padding-left:14px;margin:4px 0;position:relative}
.document-bullet:before{content:'·';position:absolute;left:2px;color:var(--ter)}
.document-space{height:5px}
.document-table-row{white-space:pre-wrap;font:12px/1.7 ui-monospace,monospace;overflow-x:auto}
.document-body code{font-size:12px;background:var(--fill);padding:1px 5px;border-radius:5px}
.document-code,.source-code{font-size:12px;line-height:1.65;color:var(--txt);background:var(--code-bg);border:1px solid var(--line);padding:14px;border-radius:var(--r-list);
  overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.milestone{display:flex;align-items:flex-start;gap:12px;width:100%;text-align:left;background:none;border:0;border-bottom:1px solid var(--sep);padding:12px 0;color:var(--txt);font-size:14px;line-height:1.45}
.milestone small{display:block;color:var(--ter);font-size:12px;margin-top:3px}
.milestone-dot{width:24px;height:24px;border:1.5px solid var(--sep);border-radius:50%;display:grid;place-items:center;flex-shrink:0;color:var(--sec);font-size:11px;font-weight:600}
.milestone-dot.done{background:var(--green);border-color:var(--green);color:#fff}
.milestone-dot.partial{border-color:var(--orange);color:var(--amber)}
.diagram-preview{height:330px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:var(--fill);border-radius:var(--r-list)}
.diagram-preview .mermaid{width:100%;height:100%;margin:0;display:grid;place-items:center}
.diagram-preview svg{max-width:100%!important;max-height:320px!important;width:auto!important;height:auto!important}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.grid-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.task-filter-bar{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.filter-pills{display:inline-flex;gap:2px;flex-wrap:wrap;padding:2px;background:var(--grey);border-radius:var(--r-btn)}
.filter-pills .filter-btn{background:none;min-height:28px;border-radius:8px}
.filter-pills .filter-btn.active{background:var(--card);color:var(--txt);box-shadow:0 1px 3px rgba(0,0,0,.12)}
.search-input,.form-input,.form-select,.form-textarea,.chat-input{background:var(--card);border:1px solid var(--sep);color:var(--txt);padding:8px 12px;border-radius:var(--r-btn);font-size:14px;min-width:0}
.search-input:focus,.form-input:focus,.form-select:focus,.form-textarea:focus,.chat-input:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px var(--focus)}
.search-input{width:240px}
.task-section{margin-bottom:20px}
.section-header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 16px;background:var(--card);border:1px solid var(--line);
  border-radius:var(--r-list) var(--r-list) 0 0;font-size:14px;font-weight:600;color:var(--txt);cursor:pointer}
.task-row{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:12px 16px;min-height:48px;border-bottom:1px solid var(--sep);font-size:14px;cursor:pointer}
.task-row:last-child{border-bottom:0}
.task-row:hover{background:var(--row-hover)}
.task-left{display:flex;align-items:flex-start;gap:10px;flex:1;min-width:0}
.task-text{overflow-wrap:anywhere;white-space:pre-wrap}
.task-text.done{color:var(--ter);text-decoration:line-through;text-decoration-color:rgba(0,0,0,.2)}
.task-badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.check-icon{width:18px;height:18px;border:1.5px solid #C7C7CC;border-radius:50%;flex-shrink:0;margin-top:1px;display:grid;place-items:center;font-size:11px}
.check-icon.done{background:var(--blue);border-color:var(--blue);color:#fff}
.section-body{background:var(--card);border:1px solid var(--line);border-top:0;border-radius:0 0 var(--r-list) var(--r-list);box-shadow:var(--shadow);overflow:hidden}

.arch-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.arch-viewport{height:560px;border:1px solid var(--line);border-radius:var(--r-list);background-color:#FBFBFD;background-image:radial-gradient(#D9D9DE 1px,transparent 1px);
  background-size:22px 22px;overflow:hidden;position:relative;cursor:grab;touch-action:none}
.arch-viewport:active{cursor:grabbing}
#arch-svg-inner,#fs-arch-svg-inner{position:absolute;left:0;top:0;transform-origin:0 0}
#arch-svg-inner pre,#fs-arch-svg-inner pre{margin:0}
.arch-viewport svg{max-width:none!important}
.arch-fullscreen-card{max-width:96vw!important;height:94vh;max-height:94vh!important}
.arch-fullscreen-card .arch-viewport{flex:1;height:auto;border:0;border-radius:0}
.diagram-error{white-space:pre-wrap;color:var(--amber)}
.stream-frame-wrap{background:var(--card);height:650px;border:1px solid var(--line);border-radius:var(--r-list);overflow:hidden}
.stream-iframe{width:100%;height:100%;border:0}

.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.22);z-index:100;display:none;align-items:center;justify-content:center;padding:24px}
.modal-backdrop.open{display:flex}
.modal-card{background:var(--card);border:1px solid var(--line);border-radius:18px;box-shadow:0 24px 64px rgba(0,0,0,.18);width:100%;max-width:780px;max-height:88vh;
  display:flex;flex-direction:column;overflow:hidden}
.modal-header,.modal-footer{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--sep);gap:12px}
.modal-footer{justify-content:flex-end;border-bottom:0;border-top:1px solid var(--sep)}
.modal-body{padding:20px;overflow:auto;min-height:0}
.form-group{margin-bottom:14px}
.form-label{display:block;font-size:13px;font-weight:500;color:var(--sec);margin-bottom:6px}
.form-input,.form-select,.form-textarea{width:100%}
.form-textarea{min-height:100px;resize:vertical}
.chat-layout{display:flex;flex-direction:column;height:650px;background:var(--card);border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--shadow);overflow:hidden}
.chat-header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--sep)}
.chat-messages{display:flex;flex-direction:column;gap:12px;flex:1;overflow:auto;padding:20px}
.msg{font-size:14px;white-space:pre-wrap;max-width:80%;padding:10px 14px;border-radius:18px;line-height:1.5}
.msg-user{align-self:flex-end;background:var(--blue);color:#fff}
.msg-bot{align-self:flex-start;background:var(--grey);color:var(--txt)}
.chat-input-bar{display:flex;gap:10px;padding:14px;border-top:1px solid var(--sep)}
.chat-input{flex:1}
.chat-quick-chips{padding:10px 14px;display:flex;gap:6px;flex-wrap:wrap;border-top:1px solid var(--sep)}

@media(min-width:1500px){.overview-grid{grid-template-columns:1.3fr 1fr}.main-content{padding-left:40px;padding-right:40px}}
@media(max-width:1100px){.sidebar{width:196px}.workspace{margin-left:196px}.main-content{padding:24px}.overview-grid{grid-template-columns:minmax(0,1fr)}
  .overview-aside{display:grid;grid-template-columns:1fr 1fr;gap:18px}.grid-3{grid-template-columns:1fr}.summary-strip strong{font-size:15px}.card{padding:18px}
  .task-filter-bar{flex-direction:column}}
@media(max-width:720px){.sidebar{position:static;width:auto;padding:12px;border-right:0;border-bottom:1px solid var(--sep)}.workspace{margin-left:0}
  .workspace-brand{padding:0 0 10px}.sidebar-project,.sidebar-foot{display:none}.nav-tabs{flex-direction:row;overflow:auto;gap:4px}
  .tab-btn{padding:8px 10px;font-size:13px;flex-shrink:0;gap:6px;min-height:40px}.tab-btn svg{width:15px}
  .top-header{height:auto;min-height:52px;padding:10px 16px;flex-wrap:wrap}.breadcrumb{font-size:12px;gap:6px}.main-content{padding:20px 16px}
  .page-heading{align-items:flex-start}.snapshot-meta{display:none}h1{font-size:26px}.summary-strip{grid-template-columns:1fr}
  .summary-strip>div{padding:12px 16px;border-right:0;border-bottom:1px solid var(--sep)}.overview-aside,.grid-2{display:block}.card-heading{flex-wrap:wrap}
  .task-row{align-items:flex-start;gap:8px}.task-badges .pill{display:none}.task-badges .btn{font-size:12px}.arch-viewport{height:430px}
  .page-footer{flex-direction:column}.modal-backdrop{padding:10px}.modal-header,.modal-body,.modal-footer{padding:14px}.search-input{width:100%}.msg{max-width:100%}
  .btn,.filter-btn,.chip-btn{min-height:40px}}

.build-stamp{white-space:nowrap;max-width:280px;overflow:hidden;text-overflow:ellipsis}
.header-actions{min-width:0;flex-wrap:wrap}
@media(max-width:720px){.header-actions{width:100%}.build-stamp{max-width:100%}}
.hub-link[hidden],#hub-open-link[hidden]{display:none}
#hub-version-status:empty{display:none}
.freshness-notice{margin:0;padding:10px 32px;background:#FFF6E5;border-bottom:1px solid rgba(255,159,10,.35);color:#7A4A00;font-size:13px}
.freshness-notice strong{color:#5C3700}

#chat-hub-panel[hidden],#chat-file-fallback[hidden]{display:none}
.chat-fallback p{margin:0 0 16px;max-width:70ch}
.msg-error{align-self:flex-start;background:var(--bad-bg);color:var(--rose)}
.msg-meta{margin-top:6px;font-size:12px;color:var(--sec);white-space:normal}
.msg-user .msg-meta{color:rgba(255,255,255,.8)}
.source-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.source-chip{font-size:12px;padding:2px 9px;border-radius:999px;background:var(--card);border:1px solid var(--sep);color:var(--sec);white-space:nowrap}
.source-chip.source-missing{opacity:.65;border-style:dashed}
.source-chip.source-error{border-color:rgba(255,59,48,.4);color:var(--rose)}

.actions-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.action-card{background:var(--card);border:1px solid var(--line);border-radius:var(--r-list);padding:14px;display:flex;flex-direction:column;gap:10px}
.action-btn{justify-content:flex-start}
.action-btn:disabled{opacity:.45;cursor:not-allowed}
.action-desc{font-size:13px;color:var(--sec)}
.runs-list{display:flex;flex-direction:column;gap:8px;margin-top:12px}
.run-row{background:var(--card);border:1px solid var(--line);border-radius:var(--r-list);padding:12px 14px;display:flex;flex-direction:column;gap:6px;align-items:flex-start}
.run-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.run-status{font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--fill);color:var(--sec)}
.run-status.status-running,.run-status.status-queued{background:var(--warn-bg);color:var(--amber)}
.run-status.status-succeeded{background:var(--good-bg);color:var(--emerald)}
.run-status.status-failed,.run-status.status-timeout,.run-status.status-interrupted{background:var(--bad-bg);color:var(--rose)}
.run-meta{font-size:12px;color:var(--sec)}
.run-error{font-size:13px;color:var(--rose);white-space:pre-wrap}
.report-body{margin-top:14px;line-height:1.65}
.report-body h2,.report-body h3,.report-body h4{margin:18px 0 8px}
.report-body p,.report-body ul,.report-body ol,.report-body pre,.report-body blockquote,.report-body table{margin:0 0 12px}
.report-body pre{background:var(--code-bg);border:1px solid var(--line);border-radius:var(--r-list);padding:12px;overflow:auto;white-space:pre-wrap}
.report-body blockquote{border-left:3px solid var(--blue);padding-left:12px;color:var(--sec)}
.report-body table{border-collapse:collapse;display:block;overflow:auto}
.report-body th,.report-body td{border:1px solid var(--sep);padding:6px 10px;text-align:left;vertical-align:top}

@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
`;
}
module.exports = { getStyles };
