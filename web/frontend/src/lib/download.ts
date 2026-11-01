/** One byte-transfer boundary for every file type and every download surface. */
type DownloadResolver = (url: string, name: string) => Promise<string>;
let resolver: DownloadResolver | undefined;
export function bindDownloadResolver(value: DownloadResolver): () => void {
  resolver=value;return ()=>{if(resolver===value)resolver=undefined};
}
export class DownloadManager {
  private pending = new Map<string, Promise<void>>();
  private readonly options: {
    fetcher?: typeof fetch;
    origin?: () => string;
    save?: (blob: Blob, name: string) => void;
    limit?: number;
  };
  constructor(options: DownloadManager['options'] = {}) { this.options=options; }

  download(href: string, filename: string): Promise<void> {
    const origin = this.options.origin?.() ?? location.origin;
    let url: URL;
    try { url = new URL(href, origin); } catch { return Promise.reject(Error('下载地址无效')); }
    if (url.origin !== origin || !/^https?:$/.test(url.protocol) || !/\/(api|media)\//.test(url.pathname)
        || url.username || url.password || /[\\\x00-\x1f]/.test(href)) {
      return Promise.reject(Error('下载地址不受支持'));
    }
    // Re-read signed images through the owner's current session. Long-open pages
    // can contain expired image capabilities; no capability refresh is necessary.
    const image = /^\/media\/images\/([A-Za-z0-9_-]+)\/[^/]+$/.exec(url.pathname);
    if (image) url = new URL('/api/files/' + image[1] + '?download=1', origin);
    url.hash = '';
    const name = filename.replace(/[\\/\x00-\x1f]/g, '_') || 'download';
    const key = url.href + '\0' + name;
    const existing = this.pending.get(key);
    if (existing) return existing;
    const operation = this.transfer(url.href, name).finally(() => this.pending.delete(key));
    this.pending.set(key, operation);
    return operation;
  }

  private async transfer(url: string, name: string): Promise<void> {
    if (resolver) {
      const signed=new URL(await resolver(url,name),this.options.origin?.()??location.origin);
      if(signed.origin!==new URL(url).origin||signed.pathname!=='/media/downloads')throw Error('下载凭证无效');
      const link=document.createElement('a');link.href=signed.href;link.download=name;
      document.body.appendChild(link);try{link.click()}finally{link.remove()}
      return;
    }
    const response = await (this.options.fetcher ?? fetch)(url, {
      credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    });
    if (!response.ok) throw Error(response.status === 401 ? '登录已失效，请重新登录后下载' : '下载失败（' + response.status + '），请重试');
    const limit = this.options.limit ?? 512 * 1024 * 1024;
    if (Number(response.headers.get('content-length')) > limit) {
      await response.body?.cancel(); throw Error('文件过大，请在电脑端处理');
    }
    const parts: Uint8Array<ArrayBuffer>[] = [];
    let size = 0;
    const reader = response.body?.getReader();
    if (!reader) throw Error('下载内容为空，请重试');
    try {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        size += next.value.byteLength;
        if (size > limit) { await reader.cancel(); throw Error('文件过大，请在电脑端处理'); }
        parts.push(new Uint8Array(next.value));
      }
    } finally { reader.releaseLock(); }
    const blob = new Blob(parts, {type: response.headers.get('content-type') || 'application/octet-stream'});
    (this.options.save ?? saveBlob)(blob, name);
  }
}

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url; link.download = name;
    document.body.appendChild(link);
    try { link.click(); } finally { link.remove(); }
  } finally {
    // Native savers can consume the Blob after the click handler has returned.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}

export const downloads = new DownloadManager();
