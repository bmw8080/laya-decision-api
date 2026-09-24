"""本地测试 UI：单文件页面，由服务本体在 / 提供（零构建、无外链、离线可用）。"""
from __future__ import annotations

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Laya 决策服务 · 本地测试台</title>
<style>
:root{--bg:#0f1419;--panel:#171d24;--line:#263140;--fg:#e6edf3;--dim:#8b98a5;--acc:#4aa8ff;--ok:#3fb950;--warn:#d29922;--err:#f85149}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,"PingFang SC",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0;font-weight:600}
#health{font-size:12px;color:var(--dim)}
main{display:grid;grid-template-columns:minmax(360px,1fr) minmax(420px,1.2fr);gap:16px;padding:16px;align-items:start}
@media(max-width:900px){main{grid-template-columns:1fr}}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
section h2{font-size:13px;margin:0 0 10px;color:var(--dim);font-weight:600;letter-spacing:.04em}
label{display:block;font-size:12px;color:var(--dim);margin:10px 0 4px}
input,select,textarea,button{font:inherit;color:var(--fg);background:#0d1117;border:1px solid var(--line);border-radius:6px;padding:7px 9px;width:100%}
textarea{min-height:88px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;resize:vertical}
.row{display:flex;gap:8px}.row>*{flex:1}
button{cursor:pointer;background:#1f6feb;border-color:#1f6feb;width:auto;padding:8px 14px}
button.ghost{background:transparent;border-color:var(--line);color:var(--fg)}
button:disabled{opacity:.5;cursor:default}
.q{border:1px solid var(--line);border-radius:8px;padding:10px;margin-bottom:8px;background:#0d1117}
.q .qhead{display:flex;gap:8px;align-items:center;margin-bottom:2px}
.q .qhead input{flex:2}.q .qhead select{flex:1}
.tag{font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid var(--line);color:var(--dim)}
.card{border:1px solid var(--line);border-radius:8px;padding:10px;margin-bottom:8px;background:#0d1117}
.card .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.card .val{font-weight:600;color:var(--acc)}
.bar{height:6px;background:#1c2530;border-radius:4px;overflow:hidden;margin-top:4px}
.bar > i{display:block;height:100%;background:var(--acc)}
.pl{display:flex;justify-content:space-between;font-size:11.5px;color:var(--dim);margin-top:5px}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;margin-left:6px}
.pill.ok{background:rgba(63,185,80,.15);color:var(--ok);border:1px solid rgba(63,185,80,.4)}
.pill.warn{background:rgba(210,153,34,.15);color:var(--warn);border:1px solid rgba(210,153,34,.4)}
pre{background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;font-size:12px;max-height:340px}
.meta{font-size:12px;color:var(--dim);margin-top:8px;display:flex;gap:14px;flex-wrap:wrap}
.err{color:var(--err);border-color:rgba(248,81,73,.5);background:rgba(248,81,73,.08)}
.hint{font-size:11.5px;color:var(--dim);margin-top:6px}
</style>
</head>
<body>
<header>
  <h1>Laya 决策服务 · 本地测试台</h1>
  <a href="/wiki" style="color:var(--acc);text-decoration:none;font-size:13px">→ 接口文档</a>
  <span id="health">加载状态…</span>
  <button class="ghost" onclick="loadStatus()">刷新状态</button>
</header>

<main>
  <div>
    <section>
      <h2>状态（state）</h2>
      <label>内容：纯文本，或 JSON 对象（如 {"body":"...","subject":"..."}）</label>
      <textarea id="state">{"subject":"登录失败","body":"系统登录失败，全组都无法使用"}</textarea>
      <div class="row">
        <div><label>state_format</label>
          <select id="state_format"><option value="auto">auto</option><option value="json">json</option><option value="text">text</option><option value="messages">messages</option></select>
        </div>
        <div><label>model</label>
          <select id="model"><option>multilingual</option><option>english</option><option>typed-decisions</option></select>
        </div>
      </div>
      <label>预设（选了它就不用手填问题）</label>
      <select id="preset"><option value="">（不用预设）</option><option>triage</option><option>router</option><option>guard</option><option>moderation</option></select>
    </section>

    <section style="margin-top:14px">
      <h2>问题（questions）</h2>
      <div id="questions"></div>
      <div class="row" style="margin-top:8px">
        <button class="ghost" onclick="addQ('choice')">+ choice</button>
        <button class="ghost" onclick="addQ('score')">+ score</button>
        <button class="ghost" onclick="addQ('noul')">+ noul</button>
      </div>
      <div class="hint">choice/score 的选项每行一个；choice 支持「标签: 说明」；score 按从低到高写。</div>
    </section>

    <section style="margin-top:14px">
      <h2>策略（policy）</h2>
      <div class="row">
        <div><label>timeout_ms</label><input id="timeout_ms" value="5000"></div>
        <div><label>max_options</label><input id="max_options" value="20"></div>
        <div><label>阈值 τ（前端判定）</label><input id="tau" value="0.6"></div>
      </div>
      <div class="hint">τ：置信度低于它的答案会标成「建议回退 LLM」——那只是前端演示，服务端只回概率。</div>
    </section>

    <section style="margin-top:14px">
      <div class="row">
        <button id="run" onclick="run()">运行决策</button>
        <button class="ghost" onclick="loadExample('billing')">示例：退款分类</button>
        <button class="ghost" onclick="loadExample('outage')">示例：故障紧急度</button>
        <button class="ghost" onclick="loadExample('preset')">示例：内置 triage</button>
      </div>
    </section>
  </div>

  <div>
    <section>
      <h2>结果</h2>
      <div id="answers"><span class="hint">还没有结果。点「运行决策」。</span></div>
      <div class="meta" id="usage"></div>
    </section>
    <section style="margin-top:14px">
      <h2>原始响应</h2>
      <pre id="raw">—</pre>
    </section>
    <section style="margin-top:14px">
      <h2>服务状态（GET /v1/status）</h2>
      <pre id="status">—</pre>
    </section>
  </div>
</main>

<script>
const $ = s => document.querySelector(s);
let qseq = 0;

function addQ(type, qid, instructions, criteria){
  qid = qid || ("q" + (++qseq));
  const el = document.createElement('div');
  el.className = 'q';
  el.innerHTML = `
    <div class="qhead">
      <input class="qid" value="${qid}" placeholder="问题名">
      <select class="qtype" onchange="syncType(this)">
        <option value="choice"${type==='choice'?' selected':''}>choice</option>
        <option value="score"${type==='score'?' selected':''}>score</option>
        <option value="noul"${type==='noul'?' selected':''}>noul</option>
      </select>
      <button class="ghost" onclick="this.closest('.q').remove()">删除</button>
    </div>
    <label>instructions（问什么）</label>
    <input class="qins" value="${instructions || ''}" placeholder="Which team should handle this?">
    <label class="critlabel">criteria</label>
    <textarea class="qcrit">${criteria || ''}</textarea>`;
  $('#questions').appendChild(el);
  syncType(el.querySelector('.qtype'));
}
function syncType(sel){
  const q = sel.closest('.q'); const t = sel.value;
  const crit = q.querySelector('.qcrit'); const lab = q.querySelector('.critlabel');
  if(t === 'noul'){ crit.style.display='none'; lab.style.display='none'; }
  else { crit.style.display='block'; lab.style.display='block';
    if(!crit.value) crit.value = (t==='choice' ? 'billing: payments refunds\ntechnical: bugs' : 'low\nmedium\nhigh'); }
}
function buildQuestions(){
  const out = {};
  document.querySelectorAll('.q').forEach(q => {
    const qid = q.querySelector('.qid').value.trim(); if(!qid) return;
    const type = q.querySelector('.qtype').value;
    const ins = q.querySelector('.qins').value.trim();
    const raw = q.querySelector('.qcrit').value.trim();
    const def = {type, instructions: ins || 'judge'};
    if(type !== 'noul' && raw){
      const lines = raw.split('\n').map(l => l.trim()).filter(Boolean);
      if(type === 'score') def.criteria = lines;
      else { def.criteria = {}; lines.forEach(l => { const i = l.indexOf(':'); i>0 ? def.criteria[l.slice(0,i).trim()] = l.slice(i+1).trim() : def.criteria[l] = l; }); }
    }
    out[qid] = def;
  });
  return out;
}
function parseState(){
  const v = $('#state').value.trim();
  const fmt = $('#state_format').value;
  if(fmt === 'text') return v;
  try { return JSON.parse(v); } catch(e){ return v; }
}
async function run(){
  const btn = $('#run'); btn.disabled = true; $('#answers').innerHTML = '<span class="hint">推理中…</span>';
  const preset = $('#preset').value;
  const body = { state: parseState(), state_format: $('#state_format').value,
    policy: { model: $('#model').value, timeout_ms: parseInt($('#timeout_ms').value||'5000',10),
              max_options: parseInt($('#max_options').value||'20',10) } };
  if(preset) body.preset = preset; else body.questions = buildQuestions();
  const t0 = performance.now();
  try {
    const r = await fetch('/v1/decide', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
    const data = await r.json();
    const wall = Math.round(performance.now() - t0);
    $('#raw').textContent = JSON.stringify(data, null, 2);
    if(r.status >= 400){ renderError(data, r.status, wall); }
    else { renderAnswers(data, wall); }
  } catch(e){
    $('#answers').innerHTML = `<div class="card err">请求失败：${e}</div>`;
  } finally { btn.disabled = false; loadStatus(); }
}
function renderError(d, code, wall){
  const e = d.error || {};
  $('#answers').innerHTML = `<div class="card err"><div class="top"><b>HTTP ${code} · ${e.code||'ERROR'}</b></div>
    <div style="margin-top:6px">${e.message||''}</div>
    ${e.details ? `<div class="hint">${JSON.stringify(e.details)}</div>` : ''}</div>`;
  $('#usage').textContent = `往返 ${wall} ms`;
}
function renderAnswers(d, wall){
  const tau = parseFloat($('#tau').value || '0.6');
  const host = $('#answers'); host.innerHTML = '';
  Object.entries(d.answers || {}).forEach(([qid, a]) => {
    const conf = Number(a.confidence ?? 0);
    const ok = conf >= tau;
    let val = '';
    if(a.type === 'choice') val = a.choice;
    else if(a.type === 'score') val = `${a.score} 分（0…${Object.keys(a.legend||{}).length-1}）`;
    else val = `P(true) = ${a.noul}`;
    let bars = '';
    if(a.probabilities){
      bars = Object.entries(a.probabilities).map(([k,v]) => {
        const label = a.legend ? (a.legend[k] ?? k) : k;
        return `<div class="pl"><span>${label}</span><span>${(v*100).toFixed(2)}%</span></div>
                <div class="bar"><i style="width:${Math.max(1, v*100)}%"></i></div>`;
      }).join('');
    }
    host.insertAdjacentHTML('beforeend', `<div class="card">
      <div class="top"><b>${qid}</b>
        <span><span class="tag">${a.type}</span>
        <span class="pill ${ok?'ok':'warn'}">conf ${conf.toFixed(4)} ${ok?'≥ τ':'< τ · 建议回退 LLM'}</span></span></div>
      <div class="val" style="margin:6px 0">${val}</div>${bars}</div>`);
  });
  const u = d.usage || {}, e = d.engine || {};
  $('#usage').innerHTML = `<span>engine: ${e.engine_mode||'-'} / ${e.model} / ${e.backend}</span>
    <span>latency ${u.latency_ms} ms</span><span>queue ${u.queue_wait_ms} ms</span>
    <span>tokens ${u.input_tokens}</span><span>cold_start: ${u.cold_start}</span>
    <span>往返 ${wall} ms</span>
    ${(d.warnings||[]).length ? '<span style="color:var(--warn)">warnings: '+d.warnings.join(', ')+'</span>' : ''}`;
}
async function loadStatus(){
  try{
    const h = await (await fetch('/healthz')).json();
    const s = await (await fetch('/v1/status')).json();
    $('#health').textContent = `ready=${h.ready} · ${h.pkg}`;
    $('#status').textContent = JSON.stringify(s, null, 2);
  }catch(e){ $('#health').textContent = '服务不可达：' + e; }
}
function loadExample(kind){
  $('#questions').innerHTML = ''; qseq = 0;
  if(kind === 'billing'){
    $('#preset').value = ''; $('#state_format').value = 'json';
    $('#state').value = JSON.stringify({body:'账单重复扣款，请退款'});
    addQ('choice','department','Which team?','billing: payments refunds\ntechnical: bugs');
    addQ('noul','needs_human','需要人工介入吗','');
  } else if(kind === 'outage'){
    $('#preset').value = ''; $('#state_format').value = 'json';
    $('#state').value = JSON.stringify({subject:'登录失败',body:'系统登录失败，全组都无法使用'});
    addQ('score','urgency','紧急程度','low\nmedium\nhigh');
    addQ('choice','department','Which team?','technical: bugs outages access\nbilling: payments refunds');
  } else {
    $('#preset').value = 'triage'; $('#state_format').value = 'text';
    $('#state').value = '用户反馈：导出报表一直转圈，重试三次都不行';
  }
}
loadExample('outage'); loadStatus();
</script>
</body>
</html>
"""
