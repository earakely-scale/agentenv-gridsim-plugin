/** An OpenEnv WebSocket session on this server (/ws): reset, list_tools and call_tool, one request at a time, as any
 * OpenEnv client sends them; the server gives each socket its own environment. */
export class EnvSession {
  constructor(onStatus) {
    this.onStatus = onStatus;
    this.ws = null;
    this.pending = [];
    this.status = "idle";
    this.closing = false;
  }

  set(status, detail) {
    this.status = status;
    this.onStatus?.(status, detail);
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return Promise.resolve();
    if (this.opening) return this.opening;
    this.closing = false;
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
    this.set("connecting");
    this.opening = new Promise((resolve, reject) => {
      let ws;
      try {
        ws = new WebSocket(url);
      } catch (e) {
        this.opening = null;
        this.set("dropped", String(e));
        reject(e);
        return;
      }
      this.ws = ws;
      let opened = false;
      ws.onopen = () => {
        opened = true;
        this.opening = null;
        this.set("open");
        resolve();
      };
      ws.onmessage = (e) => {
        let msg;
        try {
          msg = JSON.parse(e.data);
        } catch {
          msg = { type: "error", data: { message: String(e.data) } };
        }
        const p = this.pending.shift();
        if (p) p.resolve(msg);
        else if (msg.type === "error") this.refusal = msg.data || {};
      };
      ws.onclose = (e) => {
        this.opening = null;
        const why = this.refusal;
        for (const p of this.pending.splice(0)) p.reject(Object.assign(new Error(why?.message || "the connection closed"), { code: why?.code }));
        if (this.ws === ws) this.ws = null;
        if (!opened) reject(new Error(`could not open ${url}`));
        this.set(this.closing ? "idle" : "dropped", e.code);
      };
      ws.onerror = () => {};
    });
    return this.opening;
  }

  async request(msg) {
    await this.connect();
    return new Promise((resolve, reject) => {
      this.pending.push({ resolve, reject });
      try {
        this.ws.send(JSON.stringify(msg));
      } catch (e) {
        this.pending.pop();
        reject(e);
      }
    });
  }

  reset(data) {
    return this.request({ type: "reset", data });
  }

  listTools() {
    return this.request({ type: "step", data: { type: "list_tools" } });
  }

  call(name, args) {
    return this.request({ type: "step", data: { type: "call_tool", tool_name: name, arguments: args } });
  }

  close() {
    this.closing = true;
    if (this.ws) {
      try {
        if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "close" }));
        this.ws.close();
      } catch {}
    }
    this.ws = null;
  }
}

/** The observation of a response: its fields, metadata, reward and done; or the server's error. */
export function unwrap(resp) {
  if (!resp) return { error: "no response" };
  if (resp.type === "error") {
    const d = resp.data || {};
    return { error: d.message || d.code || "error", code: d.code, data: d };
  }
  const d = resp.data || {};
  const obs = d.observation || {};
  const meta = { ...(obs.metadata || {}), ...(d.metadata || {}) };
  return { obs, meta, reward: d.reward ?? obs.reward ?? null, done: !!(d.done ?? obs.done) };
}

/** The text a tool answered with (the exact string an agent reads), parsed as JSON when it is JSON. */
export function answer(obs) {
  if (obs.error) return { error: obs.error.message || String(obs.error), framework: true };
  const text = obs.result?.data ?? obs.result?.content?.map((c) => c.text).join("\n");
  if (text == null) return { error: "empty result" };
  try {
    return { json: JSON.parse(text), text };
  } catch {
    return { text };
  }
}
