'use strict';
// A small in-memory Google Sheets/Apps Script environment, so sheets/apps_script.gs can be unit-tested
// without Google. It implements only the calls the script makes.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SCRIPT = path.join(__dirname, '..', 'sheets', 'apps_script.gs');

function colToIndex(letters) {
  let n = 0;
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

class Range {
  constructor(sheet, row, col, nrows, ncols) {
    Object.assign(this, { sheet, row, col, nrows, ncols });
  }
  getValues() {
    const out = [];
    for (let r = 0; r < this.nrows; r++) {
      const line = [];
      for (let c = 0; c < this.ncols; c++) line.push(this.sheet.get(this.row + r, this.col + c));
      out.push(line);
    }
    return out;
  }
  getValue() { return this.sheet.get(this.row, this.col); }
  getFormula() { return this.sheet.formulas[`${this.row},${this.col}`] || ''; }
  setValue(v) { this.sheet.set(this.row, this.col, v); return this; }
  setValues(vals) {
    vals.forEach((line, r) => line.forEach((v, c) => this.sheet.set(this.row + r, this.col + c, v)));
    return this;
  }
  setFormula(f) { this.sheet.set(this.row, this.col, f); this.sheet.formulas[`${this.row},${this.col}`] = f; return this; }
  clearContent() {
    for (let r = 0; r < this.nrows; r++) for (let c = 0; c < this.ncols; c++) this.sheet.set(this.row + r, this.col + c, '');
    return this;
  }
  setDataValidation(rule) {
    for (let r = 0; r < this.nrows; r++) for (let c = 0; c < this.ncols; c++) this.sheet.validations[`${this.row + r},${this.col + c}`] = rule;
    return this;
  }
  getDataValidation() { return this.sheet.validations[`${this.row},${this.col}`] || null; }
  setFontWeight() { return this; }
  setNumberFormat() { return this; }
}

class Sheet {
  constructor(name) {
    this.name = name;
    this.grid = [];           // grid[r-1][c-1]
    this.validations = {};
    this.formulas = {};
    this.cfRules = [];
  }
  get(r, c) {
    const v = (this.grid[r - 1] || [])[c - 1];
    return v === undefined ? '' : v;
  }
  set(r, c, v) {
    while (this.grid.length < r) this.grid.push([]);
    const line = this.grid[r - 1];
    while (line.length < c) line.push('');
    line[c - 1] = v;
  }
  getLastRow() {
    for (let r = this.grid.length; r >= 1; r--) if (this.grid[r - 1].some((v) => v !== '' && v !== undefined)) return r;
    return 0;
  }
  getLastColumn() {
    let max = 0;
    this.grid.forEach((line) => line.forEach((v, i) => { if (v !== '' && v !== undefined) max = Math.max(max, i + 1); }));
    return max;
  }
  getDataRange() { return new Range(this, 1, 1, Math.max(1, this.getLastRow()), Math.max(1, this.getLastColumn())); }
  getRange(a, b, c, d) {
    if (typeof a === 'string') {
      const m = /^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/.exec(a);
      const c1 = colToIndex(m[1]), r1 = Number(m[2]);
      const c2 = m[3] ? colToIndex(m[3]) : c1, r2 = m[4] ? Number(m[4]) : r1;
      return new Range(this, r1, c1, r2 - r1 + 1, c2 - c1 + 1);
    }
    return new Range(this, a, b, c || 1, d || 1);
  }
  appendRow(vals) { const r = this.getLastRow() + 1; vals.forEach((v, i) => this.set(r, i + 1, v)); }
  setFrozenRows() {}
  clearContents() { this.grid = []; }
  hideSheet() { this.hidden = true; }
  getConditionalFormatRules() { return this.cfRules; }
  autoResizeColumns() {}
  setConditionalFormatRules(rules) { this.cfRules = rules; }
  // test helpers
  rowsAsObjects() {
    const headers = (this.grid[0] || []).map(String);
    return this.grid.slice(1).filter((l) => l.some((v) => v !== '')).map((line) => {
      const o = {};
      headers.forEach((h, i) => { o[h] = line[i] === undefined ? '' : line[i]; });
      return o;
    });
  }
}

function fmtDate(date, tz, pattern) {
  const parts = {};
  new Intl.DateTimeFormat('en-GB', { timeZone: tz || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(date).forEach((p) => { parts[p.type] = p.value; });
  if (parts.hour === '24') parts.hour = '00';
  return pattern.replace('yyyy', parts.year).replace('MM', parts.month).replace('dd', parts.day)
    .replace('HH', parts.hour).replace('mm', parts.minute);
}

function load(options = {}) {
  const state = {
    sheets: {}, order: [], props: new Map(), triggers: [], mail: [], alerts: [], tz: options.tz || 'UTC',
    now: new Date(options.now || '2026-11-03T08:00:00Z'),
  };
  if (options.secret !== null) state.props.set('SECRET', options.secret || 'test-secret');

  const spreadsheet = {
    getSheetByName: (n) => state.sheets[n] || null,
    insertSheet: (n) => { state.sheets[n] = new Sheet(n); state.order.push(n); return state.sheets[n]; },
    getSpreadsheetTimeZone: () => state.tz,
    getUrl: () => 'https://docs.google.com/spreadsheets/d/TEST',
  };
  const builder = (kind) => {
    const rule = { kind };
    const proxy = new Proxy(rule, {
      get(target, prop) {
        if (prop === 'build') return () => { target.getCriteriaType = () => target.type; return target; };
        if (prop in target) return target[prop];
        return (...args) => { target[prop] = args; if (/^require/.test(prop)) target.type = prop; return proxy; };
      },
    });
    return proxy;
  };
  const ctx = {
    console,
    SpreadsheetApp: {
      getActive: () => spreadsheet,
      newDataValidation: () => builder('validation'),
      newConditionalFormatRule: () => builder('cf'),
      getUi: () => ({ alert: (...a) => { state.alerts.push(a); return 'YES'; }, ButtonSet: { OK: 'OK', YES_NO: 'YES_NO' }, Button: { YES: 'YES' },
        createMenu: () => { const m = { addItem: () => m, addToUi: () => m }; return m; } }),
    },
    PropertiesService: { getScriptProperties: () => ({
      getProperty: (k) => (state.props.has(k) ? state.props.get(k) : null),
      setProperty: (k, v) => state.props.set(k, String(v)),
      deleteProperty: (k) => state.props.delete(k),
    }) },
    LockService: { getScriptLock: () => ({ waitLock() {}, tryLock: () => true, releaseLock() {} }) },
    ContentService: { MimeType: { JSON: 'json' }, createTextOutput: (s) => ({ getContent: () => s, setMimeType() { return this; } }) },
    Utilities: { formatDate: (d, tz, p) => fmtDate(d, tz, p) },
    ScriptApp: {
      getProjectTriggers: () => state.triggers.map((fn) => ({ getHandlerFunction: () => fn })),
      deleteTrigger: (t) => { const i = state.triggers.indexOf(t.getHandlerFunction()); if (i >= 0) state.triggers.splice(i, 1); },
      newTrigger: (fn) => { const t = { timeBased: () => t, everyMinutes: () => t, create: () => state.triggers.push(fn) }; return t; },
    },
    MailApp: { sendEmail: (to, subject, body) => { if (state.mailFails) throw new Error('quota'); state.mail.push({ to, subject, body }); } },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), ctx, { filename: 'apps_script.gs' });
  ctx.NOW_ = () => new Date(state.now);

  const api = {
    ctx, state,
    sheet: (name) => state.sheets[name],
    rows: (name) => state.sheets[name].rowsAsObjects(),
    setNow: (iso) => { state.now = new Date(iso); },
    makeDate: (iso) => vm.runInContext(`new Date(${JSON.stringify(iso)})`, ctx),   // a Date from the script's own realm
    call: (fn, ...args) => ctx[fn](...args),
    post(body) {
      const res = ctx.doPost({ postData: { contents: typeof body === 'string' ? body : JSON.stringify(Object.assign({ secret: options.secret || 'test-secret' }, body)) } });
      return JSON.parse(res.getContent());
    },
    setup() { return ctx.setup(); },
    setSetting(key, value) {
      const sh = state.sheets.Settings;
      for (let r = 2; r <= sh.getLastRow(); r++) if (sh.get(r, 1) === key) { sh.set(r, 2, value); return; }
      sh.appendRow([key, value, '']);
    },
    addPhone(enabled, label, type, id) { state.sheets.Phones.appendRow([enabled, label, type, id, '']); },
    addRoutine(enabled, phone, task, value = '', duration = '') { state.sheets.Routine.appendRow([enabled, phone, task, value, duration, '']); },
    clearExamples() {
      ['Phones', 'Routine'].forEach((n) => { const sh = state.sheets[n]; for (let r = 2; r <= sh.getLastRow(); r++) for (let c = 1; c <= 6; c++) sh.set(r, c, ''); });
    },
  };
  return api;
}

// Resolve every seeded Library task with sample inputs, as the runner would receive it (used by the Python contract test).
function seedTasks() {
  const env = load();
  env.setup();
  env.clearExamples();
  env.addPhone(true, 'P1', 'cloud', 'abc123');
  const out = [];
  env.rows('Library').forEach((lib) => {
    env.clearExamples();
    env.addPhone(true, 'P1', 'cloud', 'abc123');
    env.addRoutine(true, 'P1', lib.name, 'https://www.youtube.com/watch?v=Bm84BAtOfQw&t=3', 30);
    const res = env.ctx.enqueue_({ batch: '2026-11-03', dryRun: true });
    res.plan.forEach((p) => out.push({ task_id: p.task_id, device: p.device, action: p.action, params: p.params, name: lib.name }));
    if (res.problems.length) out.push({ problem: res.problems.join('; '), name: lib.name });
  });
  return out;
}

module.exports = { load, seedTasks };

if (require.main === module && process.argv[2] === 'seed-tasks') {
  process.stdout.write(JSON.stringify(seedTasks()));
}
