'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./apps_script_harness');

// Values built inside the script's VM sandbox have a different Array/Object prototype; compare them structurally.
const deepEqual = (a, b, m) => assert.deepStrictEqual(JSON.parse(JSON.stringify(a)), JSON.parse(JSON.stringify(b)), m);

// A configured sheet: two cloud phones + one local phone, an empty routine, setup() already run.
function fresh(options = {}) {
  const env = load(options);
  env.setup();
  env.clearExamples();
  env.addPhone(true, 'Phone 4', 'cloud', 'p4id');
  env.addPhone(true, 'Phone 5', 'cloud', 'p5id');
  env.addPhone(true, 'Bench', 'local', '127.0.0.1:5555');
  return env;
}
const taskRows = (env) => env.rows('Tasks');
const T0 = '2026-11-03T08:00:00Z';   // 08:00 UTC, before the default 09:00 run time

// ---------------------------------------------------------------- setup
test('setup creates every tab, seeds the library and settings, installs one trigger', () => {
  const env = load();
  env.setup();
  for (const n of ['Tasks', 'Reports', 'Runs', 'Routine', 'Phones', 'Library', 'Settings', 'Overview', '_state']) assert.ok(env.sheet(n), n);
  assert.ok(env.rows('Library').length >= 15);
  deepEqual(env.state.triggers, ['tick']);
  env.setup();                                                    // idempotent
  deepEqual(env.state.triggers, ['tick']);
  assert.equal(env.rows('Settings').length, 14);
  const names = env.rows('Library').map((r) => r.name);
  assert.equal(new Set(names).size, names.length);
});

test('setup refuses to run without the SECRET property', () => {
  const env = load({ secret: null });
  assert.throws(() => env.setup(), /SECRET/);
});

test('setup applies dropdowns, checkboxes and status colours', () => {
  const env = load();
  env.setup();
  const r = env.post({ action: 'inspect' });
  assert.equal(r.validations.routine_enabled, 'requireCheckbox');
  assert.equal(r.validations.routine_phone, 'requireValueInRange');   // chips fed from the Phones tab
  assert.equal(r.validations.routine_task, 'requireValueInRange');    // chips fed from the Library tab
  assert.equal(r.validations.routine_duration, 'requireValueInList');
  assert.equal(r.validations.phones_type, 'requireValueInList');
  assert.equal(r.validations.library_action, 'requireValueInList');
  assert.ok(env.sheet('Tasks').cfRules.length >= 8);
  assert.ok(env.sheet('Reports').cfRules.length >= 8);
  const rule = env.sheet('Routine').validations['2,2'];
  deepEqual(rule.setAllowInvalid, [true]);                     // a group name from Phones can be typed; enqueue reports any unknown name
});

test('setup upgrades an older Tasks layout without losing rows', () => {
  const env = load();
  env.state.sheets.Tasks = env.ctx.SpreadsheetApp.getActive().insertSheet('Tasks');
  const sh = env.sheet('Tasks');
  sh.appendRow(['task_id', 'device', 'action', 'params', 'status', 'attempts', 'worker', 'claimed_at', 'finished_at', 'result']);
  sh.appendRow(['first-test', 'cloud:abc', 'check-device', '', 'success', 1, 'w', '', '', 'device online']);
  env.setup();
  const rows = taskRows(env);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].task_id, 'first-test');
  assert.equal(rows[0].status, 'success');
  assert.ok('batch' in rows[0] && 'phone' in rows[0] && 'task' in rows[0] && 'value' in rows[0]);
});

test('setup postpones the first run to tomorrow when the start time already passed today', () => {
  const env = load({ now: '2026-11-03T14:00:00Z' });
  env.setup();
  env.clearExamples();
  env.addPhone(true, 'Phone 4', 'cloud', 'p4id');
  env.addRoutine(true, 'Phone 4', 'Check phone is online');
  env.call('tick');
  assert.equal(taskRows(env).length, 0);                              // no surprise run right after enabling
  env.setNow('2026-11-04T09:05:00Z');
  env.call('tick');
  assert.equal(taskRows(env).length, 1);
});

