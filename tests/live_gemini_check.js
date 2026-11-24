#!/usr/bin/env node
'use strict';
// Try the REAL Gemini drafting on real videos before you deploy anything.
//
// It runs the very same drafting code as sheets/apps_script.gs (in the test harness), but sends the requests to the real
// Gemini API. Nothing is written to your sheet and nothing is posted: it only prints what would appear on the Videos tab.
//
// Usage (PowerShell). The key is typed at the prompt, lives only in this window and is never printed or saved:
//   $env:GEMINI_API_KEY = Read-Host "Gemini API key"
//   node tests/live_gemini_check.js https://youtu.be/VIDEO_ID [https://youtu.be/OTHER_ID ...]
// Optional, to also read the video's real comments as a style reference (YouTube Data API v3 key):
//   $env:YOUTUBE_API_KEY = Read-Host "YouTube Data API key"
// Optional: $env:GEMINI_MODEL = "gemini-2.5-flash"   (defaults to the model in the sheet's settings)
//
// Needs Node 18+ and curl (built into Windows 10/11). Each video is a real, billed Gemini call.

const { spawnSync } = require('child_process');
const { load } = require('./apps_script_harness');

const links = process.argv.slice(2).filter((a) => /youtu/.test(a));
if (!links.length || !process.env.GEMINI_API_KEY) {
  console.error('Usage: set $env:GEMINI_API_KEY (see the top of this file), then:\n  node tests/live_gemini_check.js https://youtu.be/VIDEO_ID [...]');
  process.exit(2);
}

// UrlFetchApp.fetch for the harness, done with curl so the script can stay synchronous like Apps Script.
function realFetch(url, opts = {}) {
  const args = ['-sS', '-m', '120', '-X', String(opts.method || 'get').toUpperCase(), '-H', 'Content-Type: ' + (opts.contentType || 'application/json')];
  for (const [k, v] of Object.entries(opts.headers || {})) args.push('-H', `${k}: ${v}`);
  if (opts.payload) args.push('--data-binary', '@-');
  args.push('-w', '\n%{http_code}', url);
  const r = spawnSync(process.platform === 'win32' ? 'curl.exe' : 'curl', args, { input: opts.payload || '', encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 });
  if (r.error || r.status !== 0) throw new Error('curl failed: ' + (r.error ? r.error.message : (r.stderr || '').split(process.env.GEMINI_API_KEY).join('***').slice(0, 200)));
  const nl = r.stdout.lastIndexOf('\n');
  const code = Number(r.stdout.slice(nl + 1)), body = r.stdout.slice(0, nl);
  return { getResponseCode: () => code, getContentText: () => body };
}

const env = load();
env.setup();
env.clearExamples();
links.forEach((_, i) => env.addPhone(true, 'P' + (i + 1), 'cloud', 'live' + (i + 1), 'Watch 1'));
env.state.props.set('GEMINI_API_KEY', process.env.GEMINI_API_KEY);
if (process.env.YOUTUBE_API_KEY) env.state.props.set('YOUTUBE_API_KEY', process.env.YOUTUBE_API_KEY);
if (process.env.GEMINI_MODEL) env.setSetting('gemini_model', process.env.GEMINI_MODEL);
env.ctx.UrlFetchApp = { fetch: realFetch };
links.forEach((link, i) => env.sheet('Videos').appendRow([true, 'P' + (i + 1), 'comment', link, '', '', '', '', '', '', '', '']));

console.log(`Drafting ${links.length} video(s) with the real Gemini API (model: ${process.env.GEMINI_MODEL || 'from the sheet settings, default gemini-2.5-flash'})` +
  (process.env.YOUTUBE_API_KEY ? ', reading real comments as style reference' : '') + '...\n');
const started = Date.now();
const res = env.call('draftVideos_', 99);
let bad = 0;
env.rows('Videos').forEach((r, i) => {
  console.log(`--- ${links[i]}   [${r.status || 'not drafted'}]`);
  if (r.comment) console.log('  comment      :', r.comment);
  if (r.alternatives) console.log('  alternatives :', r.alternatives);
  if (r.evidence) console.log('  evidence     :', r.evidence);
  if (r.summary) console.log('  summary      :', r.summary);
  if (r.note) console.log('  note         :', r.note);
  if (r.status !== 'review_ready') bad++;
});
console.log(`\n${res.drafted} drafted, ${res.skipped} skipped, ${res.errors} errors, ${res.retry_later} to retry; ${Math.round((Date.now() - started) / 1000)} s.`);
console.log('Read each "evidence" line against the video: it must point at something that is really there.');
process.exit(bad ? 1 : 0);
