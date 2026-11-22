import { performance } from 'node:perf_hooks';
const [client, tlsArg, itersArg, concArg, roundsArg] = process.argv.slice(2);
const tls = tlsArg === '1' || tlsArg === '2', iters = +itersArg || 100, conc = +concArg || 1, rounds = +roundsArg || 3;
const P = process.env; const base = tlsArg === '2' ? `https://localhost:${P.BENCH_RTT_PORT || 8803}` : tls ? `https://localhost:${P.BENCH_HTTPS_PORT || 8802}` : `http://127.0.0.1:${P.BENCH_HTTP_PORT || 8801}`;
const t0 = performance.now();
const { streamText, jsonSchema, tool } = await import('ai');
const { createOpenAI } = await import('@ai-sdk/openai');
const { createAnthropic } = await import('@ai-sdk/anthropic');
const importMs = performance.now() - t0;
const SYSTEM = 'You are a coding agent. '.repeat(300).slice(0, 6000);
const HISTORY = [['user','Refactor module.py to use dataclasses.'],['assistant',"I'll read the file first."],['user','Also keep the public API stable.'],['assistant','Understood, editing now.'],['user','Go ahead.']];
const tools = {};
for (let i = 0; i < 15; i++) tools[`tool_${i}`] = tool({ description: 'Does a thing in the workspace. '.repeat(4),
  inputSchema: jsonSchema({ type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' }, line: { type: 'integer' } }, required: ['path'] }) });
const t1 = performance.now();
const model = client === 'vercel-anthropic'
  ? createAnthropic({ apiKey: 'k', baseURL: base + '/v1' })('claude-sonnet-4-5')
  : createOpenAI({ apiKey: 'k', baseURL: base + '/v1' }).chat('o4-mini');
const constructMs = performance.now() - t1;
const messages = HISTORY.map(([role, content]) => ({ role, content }));
async function run() {
  const s = performance.now(); let first = null, n = 0;
  const r = streamText({ model, system: SYSTEM, messages, tools, maxRetries: 0 });
  for await (const p of r.fullStream) { if (first === null && p.type === 'text-delta') first = performance.now(); n++; }
  return [first - s, performance.now() - s, n];
}
const pct = (xs, p) => { xs = [...xs].sort((a, b) => a - b); const k = (xs.length - 1) * p / 100, f = Math.floor(k), c = Math.min(f + 1, xs.length - 1); return xs[f] + (xs[c] - xs[f]) * (k - f); };
const conns = async (path) => (await (await fetch(`http://127.0.0.1:${process.env.BENCH_HTTP_PORT || 8801}/` + path)).json()).n;
for (let i = 0; i < 5; i++) await run();
await conns('reset');
const out = { client, tls: +tls, import_ms: importMs, construct_ms: constructMs };
const c0 = process.cpuUsage(); const TOK = 2150;
if (conc <= 1) {
  const tt = [], tot = []; let nev = 0;
  for (let i = 0; i < iters; i++) { const [a, b, n] = await run(); tt.push(a); tot.push(b); nev = n; }
  const cu = process.cpuUsage(c0);
  Object.assign(out, { ttfe_p50: pct(tt, 50), ttfe_p95: pct(tt, 95), total_p50: pct(tot, 50), total_p95: pct(tot, 95), events: nev,
    events_per_s: nev / (pct(tot, 50) / 1e3), cpu_ms_per_1k_tok: (cu.user + cu.system) / 1e3 / iters / (TOK / 1000), iters });
} else {
  const tt = [], tot = []; const w0 = performance.now();
  for (let r = 0; r < rounds; r++) { const res = await Promise.all(Array.from({ length: conc }, run)); for (const [a, b] of res) { tt.push(a); tot.push(b); } }
  const wall = performance.now() - w0; const cu = process.cpuUsage(c0);
  Object.assign(out, { conc, rounds, wall_ms_per_round: wall / rounds, ttfe_p50: pct(tt, 50), ttfe_p95: pct(tt, 95), total_p50: pct(tot, 50), total_p95: pct(tot, 95),
    streams_per_s: conc * rounds / (wall / 1e3), cpu_ms_per_1k_tok: (cu.user + cu.system) / 1e3 / (conc * rounds) / (TOK / 1000) });
}
out.new_tcp_conns = (await conns('stats')) - 1;
out.requests = conc <= 1 ? iters : conc * rounds;
out.peak_rss_mb = process.resourceUsage().maxRSS / 1024;
console.log(JSON.stringify(out));