// ---------------------------------------------------------------- templates
test('fillTemplate escapes strings, validates numbers and is safe against replacement patterns', () => {
  const { ctx } = load();
  const f = (t, v, d) => ctx.fillTemplate_(t, v, d);
  deepEqual(JSON.parse(f('{"url":"{value}"}', 'https://y.com/w?v=1&t=3')), { url: 'https://y.com/w?v=1&t=3' });
  deepEqual(JSON.parse(f('{"url":"{value}"}', 'say "hi" \\ there')), { url: 'say "hi" \\ there' });
  deepEqual(JSON.parse(f('{"url":"{value}"}', 'a$&b$1')), { url: 'a$&b$1' });
  deepEqual(JSON.parse(f('{"seconds":{duration}}', '', 45)), { seconds: 45 });
  deepEqual(JSON.parse(f('{"seconds":{duration}}', '', '30')), { seconds: 30 });
  deepEqual(JSON.parse(f('{}', '', '')), {});
  assert.throws(() => f('{"url":"{value}"}', '   '), /needs a value/);
  assert.throws(() => f('{"seconds":{duration}}', '', ''), /needs a duration/);
  assert.throws(() => f('{"seconds":{duration}}', '', 'soon'), /number/);
  assert.throws(() => f('{"n":{value}}', 'abc', ''), /number/);
});

test('every seeded library task resolves to valid JSON and an allowed action', () => {
  const env = fresh();
  for (const lib of env.rows('Library')) {
    env.clearExamples();
    env.addPhone(true, 'P', 'cloud', 'x1');
    env.addRoutine(true, 'P', lib.name, 'https://example.com/?a=1&b=2', 30);
    const r = env.ctx.enqueue_({ batch: '2026-11-03', dryRun: true });
    deepEqual(r.problems, [], lib.name);
    assert.equal(r.plan.length, 1, lib.name);
    assert.ok(env.ctx.ALLOWED_ACTIONS.includes(r.plan[0].action), lib.name);
    assert.equal(typeof JSON.parse(r.plan[0].params), 'object');
  }
});


// ---------------------------------------------------------------- groups
test('a Routine row can name a group: every enabled phone in it gets the task, in order', () => {
  const env = fresh();
  env.clearExamples();
  env.addPhone(true, 'A1', 'cloud', 'id-a1', 'Warmup');
  env.addPhone(true, 'A2', 'cloud', 'id-a2', 'Warmup');
  env.addPhone(false, 'A3', 'cloud', 'id-a3', 'Warmup');          // switched off: skipped quietly
  env.addPhone(true, 'B1', 'cloud', 'id-b1', 'Other');
  env.addRoutine(true, 'Warmup', 'Open YouTube');
  env.addRoutine(true, 'Warmup', 'Press Home');
  env.addRoutine(true, 'B1', 'Take screenshot');                    // a single phone still works
  const r = env.ctx.enqueue_({ batch: '2026-11-03', dryRun: true });
  deepEqual(r.problems, []);
  deepEqual(r.plan.map((p) => p.task_id), ['2026-11-03-a1-01', '2026-11-03-a2-01', '2026-11-03-a1-02', '2026-11-03-a2-02', '2026-11-03-b1-01']);
  deepEqual(r.plan.map((p) => p.device), ['cloud:id-a1', 'cloud:id-a2', 'cloud:id-a1', 'cloud:id-a2', 'cloud:id-b1']);
});

test('a name that is neither a phone nor a group is one clear problem; a phone label beats a group of the same name', () => {
  const env = fresh();
  env.clearExamples();
  env.addPhone(true, 'Solo', 'cloud', 'id-solo', 'Solo');
  env.addPhone(true, 'M1', 'cloud', 'id-m1', 'Solo');             // a group named like a phone: the phone wins
  env.addRoutine(true, 'Nobody', 'Open YouTube');
  env.addRoutine(true, 'Solo', 'Open YouTube');
  const r = env.ctx.enqueue_({ batch: '2026-11-03', dryRun: true });
  assert.equal(r.problems.length, 1);
  assert.match(r.problems[0], /Nobody.*not a phone or a group/);
  deepEqual(r.plan.map((p) => p.device), ['cloud:id-solo']);
});

