from __future__ import annotations


def render_v3_page(switcher_html: str) -> str:
    nav = switcher_html
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Phase 3 On-Call 助手</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5efe6;
      --panel: #fffaf2;
      --ink: #1f2933;
      --muted: #52606d;
      --line: #d9cbb6;
      --accent: #9b3d12;
      --accent-soft: #f2d3bf;
      --v3-input-h: 3.35rem;
    }}
    * {{ box-sizing: border-box; }}
    html {{
      height: 100%;
      height: 100dvh;
      max-height: 100dvh;
      overflow: hidden;
    }}
    body {{
      margin: 0;
      height: 100%;
      height: 100dvh;
      max-height: 100dvh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      font-family: "Iowan Old Style", "Songti SC", serif;
      background:
        radial-gradient(circle at top left, rgba(155, 61, 18, 0.10), transparent 24rem),
        linear-gradient(180deg, #f8f1e8 0%, #f3eadf 100%);
      color: var(--ink);
    }}
    main {{
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      max-width: 56rem;
      width: 100%;
      margin: 0 auto;
      padding: 3rem 1.25rem 1.75rem;
      overflow: hidden;
    }}
    .panel {{
      flex: 1 1 auto;
      min-height: 0;
      background: rgba(255, 250, 242, 0.92);
      border: 1px solid var(--line);
      border-radius: 1.25rem;
      box-shadow: 0 24px 60px rgba(54, 37, 19, 0.10);
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}
    .switcher {{
      display: flex;
      gap: 0.75rem;
      padding: 1.25rem 2rem 0;
      flex-shrink: 0;
    }}
    .mode-link {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.6rem 0.9rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 250, 242, 0.7);
      color: var(--muted);
      text-decoration: none;
      transition: border-color 140ms ease, background 140ms ease, color 140ms ease;
    }}
    .mode-link:hover,
    .mode-link:focus-visible {{
      border-color: #b9835a;
      color: var(--ink);
      outline: none;
    }}
    .mode-link.is-active {{
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }}
    .mode-label {{ font-weight: 700; }}
    .mode-note {{ font-size: 0.92rem; }}
    .hero {{
      flex-shrink: 0;
      padding: 2rem 2rem 1.25rem;
      border-bottom: 1px solid var(--line);
      background:
        linear-gradient(135deg, rgba(155, 61, 18, 0.08), rgba(255, 250, 242, 0));
    }}
    .hero h1 {{
      margin: 0 0 0.5rem;
      font-size: clamp(2rem, 4vw, 3rem);
      line-height: 1.05;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }}
    .upload-block {{
      flex-shrink: 0;
      padding: 1.25rem 2rem 0.65rem;
      border-bottom: 1px solid var(--line);
    }}
    .upload-block .hint {{
      margin: 0;
      padding: 0.4rem 0 0;
      font-size: 0.92rem;
      color: var(--muted);
    }}
    .upload-row {{
      display: grid;
      grid-template-columns: minmax(10rem, 1.2fr) minmax(8rem, 1fr) auto;
      gap: 0.75rem;
      align-items: center;
    }}
    .chat-log {{
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      padding: 1.25rem 2rem 1.25rem;
      overflow-x: hidden;
      overflow-y: auto;
      background: rgba(255, 255, 255, 0.55);
      border-bottom: 1px solid var(--line);
    }}
    .bubble-user {{
      align-self: flex-end;
      background: #e8dfd4;
      padding: 0.75rem 1rem;
      border-radius: 1rem;
      max-width: 92%;
      white-space: pre-wrap;
      line-height: 1.55;
      border: 1px solid var(--line);
    }}
    .bubble-asst {{
      align-self: flex-start;
      background: var(--panel);
      padding: 0.75rem 1rem;
      border-radius: 1rem;
      max-width: 96%;
      white-space: pre-wrap;
      line-height: 1.55;
      border: 1px solid var(--line);
      box-shadow: 0 8px 20px rgba(54, 37, 19, 0.06);
    }}
    .tool {{
      font-family: ui-monospace, monospace;
      font-size: 0.88rem;
      color: var(--muted);
      border-left: 3px solid var(--accent);
      padding: 0.5rem 0.75rem;
      background: rgba(250, 246, 240, 0.95);
      border-radius: 0 0.5rem 0.5rem 0;
      max-width: 100%;
      white-space: pre-wrap;
    }}
    .chat-composer {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 0.75rem;
      align-items: stretch;
      min-height: var(--v3-input-h);
    }}
    .composer-block {{
      flex-shrink: 0;
      padding: 1rem 2rem 1rem;
      border-bottom: none;
    }}
    input, button {{ font: inherit; }}
    input[type="text"] {{
      width: 100%;
      height: var(--v3-input-h);
      min-height: var(--v3-input-h);
      max-height: var(--v3-input-h);
      padding: 0 1rem;
      border-radius: 0.9rem;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      line-height: 1.35;
    }}
    #fnameOverride {{
      height: var(--v3-input-h);
      min-height: var(--v3-input-h);
      max-height: var(--v3-input-h);
    }}
    input[type="file"] {{
      width: 100%;
      padding: 0.55rem 0;
      font-size: 0.92rem;
      color: var(--muted);
    }}
    button {{
      height: var(--v3-input-h);
      min-height: var(--v3-input-h);
      max-height: var(--v3-input-h);
      padding: 0 1.2rem;
      border: 0;
      border-radius: 0.9rem;
      background: var(--accent);
      color: white;
      cursor: pointer;
      white-space: nowrap;
    }}
    button.btn-muted {{
      background: var(--muted);
    }}
    .hint {{
      flex-shrink: 0;
      margin: 0;
      padding: 0.35rem 2rem 0.5rem;
      font-size: 0.95rem;
      color: var(--muted);
    }}
    .hint:empty {{
      display: none;
    }}
    .hint.err {{ color: #b00020; }}
    @media (max-width: 640px) {{
      .upload-row {{ grid-template-columns: 1fr; }}
      .chat-composer {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <nav class="switcher" aria-label="Search mode">{nav}</nav>
      <div class="hero">
        <h1>On-Call 助手</h1>
        <p>Agent 只能调用 <code>readFile(fname)</code> 读取文件。对话中会展示每次读文件的过程；如需把文件写入 <code>data/</code>，请使用上方上传入口。</p>
      </div>
      <div class="upload-block">
        <div class="upload-row">
          <input type="file" id="fileup" />
          <input type="text" id="fnameOverride" placeholder="保存文件名（可空）" autocomplete="off" />
          <button type="button" class="btn-muted" id="uploadBtn">上传到 data</button>
        </div>
        <p id="uploadHint" class="hint err"></p>
      </div>
      <div id="log" class="chat-log" aria-live="polite"></div>
      <div class="composer-block">
        <div class="chat-composer">
          <input id="q" type="text" placeholder="例如：数据库主从延迟超过30秒怎么处理？" autocomplete="off" />
          <button type="button" id="go">发送</button>
        </div>
      </div>
      <p id="hint" class="hint err"></p>
    </section>
  </main>
<script>
const log = document.getElementById('log');
const input = document.getElementById('q');
const hint = document.getElementById('hint');
const uploadHint = document.getElementById('uploadHint');
const fnameOverride = document.getElementById('fnameOverride');
const uploadBtn = document.getElementById('uploadBtn');
const goBtn = document.getElementById('go');
const ACTIVE_VERSION = 'v3';
const STATE_KEY = 'oncall.pageState.' + ACTIVE_VERSION;
const URLS_KEY = 'oncall.pageUrls';
const RESTORE_KEY = 'oncall.restoreTarget';
let chatHistory = [];

function add(el) {{ log.appendChild(el); log.scrollTop = log.scrollHeight; }}

function readJson(key, fallback) {{
  try {{
    const raw = sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  }} catch (_error) {{
    return fallback;
  }}
}}

function writeUrls(url) {{
  const urls = readJson(URLS_KEY, {{}});
  urls[ACTIVE_VERSION] = url;
  sessionStorage.setItem(URLS_KEY, JSON.stringify(urls));
}}

function saveState() {{
  const state = {{
    url: window.location.pathname + window.location.search,
    history: chatHistory,
    logHtml: log.innerHTML,
    inputValue: input.value,
    hintText: hint.textContent,
    uploadHintText: uploadHint.textContent,
    uploadHintColor: uploadHint.style.color || '',
    fnameOverride: fnameOverride.value,
    logScrollTop: log.scrollTop
  }};
  sessionStorage.setItem(STATE_KEY, JSON.stringify(state));
  writeUrls(state.url);
}}

function restoreStateIfNeeded() {{
  const target = sessionStorage.getItem(RESTORE_KEY);
  if (target !== ACTIVE_VERSION) {{
    return;
  }}
  sessionStorage.removeItem(RESTORE_KEY);
  const state = readJson(STATE_KEY, null);
  if (!state) {{
    return;
  }}
  chatHistory = Array.isArray(state.history) ? state.history : [];
  if (typeof state.logHtml === 'string') {{
    log.innerHTML = state.logHtml;
  }}
  if (typeof state.inputValue === 'string') {{
    input.value = state.inputValue;
  }}
  if (typeof state.hintText === 'string') {{
    hint.textContent = state.hintText;
  }}
  if (typeof state.uploadHintText === 'string') {{
    uploadHint.textContent = state.uploadHintText;
  }}
  uploadHint.style.color = typeof state.uploadHintColor === 'string' ? state.uploadHintColor : '';
  if (typeof state.fnameOverride === 'string') {{
    fnameOverride.value = state.fnameOverride;
  }}
  if (typeof state.url === 'string' && state.url) {{
    history.replaceState(null, '', state.url);
  }}
  requestAnimationFrame(() => {{
    log.scrollTop = Number(state.logScrollTop) || 0;
  }});
}}

function syncSwitcherLinks() {{
  const urls = readJson(URLS_KEY, {{}});
  document.querySelectorAll('.mode-link[data-version]').forEach(link => {{
    const version = link.getAttribute('data-version');
    if (!version) return;
    const savedUrl = urls[version];
    if (savedUrl) {{
      link.href = savedUrl;
    }}
    link.addEventListener('click', () => {{
      try {{
        sessionStorage.setItem(RESTORE_KEY, version);
      }} catch (_error) {{}}
    }});
  }});
}}

syncSwitcherLinks();
restoreStateIfNeeded();
saveState();

goBtn.onclick = send;
input.addEventListener('keydown', e => {{ if (e.key === 'Enter') send(); }});
input.addEventListener('input', saveState);
fnameOverride.addEventListener('input', saveState);
window.addEventListener('pagehide', saveState);
window.addEventListener('beforeunload', saveState);

uploadBtn.onclick = async () => {{
  const fileInput = document.getElementById('fileup');
  const f = fileInput.files && fileInput.files[0];
  uploadHint.textContent = '';
  uploadHint.style.color = '';
  saveState();
  if (!f) {{ uploadHint.textContent = '请先选择文件。'; saveState(); return; }}
  const override = document.getElementById('fnameOverride').value.trim();
  const fname = override || (f.name || '').replace(/^.*[\\\\/]/, '');
  if (!fname) {{ uploadHint.textContent = '无法确定文件名。'; saveState(); return; }}
  uploadHint.textContent = '上传中…';
  saveState();
  try {{
    const buf = await f.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {{
      binary += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + chunk, bytes.length)));
    }}
    const b64 = btoa(binary);
    const res = await fetch('/v3/upload', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ fname: fname, content_base64: b64 }})
    }});
    let j = {{}};
    try {{ j = await res.json(); }} catch (_error) {{}}
    if (!res.ok) {{ uploadHint.textContent = j.error || ('HTTP ' + res.status); saveState(); return; }}
    uploadHint.textContent = (j.message || '已保存') + '（' + (j.bytes || 0) + ' 字节）';
    uploadHint.style.color = 'var(--muted)';
    saveState();
  }} catch (e) {{
    uploadHint.textContent = String(e);
    saveState();
  }}
}};

