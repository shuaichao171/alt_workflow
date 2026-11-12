import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

function positiveMs(value, label) {
  const milliseconds = Number(value);
  if (!Number.isSafeInteger(milliseconds) || milliseconds < 1 || milliseconds > 2147483647) {
    throw new Error(`${label} 必须是 1 到 2147483647 之间的整数毫秒`);
  }
  return milliseconds;
}

export async function discoverEndpoint(userDataDir = process.env.CHROME_USER_DATA_DIR) {
  if (!userDataDir) {
    if (!process.env.LOCALAPPDATA) throw new Error('请用 --user-data-dir 指定 Chrome 数据根目录');
    userDataDir = path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'User Data');
  }
  let contents;
  try {
    contents = await readFile(path.join(userDataDir, 'DevToolsActivePort'), 'utf8');
  } catch (error) {
    throw new Error(`无法读取 DevToolsActivePort（${error.code ?? '读取失败'}）；请确认 Chrome 已运行、远程调试已开启、数据根目录正确`);
  }
  const [portText, browserPath] = contents.replace(/^\uFEFF/, '').trim().split(/\r?\n/);
  const port = Number(portText);
  if (!/^\d+$/.test(portText) || !Number.isInteger(port) || port < 1 || port > 65535 ||
      !/^\/devtools\/browser\/[A-Za-z0-9_-]+$/.test(browserPath ?? '')) {
    throw new Error('DevToolsActivePort 格式不正确；请重新检查 Chrome 调试状态');
  }
  return `ws://127.0.0.1:${port}${browserPath}`;
}

export class ChromeCdp {
  #socket;
  #nextId = 0;
  #pending = new Map();
  #listeners = new Set();
  #timeoutMs;

  constructor(socket, timeoutMs) {
    this.#socket = socket;
    this.#timeoutMs = positiveMs(timeoutMs, 'timeoutMs');
    socket.addEventListener('message', event => {
      let message;
      try { message = JSON.parse(event.data); }
      catch { this.#rejectPending(new Error('收到无法解析的 CDP 消息')); return; }
      if (message.id !== undefined) {
        const pending = this.#pending.get(message.id);
        if (!pending) return;
        clearTimeout(pending.timer);
        this.#pending.delete(message.id);
        if (message.error) pending.reject(new Error(`CDP ${pending.method}: ${message.error.message}`));
        else pending.resolve(message.result);
      } else {
        for (const listener of this.#listeners) {
          try { listener(message); }
          catch { this.#rejectPending(new Error('CDP 事件监听回调执行失败')); }
        }
      }
    });
    socket.addEventListener('close', () => {
      this.#rejectPending(new Error('CDP 连接已关闭；重试前先核对实际页面状态'));
      this.#listeners.clear();
    });
    socket.addEventListener('error', () => this.#rejectPending(new Error('CDP WebSocket 连接失败')));
  }

  #rejectPending(error) {
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.#pending.clear();
  }

  static async connect({ userDataDir, connectTimeoutMs = 90000, timeoutMs = 20000 } = {}) {
    if (typeof WebSocket !== 'function') throw new Error('需要支持原生 WebSocket 的 Node.js（建议 22.4+）');
    connectTimeoutMs = positiveMs(connectTimeoutMs, 'connectTimeoutMs');
    timeoutMs = positiveMs(timeoutMs, 'timeoutMs');
    const socket = new WebSocket(await discoverEndpoint(userDataDir));
    const client = new ChromeCdp(socket, timeoutMs);
    try {
      await new Promise((resolve, reject) => {
        const finish = error => {
          clearTimeout(timer);
          socket.removeEventListener('open', onOpen);
          socket.removeEventListener('error', onError);
          socket.removeEventListener('close', onClose);
          if (error) reject(error); else resolve();
        };
        const onOpen = () => finish();
        const onError = () => finish(new Error('连接 Chrome 失败；请检查远程调试状态与端口文件'));
        const onClose = () => finish(new Error('Chrome 在建立连接时关闭了调试连接'));
        const timer = setTimeout(() => finish(new Error('等待 Chrome 连接授权超时；请检查浏览器的允许／拒绝提示')), connectTimeoutMs);
        socket.addEventListener('open', onOpen, { once: true });
        socket.addEventListener('error', onError, { once: true });
        socket.addEventListener('close', onClose, { once: true });
      });
      return client;
    } catch (error) {
      await client.close();
      throw error;
    }
  }

  call(method, params = {}, sessionId) {
    if (this.#socket.readyState !== WebSocket.OPEN) return Promise.reject(new Error('CDP 连接未打开'));
    const id = ++this.#nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`CDP ${method} 超时；重试前先核对实际页面状态`));
      }, this.#timeoutMs);
      this.#pending.set(id, { resolve, reject, timer, method });
      try {
        this.#socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
      } catch (error) {
        clearTimeout(timer);
        this.#pending.delete(id);
        reject(error);
      }
    });
  }