test('the new spend-cap settings exist with the agreed defaults', () => {
  const env = fresh();
  const d = Object.fromEntries(env.ctx.DEFAULT_SETTINGS.map((x) => [x[0], x[1]]));
  assert.equal(d.max_phone_minutes, '8');
  assert.equal(d.daily_phone_minutes, '120');
});

// ---------------------------------------------------------------- enqueue
test('enqueue dry-run: ordering, device mapping, quiet skips and clear problems', () => {
  const env = fresh();
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  env.addRoutine(true, 'Phone 5', 'Open TikTok');
  env.addRoutine(true, 'Phone 4', 'Watch YouTube video', 'https://youtu.be/abc?x=1&y=2', 60);
  env.addRoutine(false, 'Phone 4', 'Press Home');                       // switched off
  env.addRoutine(true, 'Ghost', 'Press Home');                          // unknown phone
  env.addRoutine(true, 'Phone 4', 'No such task');                      // unknown task
  env.addRoutine(true, 'Phone 5', 'Open link in YouTube');              // missing value
  env.addRoutine(true, 'Bench', 'Take screenshot');                     // local phone
  env.sheet('Routine').appendRow(['', '', '', '', '', '']);             // empty row
  const r = env.ctx.enqueue_({ batch: '2026-11-03', dryRun: true });
  deepEqual(r.plan.map((p) => p.task_id), ['2026-11-03-phone-4-01', '2026-11-03-phone-5-01', '2026-11-03-phone-4-02', '2026-11-03-bench-01']);
  deepEqual(r.plan.map((p) => p.device), ['cloud:p4id', 'cloud:p5id', 'cloud:p4id', '127.0.0.1:5555']);
  assert.equal(r.problems.length, 3);
  assert.match(r.problems.join('|'), /Ghost/);
  assert.match(r.problems.join('|'), /No such task/);
  assert.match(r.problems.join('|'), /needs a value/);
  assert.equal(taskRows(env).length, 0);                                // dry run writes nothing
  const flow = JSON.parse(r.plan[2].params);
  assert.equal(flow.steps[1].url, 'https://youtu.be/abc?x=1&y=2');
  assert.equal(flow.steps[3].seconds, 60);
});

test('a disabled phone skips its tasks quietly; a phone without an id is a problem', () => {
  const env = fresh();
  env.addPhone(false, 'Off', 'cloud', 'offid');
  env.addPhone(true, 'NoId', 'cloud', '');
  env.addRoutine(true, 'Off', 'Press Home');
  env.addRoutine(true, 'NoId', 'Press Home');
  const r = env.ctx.enqueue_({ batch: '2026-11-03', dryRun: true });
  assert.equal(r.plan.length, 0);
  assert.equal(r.problems.length, 1);
  assert.match(r.problems[0], /NoId.*profile id/);
});

test('enqueue writes pending rows, is idempotent, and records problems as error rows', () => {
  const env = fresh();
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  env.addRoutine(true, 'Ghost', 'Press Home');
  const a = env.ctx.enqueue_({ batch: '2026-11-03', scheduled: true });
  assert.equal(a.enqueued, 1);
  const rows = taskRows(env);
  assert.equal(rows.length, 1);
  deepEqual([rows[0].status, rows[0].batch, rows[0].phone, rows[0].task, rows[0].device], ['pending', '2026-11-03', 'Phone 4', 'Open YouTube', 'cloud:p4id']);
  deepEqual(JSON.parse(rows[0].params), { name: 'youtube' });
  assert.ok(env.rows('Reports').some((r) => r.status === 'error' && /Ghost/.test(r.message)));
  assert.equal(env.ctx.enqueue_({ batch: '2026-11-03', scheduled: true }).enqueued, 0);
  assert.equal(taskRows(env).length, 1);
  assert.equal(env.state.props.get('LAST_BATCH'), '2026-11-03');
});