function send() {{
  const text = input.value.trim();
  if (!text) return;
  hint.textContent = '';
  input.value = '';
  chatHistory.push({{ role: 'user', content: text }});
  const u = document.createElement('div');
  u.className = 'bubble-user';
  u.textContent = text;
  add(u);
  saveState();

  fetch('/v3/chat', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ messages: chatHistory }})
  }}).then(async res => {{
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let asst = '';
    while (true) {{
      const {{ done, value }} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {{ stream: true }});
      let sep;
      while ((sep = buf.indexOf('\\n\\n')) >= 0) {{
        const block = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        let ev = '', dataLine = '';
        for (const line of block.split('\\n')) {{
          if (line.startsWith('event:')) ev = line.slice(6).trim();
          if (line.startsWith('data:')) dataLine = line.slice(5).trim();
        }}
        if (!dataLine) continue;
        let data = {{}};
        try {{ data = JSON.parse(dataLine); }} catch (_error) {{ continue; }}
        if (ev === 'tool_call') {{
          const t = document.createElement('div');
          t.className = 'tool';
          t.textContent = '调用 ' + (data.name || '') + ' ' + (data.arguments || '');
          add(t);
          saveState();
        }} else if (ev === 'tool_result') {{
          const t = document.createElement('div');
          t.className = 'tool';
          t.textContent = data.ok
            ? (data.wrote
                ? ('结果：已写入 ' + (data.fname || '') + '，' + (data.chars || 0) + ' 字符')
                : ('结果：已读 ' + (data.fname || '') + '，' + (data.chars || 0) + ' 字符'))
            : ('失败：' + (data.error || ''));
          add(t);
          saveState();
        }} else if (ev === 'assistant') {{
          asst = data.text || '';
          let bubble = log.querySelector('.bubble-asst.pending');
          if (!bubble) {{
            bubble = document.createElement('div');
            bubble.className = 'bubble-asst pending';
            add(bubble);
          }}
          bubble.textContent = asst;
          saveState();
        }} else if (ev === 'error') {{
          hint.textContent = data.message || '错误';
          saveState();
        }} else if (ev === 'done') {{
          const bubble = log.querySelector('.bubble-asst.pending');
          if (bubble) bubble.classList.remove('pending');
          if (asst) chatHistory.push({{ role: 'assistant', content: asst }});
          saveState();
        }}
      }}
    }}
  }}).catch(e => {{ hint.textContent = String(e); saveState(); }});
}}
</script>
</body>
</html>"""