  onEvent(listener) {
    if (typeof listener !== 'function') throw new TypeError('listener 必须是函数');
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  async close() {
    this.#rejectPending(new Error('本次 CDP 客户端正在断开连接'));
    this.#listeners.clear();
    if (this.#socket.readyState === WebSocket.CLOSED) return;
    await new Promise(resolve => {
      const finish = () => {
        clearTimeout(timer);
        this.#socket.removeEventListener('close', finish);
        resolve();
      };
      const timer = setTimeout(finish, 3000);
      this.#socket.addEventListener('close', finish, { once: true });
      try { this.#socket.close(); } catch { finish(); }
    });
  }
}

export async function withChrome(task, options) {
  const cdp = await ChromeCdp.connect(options);
  try { return await task(cdp); }
  finally { await cdp.close(); }
}

async function probe(cdp) {
  const version = await cdp.call('Browser.getVersion');
  const { targetInfos } = await cdp.call('Target.getTargets');
  return { connected: true, browser: version.product, pageCount: targetInfos.filter(t => t.type === 'page').length };
}

async function smoke(cdp, screenshotPath) {
  const baseline = await probe(cdp);
  const { targetId } = await cdp.call('Target.createTarget', { url: 'about:blank' });
  let result;
  let operationError;
  try {
    const { sessionId } = await cdp.call('Target.attachToTarget', { targetId, flatten: true });
    const written = await cdp.call('Runtime.evaluate', {
      expression: `(() => {
        document.title = 'CDP direct connection verified';
        document.documentElement.lang = 'zh-CN';
        document.body.innerHTML = '<main style="font-family:Arial,sans-serif;padding:64px"><h1>CDP 直连测试成功</h1><p>Node.js 原生 WebSocket → CDP → Chrome</p><p>此临时标签页将在验证后关闭。</p></main>';
      })()`,
    }, sessionId);
    if (written.exceptionDetails) throw new Error('测试页写入时发生 JavaScript 异常');
    const checked = await cdp.call('Runtime.evaluate', {
      expression: '({title:document.title, heading:document.querySelector("h1")?.textContent})', returnByValue: true,
    }, sessionId);
    if (checked.exceptionDetails || checked.result?.value?.title !== 'CDP direct connection verified' ||
        checked.result?.value?.heading !== 'CDP 直连测试成功') throw new Error('测试页回读验证失败');
    const { data } = await cdp.call('Page.captureScreenshot', { format: 'png' }, sessionId);
    await mkdir(path.dirname(path.resolve(screenshotPath)), { recursive: true });
    await writeFile(screenshotPath, Buffer.from(data, 'base64'));
    result = { ...baseline, controlVerified: true, screenshotSaved: true };
  } catch (error) {
    operationError = error;
  } finally {
    try {
      const closed = await cdp.call('Target.closeTarget', { targetId });
      const { targetInfos } = await cdp.call('Target.getTargets');
      if (!closed.success || targetInfos.some(t => t.targetId === targetId)) throw new Error('测试标签页未成功关闭');
      if (result) result.testTabClosed = true;
    } catch (error) {
      throw new Error(`${operationError ? `${operationError.message}；` : ''}测试页清理失败：${error.message}`);
    }
  }
  if (operationError) throw operationError;
  return result;
}

async function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      'user-data-dir': { type: 'string' },
      'connect-timeout-ms': { type: 'string', default: '90000' },
      'timeout-ms': { type: 'string', default: '20000' },
      screenshot: { type: 'string' },
      script: { type: 'string' },
      help: { type: 'boolean' },
    },
  });
  if (values.help) {
    console.log('用法：node cdp.mjs probe | smoke --screenshot <PNG> | run --script <任务.mjs>');
    console.log('通用参数：--user-data-dir <数据根目录> --connect-timeout-ms <毫秒> --timeout-ms <毫秒>');
    return;
  }
  const command = positionals[0] ?? 'probe';
  if (positionals.length > 1 || !['probe', 'smoke', 'run'].includes(command)) throw new Error('命令必须是 probe、smoke 或 run');
  if (command === 'smoke' && !values.screenshot) throw new Error('smoke 需要 --screenshot 指定目标项目内的截图文件');
  if (command === 'run' && !values.script) throw new Error('run 需要 --script 指定任务脚本');
  let task = probe;
  if (command === 'smoke') task = cdp => smoke(cdp, values.screenshot);
  if (command === 'run') {
    task = (await import(pathToFileURL(path.resolve(values.script)).href)).default;
    if (typeof task !== 'function') throw new Error('任务脚本必须默认导出一个函数');
  }
  console.error('正在直连 Chrome CDP；若浏览器请求远程调试授权，请由用户确认。');
  const result = await withChrome(task, {
    userDataDir: values['user-data-dir'],
    connectTimeoutMs: positiveMs(values['connect-timeout-ms'], '--connect-timeout-ms'),
    timeoutMs: positiveMs(values['timeout-ms'], '--timeout-ms'),
  });
  console.log(JSON.stringify(result ?? { completed: true }));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    console.error(JSON.stringify({ error: error.message }));
    process.exitCode = 1;
  });
}