test('yesterday\'s unfinished tasks expire; hand-added and same-day rows are untouched', () => {
  const env = fresh();
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  const tasks = env.sheet('Tasks');
  tasks.appendRow(['old-1', 'cloud:p4id', 'key', '{"name":"home"}', 'pending', '', '', '', '', '', '2026-11-02', 'Phone 4', 'Press Home', '']);
  tasks.appendRow(['old-2', 'cloud:p4id', 'key', '{"name":"home"}', 'running', '', '', '', '', '', '2026-11-02', 'Phone 4', 'Press Home', '']);
  tasks.appendRow(['old-3', 'cloud:p4id', 'key', '{"name":"home"}', 'success', '', '', '', '', '', '2026-11-02', 'Phone 4', 'Press Home', '']);
  tasks.appendRow(['hand-1', 'cloud:p4id', 'key', '{"name":"home"}', 'pending', '', '', '', '', '', '', '', '', '']);
  env.ctx.enqueue_({ batch: '2026-11-03', scheduled: true });
  const by = Object.fromEntries(taskRows(env).map((r) => [r.task_id, r.status]));
  deepEqual([by['old-1'], by['old-2'], by['old-3'], by['hand-1']], ['expired', 'expired', 'success', 'pending']);
  env.ctx.enqueue_({ batch: '2026-11-03-manual-1000' });
  assert.equal(taskRows(env).filter((r) => r.batch === '2026-11-03' && r.status === 'pending').length, 1);   // manual run didn't expire the scheduled batch
});

test('a batch id stored as a Date (Sheets auto-converts "2026-11-03") still matches everywhere', () => {
  const env = fresh({ now: '2026-11-04T09:10:00Z' });
  env.setSetting('report_email', 'x@example.com');
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  const asDate = env.makeDate('2026-11-03T00:00:00Z');
  const tasks = env.sheet('Tasks');
  tasks.appendRow(['d-1', 'cloud:p4id', 'key', '{"name":"home"}', 'success', 1, '', '', '2026-11-03T05:00:00.000Z', 'ok', asDate, 'Phone 4', 'Press Home', '']);
  tasks.appendRow(['d-2', 'cloud:p4id', 'key', '{"name":"home"}', 'pending', '', '', '', '', '', asDate, 'Phone 4', 'Press Home', '']);
  assert.equal(env.ctx.batchStats_('2026-11-03').total, 2);                 // matched by value, not by Date string
  env.ctx.enqueue_({ batch: '2026-11-04', scheduled: true });
  const by = Object.fromEntries(taskRows(env).map((r) => [r.task_id, r.status]));
  assert.deepEqual(by['d-2'], 'expired');                                   // yesterday's unfinished task expired
  assert.deepEqual(by['d-1'], 'success');
  env.post({ action: 'claim', worker: 'cloud:p4id', exact: true });
  env.post({ action: 'claim', worker: 'cloud:p4id', exact: true });
  env.post({ action: 'report', task_id: '2026-11-04-phone-4-01', status: 'success', attempts: 1 });
  assert.equal(env.state.mail.length, 1);                                   // the day's report is still sent
});

test('trim removes old finished rows only and keeps the header', () => {
  const env = fresh();
  env.setSetting('keep_days', 7);
  const tasks = env.sheet('Tasks');
  const old = '2026-10-01T00:00:00.000Z', recent = '2026-11-02T00:00:00.000Z';
  tasks.appendRow(['a', '', 'key', '{}', 'success', 1, '', '', old, '', '2026-10-01', '', '', '']);
  tasks.appendRow(['b', '', 'key', '{}', 'success', 1, '', '', recent, '', '2026-11-02', '', '', '']);
  tasks.appendRow(['c', '', 'key', '{}', 'pending', '', '', '', '', '', '2026-11-03', '', '', '']);
  env.sheet('Reports').appendRow(['2025-01-01T00:00:00.000Z', 'r', 't', 'd', 'a', 'success']);
  env.sheet('Reports').appendRow(['2026-11-02T00:00:00.000Z', 'r', 't', 'd', 'a', 'success']);
  env.ctx.trim_();
  deepEqual(taskRows(env).map((r) => r.task_id), ['b', 'c']);
  assert.equal(env.sheet('Tasks').get(1, 1), 'task_id');
  assert.equal(env.rows('Reports').length, 1);
});

// ---------------------------------------------------------------- claim / devices / report
function queue(env) {
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  env.addRoutine(true, 'Phone 5', 'Open TikTok');
  env.addRoutine(true, 'Phone 4', 'Press Home');
  env.addRoutine(true, 'Phone 4', 'Take screenshot');
  env.ctx.enqueue_({ batch: '2026-11-03', scheduled: true });
}

