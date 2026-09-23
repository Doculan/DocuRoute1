// Minimal Chrome DevTools driver for DocuRoute: one command per line.
// Needs Node 22+ (global WebSocket and fetch) and Chrome listening on 9222.
// No dependencies. `${NAME}` in a line is replaced from the environment.
//
//   node cdp.mjs <script.cdp> <screenshot-dir>
//
//   nav <url>
//   wait <text>                  wait until the page text contains <text>
//   click <css> | <text>         click the first <css> element whose text contains <text>
//   type <css> | <text>          focus <css>, then type <text> as real input
//   upload <css> | <path>        set a file input's file (fires change)
//   shot <name>                  screenshot to <dir>/<name>.png
//   text <css>                   print the innerText of <css>
//   errors                       print console errors and exceptions so far
//   ? <command>                  optional: on failure, report and carry on
import fs from 'node:fs';
import path from 'node:path';

const [, , scriptPath, outDir] = process.argv;
const lines = fs.readFileSync(scriptPath, 'utf8')
  .split(/\r?\n/)
  .filter((l) => l.trim() && !l.startsWith('#'))
  .map((l) => l.replace(/\$\{(\w+)\}/g, (_, name) => {
    if (!(name in process.env)) throw new Error(`${name} is not set in the environment`);
    return process.env[name];
  }));
fs.mkdirSync(outDir, { recursive: true });

const targets = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const page = targets.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((ok) => ws.addEventListener('open', ok));

let id = 0;
const waiting = new Map();
const problems = [];
ws.addEventListener('message', (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && waiting.has(msg.id)) {
    const { ok, fail } = waiting.get(msg.id);
    waiting.delete(msg.id);
    msg.error ? fail(new Error(JSON.stringify(msg.error))) : ok(msg.result);
  } else if (msg.method === 'Runtime.exceptionThrown') {
    problems.push('exception: ' + (msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text));
  } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
    problems.push('console.error: ' + msg.params.args.map((a) => a.value ?? a.description).join(' '));
  }
});
const send = (method, params = {}) => new Promise((ok, fail) => {
  const n = ++id;
  waiting.set(n, { ok, fail });
  ws.send(JSON.stringify({ id: n, method, params }));
});
const evaluate = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// "<css> | <text>", split at the first bar. Not on " | ": editors strip the
// trailing space from "click <css> | ", and the selector must not inherit
// the bar when they do.
const split = (rest) => {
  const bar = rest.indexOf('|');
  if (bar < 0) return [rest.trim(), ''];
  return [rest.slice(0, bar).trim(), rest.slice(bar + 1).trim()];
};

await send('Page.enable');
await send('Runtime.enable');
await send('DOM.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });

for (const raw of lines) {
  // "? <command>" is optional: a failure is reported and the script goes on.
  const optional = raw.startsWith('? ');
  const line = optional ? raw.slice(2) : raw;
  const [cmd, ...restParts] = line.split(' ');
  const rest = restParts.join(' ');
  try {
    if (cmd === 'nav') {
      await send('Page.navigate', { url: rest });
      await sleep(1500);
    } else if (cmd === 'wait') {
      const until = Date.now() + 20000;
      let found = false;
      while (Date.now() < until) {
        found = await evaluate(`document.body && document.body.innerText.includes(${JSON.stringify(rest)})`);
        if (found) break;
        await sleep(250);
      }
      if (!found) throw new Error('text never appeared');
    } else if (cmd === 'click') {
      const [css, text] = split(rest);
      const clicked = await evaluate(`(() => {
        const el = [...document.querySelectorAll(${JSON.stringify(css)})]
          .find((e) => e.innerText.includes(${JSON.stringify(text || '')}));
        if (!el) return false; el.scrollIntoView({block: 'center'}); el.click(); return true; })()`);
      if (!clicked) throw new Error('nothing to click');
      await sleep(600);
    } else if (cmd === 'type') {
      const [css, text] = split(rest);
      const focused = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(css)});
        if (!el) return false; el.focus(); return true; })()`);
      if (!focused) throw new Error('no such input');
      await send('Input.insertText', { text });
    } else if (cmd === 'upload') {
      const [css, file] = split(rest);
      const { root } = await send('DOM.getDocument', { depth: -1 });
      const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: css });
      if (!nodeId) throw new Error('no such file input');
      await send('DOM.setFileInputFiles', { nodeId, files: [path.resolve(file)] });
      await sleep(2500);
    } else if (cmd === 'shot') {
      const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      fs.writeFileSync(path.join(outDir, rest + '.png'), Buffer.from(data, 'base64'));
    } else if (cmd === 'text') {
      console.log('TEXT', rest, '=>', JSON.stringify(await evaluate(
        `(document.querySelector(${JSON.stringify(rest)}) || {}).innerText || null`)));
      continue;
    } else if (cmd === 'errors') {
      console.log('ERRORS', problems.length ? problems : 'none');
      continue;
    }
    console.log('ok  ', line);
  } catch (err) {
    if (optional) {
      console.log('skip', line, '->', err.message);
      continue;
    }
    console.log('FAIL', line, '->', err.message);
    process.exitCode = 1;
    break;
  }
}
ws.close();
