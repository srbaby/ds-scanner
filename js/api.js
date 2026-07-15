/**
 * GitHub Gist transport.  This module deliberately knows nothing about DOM
 * state or investment rules: callers provide file names and JSON/text values.
 */
export class GistApiError extends Error {
  constructor(message, { status = 0, code = 'network' } = {}) {
    super(message);
    this.name = 'GistApiError';
    this.status = status;
    this.code = code;
  }
}

export class GistClient {
  constructor({ token, gistId, fetchImpl = fetch }) {
    this.token = token;
    this.gistId = gistId;
    this.fetch = fetchImpl;
  }

  headers(extra = {}) {
    return { Authorization: `token ${this.token}`, ...extra };
  }

  async index({ cache = 'no-store' } = {}) {
    const response = await this.fetch(`https://api.github.com/gists/${this.gistId}`, {
      headers: this.headers(), cache,
    });
    if (!response.ok) throw new GistApiError(`HTTP ${response.status}`, { status: response.status, code: 'index' });
    return response.json();
  }

  async readFile(gist, filename) {
    const file = gist?.files?.[filename];
    if (!file) return null;
    // The index includes small file content. Large Gists mark content as
    // truncated, in which case raw_url is the only complete representation.
    if (!file.truncated && typeof file.content === 'string') return file.content;
    const response = await this.fetch(file.raw_url, { headers: this.headers(), cache: 'no-store' });
    if (!response.ok) throw new GistApiError(`${filename}: HTTP ${response.status}`, { status: response.status, code: 'read_file' });
    return response.text();
  }

  async readFiles(gist, filenames) {
    const entries = await Promise.all(filenames.map(async filename => [filename, await this.readFile(gist, filename)]));
    return Object.fromEntries(entries);
  }

  async patchFiles(files) {
    const payload = Object.fromEntries(Object.entries(files).map(([name, value]) => [
      name,
      { content: typeof value === 'string' ? value : JSON.stringify(value, null, 2) },
    ]));
    const response = await this.fetch(`https://api.github.com/gists/${this.gistId}`, {
      method: 'PATCH',
      headers: this.headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ files: payload }),
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new GistApiError(`HTTP ${response.status}${detail ? ` ${detail.slice(0, 200)}` : ''}`, { status: response.status, code: 'patch' });
    }
    return response.json();
  }
}

export function parseJson(raw, fallback = null) {
  if (!raw) return fallback;
  try { return JSON.parse(raw); } catch { return fallback; }
}

export function parseJsonl(raw = '') {
  return String(raw).split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    .map(line => parseJson(line)).filter(Boolean);
}