test('claim hands a phone its own tasks one at a time, in routine order', () => {
  const env = fresh();
  queue(env);
  const claim = (w, exact = true) => env.post({ action: 'claim', worker: w, exact }).tasks;
  const first = claim('cloud:p4id');
  assert.equal(first.length, 1);
  assert.equal(first[0].task_id, '2026-11-03-phone-4-01');
  assert.equal(taskRows(env)[0].status, 'running');
  assert.equal(taskRows(env)[0].worker, 'cloud:p4id');
  assert.equal(claim('cloud:p4id')[0].task_id, '2026-11-03-phone-4-02');   // next one only after asking again
  assert.equal(claim('cloud:p5id')[0].task_id, '2026-11-03-phone-5-01');
  assert.equal(claim('cloud:p5id').length, 0);
  assert.equal(claim('cloud:p4id')[0].task_id, '2026-11-03-phone-4-03');
  assert.equal(claim('cloud:p4id').length, 0);
});

test('claim: exact skips blank-device rows, others may take them; stale running rows come back', () => {
  const env = fresh();
  env.sheet('Tasks').appendRow(['any-1', '', 'key', '{"name":"home"}', '', '', '', '', '', '', '', '', '', '']);
  assert.equal(env.post({ action: 'claim', worker: 'cloud:p4id', exact: true }).tasks.length, 0);
  assert.equal(env.post({ action: 'claim', worker: 'emulator-5554', exact: false }).tasks[0].task_id, 'any-1');
  assert.equal(env.post({ action: 'claim', worker: 'emulator-5554' }).tasks.length, 0);          // already running
  env.setNow('2026-11-03T08:20:00Z');                                                            // 20 min later: stale
  assert.equal(env.post({ action: 'claim', worker: 'emulator-5554' }).tasks[0].task_id, 'any-1');
});

test('claim ignores finished, expired and other devices\' rows', () => {
  const env = fresh();
  const t = env.sheet('Tasks');
  for (const st of ['success', 'failed', 'skipped', 'expired']) t.appendRow([`x-${st}`, 'cloud:p4id', 'key', '{}', st, '', '', '', '', '', '', '', '', '']);
  t.appendRow(['other', 'cloud:p5id', 'key', '{}', 'pending', '', '', '', '', '', '', '', '', '']);
  t.appendRow(['noaction', 'cloud:p4id', '', '{}', 'pending', '', '', '', '', '', '', '', '', '']);
  assert.equal(env.post({ action: 'claim', worker: 'cloud:p4id', exact: true }).tasks.length, 0);
});

test('devices lists phones with waiting tasks and counts blank-device ones', () => {
  const env = fresh();
  queue(env);
  env.sheet('Tasks').appendRow(['any-1', '', 'key', '{}', 'pending', '', '', '', '', '', '', '', '', '']);
  const d = env.post({ action: 'devices' });
  deepEqual(d.devices.sort(), ['cloud:p4id', 'cloud:p5id']);
  assert.equal(d.blank, 1);
  for (const w of ['cloud:p4id', 'cloud:p4id', 'cloud:p4id', 'cloud:p5id']) env.post({ action: 'claim', worker: w, exact: true });
  const after = env.post({ action: 'devices' });
  deepEqual(after.devices, []);                                                           // running rows are not "waiting"
});

test('report marks the task, logs a Reports row with phone and task names', () => {
  const env = fresh();
  queue(env);
  env.post({ action: 'claim', worker: 'cloud:p4id', exact: true });
  env.post({ action: 'report', run_id: 'r1', task_id: '2026-11-03-phone-4-01', device: 'cloud:p4id', task_action: 'open-app', status: 'success', attempts: 1, duration_s: 4.2, message: 'ok', output: '{}' });
  const t = taskRows(env)[0];
  deepEqual([t.status, t.attempts, t.result], ['success', 1, 'ok']);
  assert.ok(t.finished_at);
  const rep = env.rows('Reports').find((r) => r.task_id === '2026-11-03-phone-4-01');
  deepEqual([rep.status, rep.phone, rep.task, rep.action], ['success', 'Phone 4', 'Open YouTube', 'open-app']);
  for (const [st, want] of [['timeout', 'failed'], ['offline', 'failed'], ['error', 'failed'], ['skipped', 'skipped']]) {
    env.post({ action: 'report', task_id: '2026-11-03-phone-4-02', status: st, attempts: 1 });
    assert.equal(taskRows(env).find((r) => r.task_id === '2026-11-03-phone-4-02').status, want, st);
    assert.equal(env.rows('Reports').at(-1).status, st);                                         // Reports keeps the precise status
  }
});

