/**
 * GeeLark bulk automation backend: a Google Sheet as task queue + report log.
 *
 * Setup (see references/bulk_automation.md):
 *   1. Open a Google Sheet > Extensions > Apps Script, paste this file.
 *   2. Project Settings > Script properties: add SECRET = <long random string>.
 *   3. Run setup() once (authorize). It creates the Tasks / Reports / Runs tabs.
 *   4. Deploy > New deployment > Web app: Execute as "Me", access "Anyone".
 *      (The secret, not the URL, is what protects it.) Copy the /exec URL.
 *   5. export GEELARK_SHEETS_URL=<that url>  GEELARK_SHEETS_SECRET=<the secret>
 */

var TASKS = 'Tasks';
var REPORTS = 'Reports';
var RUNS = 'Runs';
var TASK_HEADERS = ['task_id', 'device', 'action', 'params', 'status', 'attempts', 'worker', 'claimed_at', 'finished_at', 'result'];
var REPORT_HEADERS = ['timestamp', 'run_id', 'task_id', 'device', 'action', 'status', 'attempts', 'duration_s', 'message', 'output'];
var RUN_HEADERS = ['run_id', 'started', 'finished', 'workers', 'total', 'success', 'failed', 'other', 'notes'];
var STALE_MINUTES = 15;   // a task stuck in "running" longer than this is handed out again
var CELL_LIMIT = 2000;    // keep cells small; full detail lives in the local JSONL run log