test('log and summary rows are appended', () => {
  const env = fresh();
  env.post({ action: 'log', run_id: 'r', level: 'warning', message: 'phone slow', device: 'cloud:p4id' });
  env.post({ action: 'summary', run_id: 'r', started: 's', workers: 'cloud:p4id', total: 3, success: 2, failed: 1, other: 0, notes: 'cloud phones: 1' });
  assert.equal(env.rows('Reports').at(-1).status, 'warning');
  const run = env.rows('Runs')[0];
  deepEqual([run.total, run.success, run.failed], [3, 2, 1]);
});

// ---------------------------------------------------------------- daily report email
function finishAll(env, outcomes = {}) {
  for (const w of ['cloud:p4id', 'cloud:p5id']) {
    for (let i = 0; i < 5; i++) {
      const c = env.post({ action: 'claim', worker: w, exact: true }).tasks[0];
      if (!c) break;
      const bad = outcomes[c.task_id];
      env.post({ action: 'report', run_id: 'r', task_id: c.task_id, device: w, task_action: c.action, status: bad ? 'failed' : 'success', attempts: 1, message: bad || 'ok' });
    }
  }
}

test('one report email when the day finishes, listing failures; none while tasks are open', () => {
  const env = fresh();
  env.setSetting('report_email', 'boss@example.com');
  queue(env);
  env.post({ action: 'claim', worker: 'cloud:p4id', exact: true });
  env.post({ action: 'report', task_id: '2026-11-03-phone-4-01', status: 'success', attempts: 1 });
  assert.equal(env.state.mail.length, 0);                                                        // others still open
  finishAll(env, { '2026-11-03-phone-4-03': 'screenshot failed' });
  assert.equal(env.state.mail.length, 1);
  const m = env.state.mail[0];
  assert.equal(m.to, 'boss@example.com');
  assert.match(m.subject, /2026-11-03.*attention needed/);
  assert.match(m.body, /Phone 4/);
  assert.match(m.body, /screenshot failed/);
  env.post({ action: 'report', task_id: '2026-11-03-phone-5-01', status: 'success', attempts: 1 });   // late duplicate report
  assert.equal(env.state.mail.length, 1);
});

test('all-OK day says so; no email when report_email is blank', () => {
  const a = fresh();
  a.setSetting('report_email', 'x@example.com');
  queue(a);
  finishAll(a);
  assert.match(a.state.mail[0].subject, /all 4 OK/);
  const b = fresh();
  queue(b);
  finishAll(b);
  assert.equal(b.state.mail.length, 0);
});

test('an email failure is logged, not thrown', () => {
  const env = fresh();
  env.setSetting('report_email', 'x@example.com');
  env.state.mailFails = true;
  queue(env);
  finishAll(env);
  assert.ok(env.rows('Reports').some((r) => r.action === 'email' && r.status === 'error'));
});

test('an unfinished batch gets an INCOMPLETE report after max_runtime + 30 min, once', () => {
  const env = fresh({ now: '2026-11-03T09:00:00Z' });
  env.setSetting('report_email', 'x@example.com');
  env.setSetting('max_runtime_min', 60);
  queue(env);
  env.setNow('2026-11-03T10:00:00Z');
  env.call('tick');
  assert.equal(env.state.mail.length, 0);
  env.setNow('2026-11-03T10:45:00Z');
  env.call('tick');
  assert.equal(env.state.mail.length, 1);
  assert.match(env.state.mail[0].body, /INCOMPLETE/);
  env.setNow('2026-11-03T11:30:00Z');
  env.call('tick');
  assert.equal(env.state.mail.length, 1);
});

test('a day with nothing to run still reports', () => {
  const env = fresh();
  env.setSetting('report_email', 'x@example.com');
  env.ctx.enqueue_({ batch: '2026-11-03', scheduled: true });
  assert.equal(env.state.mail.length, 1);
  assert.match(env.state.mail[0].body, /Nothing to run/);
});

// ---------------------------------------------------------------- tick / schedule
test('tick: nothing before run_time, one batch after, never twice a day', () => {
  const env = fresh({ now: T0 });
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  env.call('tick');
  assert.equal(taskRows(env).length, 0);
  env.setNow('2026-11-03T09:02:00Z');
  env.call('tick');
  assert.equal(taskRows(env).length, 1);
  env.setNow('2026-11-03T09:07:00Z');
  env.call('tick');
  env.setNow('2026-11-03T20:00:00Z');
  env.call('tick');
  assert.equal(taskRows(env).length, 1);
  env.setNow('2026-11-04T09:00:00Z');                                                            // next day: queued again
  env.call('tick');
  const rows = taskRows(env);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].status, 'expired');                                                       // yesterday's unfinished task
  assert.equal(rows[1].batch, '2026-11-04');
});

test('tick respects enabled, paused and the emergency stop', () => {
  for (const [k, v] of [['enabled', false], ['paused', true]]) {
    const env = fresh({ now: T0 });
    env.addRoutine(true, 'Phone 4', 'Open YouTube');
    env.setSetting(k, v);
    env.setNow('2026-11-03T09:30:00Z');
    env.call('tick');
    assert.equal(taskRows(env).length, 0, k);
  }
});

test('tick: a start missed by more than 6 hours is skipped with a warning, not run at night', () => {
  const env = fresh({ now: T0 });
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  env.setNow('2026-11-03T16:00:00Z');
  env.call('tick');
  assert.equal(taskRows(env).length, 0);
  assert.ok(env.rows('Reports').some((r) => r.action === 'schedule' && r.status === 'warning'));
  env.call('tick');
  assert.equal(env.rows('Reports').filter((r) => r.status === 'warning').length, 1);
});

test('tick: run_time forms and time zones', () => {
  const tokyo = fresh({ now: '2026-11-03T00:30:00Z', tz: 'Asia/Tokyo' });          // 09:30 in Tokyo
  tokyo.addRoutine(true, 'Phone 4', 'Open YouTube');
  tokyo.state.props.delete('LAST_SCHEDULED_DATE');
  tokyo.call('tick');
  assert.equal(taskRows(tokyo).length, 1);

  const loose = fresh({ now: '2026-11-03T07:30:00Z' });
  loose.addRoutine(true, 'Phone 4', 'Open YouTube');
  loose.setSetting('run_time', '7:05');                                              // sloppy entry still parses
  loose.call('tick');
  assert.equal(taskRows(loose).length, 1);

  const asDate = fresh({ now: '2026-11-03T06:30:00Z' });
  asDate.addRoutine(true, 'Phone 4', 'Open YouTube');
  asDate.setSetting('run_time', asDate.makeDate('1899-12-30T06:00:00Z'));                   // Sheets may store a time as a Date
  asDate.call('tick');
  assert.equal(taskRows(asDate).length, 1);

  const bad = fresh({ now: '2026-11-03T12:00:00Z' });
  bad.addRoutine(true, 'Phone 4', 'Open YouTube');
  bad.setSetting('run_time', 'sometime');
  bad.call('tick');
  assert.equal(taskRows(bad).length, 0);                                             // unparseable: do nothing rather than guess
});

test('enqueue web action: dry run, force makes a separate manual batch, paused refuses', () => {
  const env = fresh();
  env.addRoutine(true, 'Phone 4', 'Open YouTube');
  const dry = env.post({ action: 'enqueue', dry_run: true });
  assert.equal(dry.result.plan.length, 1);
  assert.equal(taskRows(env).length, 0);
  const a = env.post({ action: 'enqueue', force: true });
  assert.match(a.result.batch, /^2026-11-03-manual-\d{4}$/);
  assert.equal(taskRows(env).length, 1);
  env.setNow('2026-11-03T08:05:00Z');
  env.post({ action: 'enqueue', force: true });
  assert.equal(taskRows(env).length, 2);
  env.setSetting('paused', true);
  assert.equal(env.post({ action: 'enqueue', force: true }).error, 'paused');
});