function setup() {
  ensureSheet_(TASKS, TASK_HEADERS);
  ensureSheet_(REPORTS, REPORT_HEADERS);
  ensureSheet_(RUNS, RUN_HEADERS);
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('SECRET')) {
    throw new Error('Add a script property named SECRET (Project Settings > Script properties) and run setup() again.');
  }
  // Example row so the queue format is obvious; delete it freely.
  var tasks = SpreadsheetApp.getActive().getSheetByName(TASKS);
  if (tasks.getLastRow() < 2) {
    tasks.appendRow(['example-1', '', 'open-app', '{"name":"settings"}', 'done-example', '', '', '', '', 'delete this row']);
  }
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return out_({ ok: false, error: 'bad_json' });
  }
  var secret = PropertiesService.getScriptProperties().getProperty('SECRET');
  if (!secret || body.secret !== secret) {
    return out_({ ok: false, error: 'unauthorized' });
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(25000);   // serializes claims so two workers never get the same task
  try {
    switch (body.action) {
      case 'ping':    return out_({ ok: true, now: new Date().toISOString() });
      case 'claim':   return out_(claim_(body));
      case 'devices': return out_(devices_(body));
      case 'report':  return out_(report_(body));
      case 'log':     return out_(log_(body));
      case 'summary': return out_(summary_(body));
      default:        return out_({ ok: false, error: 'unknown_action' });
    }
  } catch (err) {
    return out_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function claim_(body) {
  var sheet = sheet_(TASKS);
  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return { ok: true, tasks: [] };
  var col = indexMap_(values[0]);
  var worker = String(body.worker || '');
  var limit = Math.max(1, Math.min(Number(body.limit) || 1, 20));
  var now = new Date();
  var claimed = [];
  for (var r = 1; r < values.length && claimed.length < limit; r++) {
    var row = values[r];
    var status = String(row[col.status] || '').trim().toLowerCase();
    var device = String(row[col.device] || '').trim();
    var action = String(row[col.action] || '').trim();
    if (!action) continue;
    var stale = false;
    if (status === 'running' && row[col.claimed_at]) {
      stale = (now - new Date(row[col.claimed_at])) > STALE_MINUTES * 60000;
    }
    if (!(status === '' || status === 'pending' || stale)) continue;
    if (device && device !== worker) continue;          // blank device = any worker may take it
    if (!device && body.exact) continue;                // ...except billed cloud phones, which only take tasks addressed to them
    var taskId = String(row[col.task_id] || '') || ('row-' + (r + 1));
    sheet.getRange(r + 1, col.task_id + 1).setValue(taskId);
    sheet.getRange(r + 1, col.status + 1).setValue('running');
    sheet.getRange(r + 1, col.worker + 1).setValue(worker);
    sheet.getRange(r + 1, col.claimed_at + 1).setValue(now.toISOString());
    claimed.push({
      task_id: taskId,
      device: device,
      action: action,
      params: String(row[col.params] || ''),
      attempts: Number(row[col.attempts]) || 0
    });
  }
  return { ok: true, tasks: claimed };
}

// Distinct devices named by tasks that are waiting to run, so the runner knows which cloud phones to start.
function devices_(body) {
  var values = sheet_(TASKS).getDataRange().getValues();
  if (values.length < 2) return { ok: true, devices: [] };
  var col = indexMap_(values[0]);
  var now = new Date();
  var seen = {};
  for (var r = 1; r < values.length; r++) {
    var status = String(values[r][col.status] || '').trim().toLowerCase();
    var stale = status === 'running' && values[r][col.claimed_at] &&
                (now - new Date(values[r][col.claimed_at])) > STALE_MINUTES * 60000;
    if (!(status === '' || status === 'pending' || stale)) continue;
    if (!String(values[r][col.action] || '').trim()) continue;
    var device = String(values[r][col.device] || '').trim();
    if (device) seen[device] = true;
  }
  return { ok: true, devices: Object.keys(seen) };
}

function report_(body) {
  var sheet = sheet_(TASKS);
  var values = sheet.getDataRange().getValues();
  var col = indexMap_(values[0]);
  var status = String(body.status || 'unknown');
  for (var r = 1; r < values.length; r++) {
    if (String(values[r][col.task_id]) === String(body.task_id)) {
      sheet.getRange(r + 1, col.status + 1).setValue(status === 'success' ? 'success' : 'failed');
      sheet.getRange(r + 1, col.attempts + 1).setValue(Number(body.attempts) || 0);
      sheet.getRange(r + 1, col.finished_at + 1).setValue(new Date().toISOString());
      sheet.getRange(r + 1, col.result + 1).setValue(clip_(body.message));
      break;
    }
  }
  sheet_(REPORTS).appendRow([
    new Date().toISOString(), body.run_id || '', body.task_id || '', body.device || '', body.task_action || '',
    status, Number(body.attempts) || 0, Number(body.duration_s) || 0, clip_(body.message), clip_(body.output)
  ]);
  return { ok: true };
}

// Non-task events: device offline, retries, warnings, "any other report".
function log_(body) {
  sheet_(REPORTS).appendRow([
    new Date().toISOString(), body.run_id || '', body.task_id || '', body.device || '', body.task_action || 'event',
    body.level || 'info', '', '', clip_(body.message), clip_(body.output)
  ]);
  return { ok: true };
}

function summary_(body) {
  sheet_(RUNS).appendRow([
    body.run_id || '', body.started || '', body.finished || new Date().toISOString(), body.workers || '',
    Number(body.total) || 0, Number(body.success) || 0, Number(body.failed) || 0, Number(body.other) || 0, clip_(body.notes)
  ]);
  return { ok: true };
}

function sheet_(name) {
  var s = SpreadsheetApp.getActive().getSheetByName(name);
  if (!s) throw new Error('Missing tab "' + name + '". Run setup().');
  return s;
}

function ensureSheet_(name, headers) {
  var ss = SpreadsheetApp.getActive();
  var s = ss.getSheetByName(name) || ss.insertSheet(name);
  if (s.getLastRow() === 0) {
    s.appendRow(headers);
    s.setFrozenRows(1);
    s.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  }
}

function indexMap_(headerRow) {
  var map = {};
  for (var i = 0; i < headerRow.length; i++) map[String(headerRow[i]).trim()] = i;
  TASK_HEADERS.forEach(function (h) {
    if (map[h] === undefined) throw new Error('Tasks tab is missing column "' + h + '"');
  });
  return map;
}

function clip_(v) {
  var s = v === undefined || v === null ? '' : String(v);
  return s.length > CELL_LIMIT ? s.slice(0, CELL_LIMIT) + '…' : s;
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