// ---------------------------------------------------------------- settings / auth / dashboard
test('settings returned to the runner are strings; blanks fall back to defaults', () => {
  const env = fresh();
  env.setSetting('retries', 2);
  env.setSetting('paused', true);
  env.setSetting('on_failure', '');
  const s = env.post({ action: 'settings' }).settings;
  assert.equal(s.retries, '2');
  assert.equal(s.paused, 'TRUE');
  assert.equal(s.enabled, 'TRUE');
  assert.equal(s.on_failure, 'continue');
  assert.equal(s.max_cloud_phones, '2');
});

test('requests without the right secret are rejected', () => {
  const env = fresh();
  assert.equal(env.post({ action: 'ping', secret: 'nope' }).error, 'unauthorized');
  assert.equal(env.post('not json').error, 'bad_json');
  assert.equal(env.post({ action: 'ping' }).ok, true);
  assert.equal(env.post({ action: 'explode' }).error, 'unknown_action');
  const noSecret = load({ secret: null });
  assert.equal(JSON.parse(noSecret.ctx.doPost({ postData: { contents: '{"secret":"","action":"ping"}' } }).getContent()).error, 'unauthorized');
});

test('status goes to the hidden _state tab and the Overview tab is never touched', () => {
  const env = fresh();
  env.sheet('Overview').set(1, 1, 'MY DESIGN');
  env.sheet('Overview').set(5, 3, '=COUNTIF(Tasks!K:K,1)');
  env.call('refreshDashboard_');
  const st = Object.fromEntries(env.sheet('_state').grid.map((r) => [r[0], r[1]]));
  assert.equal(st.status, 'Active');
  assert.equal(st.latest_batch, '(none yet)');
  assert.match(st.next_run, /^(today|tomorrow) at 09:00$/);
  assert.equal(st.timezone, 'UTC');
  assert.equal(env.sheet('_state').hidden, true);
  queue(env);
  finishAll(env, { '2026-11-03-phone-4-02': 'boom' });
  assert.equal(env.sheet('_state').get(4, 2), '2026-11-03');
  env.setSetting('paused', true);
  env.call('refreshDashboard_');
  assert.match(env.sheet('_state').get(2, 2), /PAUSED/);
  assert.equal(env.sheet('Overview').get(1, 1), 'MY DESIGN');           // design untouched
  assert.equal(env.sheet('Overview').get(5, 3), '=COUNTIF(Tasks!K:K,1)');
});

test('setup never overwrites a dropdown, colour rules or the Overview that already exist', () => {
  const env = fresh();
  const chip = { kind: 'validation', type: 'requireValueInRange', customUi: 'CHIP', getCriteriaType: () => 'requireValueInRange' };
  env.sheet('Routine').validations['2,2'] = chip;                       // e.g. a dropdown converted to a chip in the sheet
  const marker = [{ marker: 'my-rule' }];
  env.sheet('Tasks').cfRules = marker;
  env.sheet('Overview').set(1, 1, 'MY DESIGN');
  env.setup();
  assert.equal(env.sheet('Routine').validations['2,2'], chip);
  assert.equal(env.sheet('Tasks').cfRules, marker);
  assert.equal(env.sheet('Overview').get(1, 1), 'MY DESIGN');
  assert.equal(env.sheet('Routine').validations['2,1'].type, 'requireCheckbox');   // gaps still get defaults
});

test('a broken Settings tab or Library never stops claims from working', () => {
  const env = fresh();
  env.sheet('Tasks').appendRow(['t1', 'cloud:p4id', 'key', '{"name":"home"}', 'pending', '', '', '', '', '', '', '', '', '']);
  delete env.state.sheets._state;                                                                // status tab is cosmetic
  assert.equal(env.post({ action: 'claim', worker: 'cloud:p4id', exact: true }).tasks.length, 1);
  assert.equal(env.post({ action: 'report', task_id: 't1', status: 'success', attempts: 1 }).ok, true);
});

test('the script never hardcodes the secret', () => {
  const src = require('fs').readFileSync(require('path').join(__dirname, '..', 'sheets', 'apps_script.gs'), 'utf8');
  assert.doesNotMatch(src, /SECRET['"]?\s*[:=]\s*['"][^'"]{6,}['"]/);
});
