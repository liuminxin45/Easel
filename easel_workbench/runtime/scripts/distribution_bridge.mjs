/**
 * One-request, loopback-only WechatSync bridge. No CLI program is executed.
 *
 * Runtime dependency: @wechatsync/cli 1.1.0, author "fun", npm license MIT.
 * Source: https://github.com/wechatsync/Wechatsync (repository LICENSE currently
 * says GPL-3.0; this wrapper does not copy or relicense that repository's code).
 * The hash-pinned installed ExtensionBridge is loaded in memory with vm. The
 * upstream package files and their license metadata are left intact. Local
 * overrides disable upstream's public listeners, secondary forwarding, retries,
 * takeover, unauthenticated HTTP, unsolicited response logging and CLI startup.
 *
 * stdin: one JSON object, protocol_version 1; credentials ONLY in stdin.
 * stdout: exactly one sanitized JSON object; no raw upstream errors or sessions.
 * getPlatforms is account-independent discovery. It never creates a connection
 * or turns discovered login metadata into publishing or verification authority.
 */
import {createHash, timingSafeEqual} from 'node:crypto';
import {readFile, realpath, stat} from 'node:fs/promises';
import http from 'node:http';
import {createRequire} from 'node:module';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

export const CLI_SHA256 = 'b792a30402f070b536c3dcc3090ff7ab483d4e77357ce893e564939224c7008b';
export const EXTENSION_MANIFEST_SHA256 = '4dbf8ac30804b8c192af895fa2069a629de0505954d010f7b080279d01bcb40e';
export const EXTENSION_BACKGROUND_SHA256 = '1c45a07a8323cdc2a92c38349381e1d24d560b19c0b59a2567479ab6661de4b8';
// This is the same immutable catalog used by the service and both UIs. Platform
// discovery never adds entries or grants capabilities to this execution map.
const catalog = JSON.parse(await readFile(new URL('../packages/core/src/distribution-platforms.json', import.meta.url), 'utf8'));
if (catalog.schema_version !== 1 || !Array.isArray(catalog.platforms) || !catalog.providers || typeof catalog.providers !== 'object') throw Error('invalid_distribution_catalog');
const providerEntries = catalog.platforms.map(platform => {
  if (!platform || typeof platform.id !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(platform.id)
      || typeof platform.provider !== 'string' || !Object.hasOwn(catalog.providers, platform.provider)
      || typeof platform.draft !== 'boolean' || !Array.isArray(platform.content_kinds) || platform.content_kinds.length !== 1
      || typeof platform.content_kinds[0] !== 'string' || platform.draft && platform.content_kinds[0] !== 'article') throw Error('invalid_distribution_catalog');
  return [platform.id, Object.freeze({id: platform.provider, draft: platform.draft,
    content_kind: platform.content_kinds[0], ...(typeof platform.reason === 'string' ? {reason: platform.reason} : {})})];
});
if (new Set(providerEntries.map(([id]) => id)).size !== providerEntries.length) throw Error('invalid_distribution_catalog');
export const PROVIDERS = Object.freeze(Object.fromEntries(providerEntries));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const allowedOps = new Set(['probe', 'getPlatforms', 'sync', 'readback', 'reconcile']);
const noCapabilities = () => ({draft: false, publish: false, verify: false});

export class BridgeFailure extends Error {
  constructor(code, phase = 'pre_send') {super(code); this.code = code; this.phase = phase;}
}

export function publicUrl(value) {
  if (typeof value !== 'string' || value.length > 4000 || /[\\\s\x00-\x1f]/.test(value)) return undefined;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port || !url.hostname.includes('.') || /^(localhost|127\.|10\.|192\.168\.|0\.)/.test(url.hostname) || url.hostname.endsWith('.local')) return undefined;
    // Editing links may contain provider/session tokens; no query or fragment
    // is ever emitted. The separately retained postId is the opaque draft ID.
    url.search = ''; url.hash = '';
    return url.toString();
  } catch {return undefined;}
}

function safeString(value, token = '', limit = 1000) {
  if (typeof value !== 'string') return undefined;
  // Redact before truncation so a credential longer than a display field cannot
  // leak a prefix. Also remove the URL-encoded form before JSON serialization.
  let result = value;
  if (token) {
    result = result.split(token).join('[redacted]');
    result = result.split(encodeURIComponent(token)).join('[redacted]');
  }
  return result.replace(/[\x00-\x1f\x7f]/g, '').slice(0, limit);
}

function configuration(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || input.protocol_version !== 1 || !allowedOps.has(input.op)) throw new BridgeFailure('invalid_protocol');
  if (input.op !== 'getPlatforms' && (!input.connection || typeof input.connection.account !== 'string' || !input.connection.account.trim() || input.connection.account.length > 200 || typeof input.connection.platform !== 'string' || !Object.hasOwn(PROVIDERS, input.connection.platform))) throw new BridgeFailure('invalid_connection');
  const settings = input.settings || {};
  const token = settings.WECHATSYNC_TOKEN;
  if (typeof token !== 'string' || token.length < 16 || token.length > 4096 || /[\x00-\x20\x7f]/.test(token)) throw new BridgeFailure('token_required');
  let endpoint;
  try {endpoint = new URL(settings.bridge_url || 'ws://127.0.0.1:9527');} catch {throw new BridgeFailure('invalid_loopback_endpoint');}
  if (endpoint.protocol !== 'ws:' || endpoint.hostname !== '127.0.0.1' || endpoint.username || endpoint.password || endpoint.search || endpoint.hash || endpoint.pathname !== '/') throw new BridgeFailure('invalid_loopback_endpoint');
  const port = Number(endpoint.port || 80);
  if (!Number.isInteger(port) || port < 1024 || port > 65534) throw new BridgeFailure('invalid_loopback_endpoint');
  const toolRoot = path.resolve(input.tool_root || path.join(os.homedir(), '.codex', 'tools', 'wechatsync'));
  const extensionPath = path.join(toolRoot, 'extension-2.0.9');
  // Supplied only by the protected installer receipt after reading the actual
  // unpacked extension ID. Chromium path guesses are not identity evidence.
  const extensionId = settings.extension_id;
  if (typeof extensionId !== 'string' || !/^[a-p]{32}$/.test(extensionId)) throw new BridgeFailure('actual_extension_origin_required');
  const timeout = settings.timeout_ms === undefined ? 30000 : settings.timeout_ms;
  if (!Number.isInteger(timeout) || timeout < 100 || timeout > 360000) throw new BridgeFailure('invalid_timeout');
  return {token, port, toolRoot, extensionPath, extensionId, timeout};
}

export async function loadOfficialBridge(toolRoot) {
  const packagePath = path.join(toolRoot, 'node_modules', '@wechatsync', 'cli', 'package.json');
  let metadata, source, manifest, background;
  try {
    metadata = JSON.parse(await readFile(packagePath, 'utf8'));
    source = await readFile(path.join(path.dirname(packagePath), 'dist', 'index.js'));
    manifest = await readFile(path.join(toolRoot, 'extension-2.0.9', 'manifest.json'));
    background = await readFile(path.join(toolRoot, 'extension-2.0.9', 'assets', 'index.ts-Bw-475TG.js'));
  } catch {throw new BridgeFailure('official_tool_not_installed');}
  if (metadata.name !== '@wechatsync/cli' || metadata.version !== '1.1.0' || sha(source) !== CLI_SHA256 || sha(manifest) !== EXTENSION_MANIFEST_SHA256 || sha(background) !== EXTENSION_BACKGROUND_SHA256) throw new BridgeFailure('official_source_hash_mismatch');
  const bundle = source.toString('utf8');
  const begin = bundle.indexOf('var ExtensionBridge = class {');
  const end = bundle.indexOf('\n// src/index.ts\nvar WS_PORT', begin);
  if (begin < 0 || end < 0) throw new BridgeFailure('official_bridge_export_missing');
  const requireTool = createRequire(packagePath);
  const ws = requireTool('ws');
  const context = vm.createContext({import_ws: ws, import_http: {default: http}, WS_OPEN: ws.WebSocket.OPEN, process: {env: Object.freeze({})}, Buffer,
    console: Object.freeze({log() {}, error() {}, warn() {}}), setTimeout, clearTimeout}, {codeGeneration: {strings: false, wasm: false}});
  const Base = vm.runInContext(bundle.slice(begin, end) + '\nExtensionBridge;', context, {timeout: 1000, filename: '@wechatsync/cli@1.1.0:ExtensionBridge'});
  return {Base, ws, source: {package: '@wechatsync/cli', version: '1.1.0', sha256: CLI_SHA256, extension_version: '2.0.9', background_sha256: EXTENSION_BACKGROUND_SHA256}};
}

export function restrictedBridge({Base, ws}, config) {
  return new class LoopbackBridge extends Base {
    constructor() {super(config.port, {silent: true}); this.token = config.token; this.requestTimeout = config.timeout; this.waiters = new Set();}
    async start() {await this.startServer(); this.isServerMode = true;}
    async startServer() {
      await new Promise((resolve, reject) => {
        this.wss = new ws.WebSocketServer({host: '127.0.0.1', port: this.port, maxPayload: 2 * 1024 * 1024, perMessageDeflate: false,
          verifyClient: (info, done) => {
            const trustedOrigin = info.origin === 'chrome-extension://' + config.extensionId;
            const localPeer = info.req.socket.remoteAddress === '127.0.0.1';
            const trustedHost = ['127.0.0.1:' + this.port, 'localhost:' + this.port].includes(info.req.headers.host);
            done(Boolean(trustedOrigin && localPeer && trustedHost && !this.client), 403, 'Forbidden');
          }});
        this.wss.once('error', reject);
        this.wss.once('listening', resolve);
        this.wss.on('connection', socket => {
          this.client = socket;
          for (const resolveWait of this.waiters) resolveWait();
          this.waiters.clear();
          socket.on('message', value => this.handleMessage(value.toString()));
          socket.on('error', () => {});
          socket.on('close', () => {
            if (this.client === socket) this.client = null;
            for (const pending of this.pendingRequests.values()) {clearTimeout(pending.timeout); pending.reject(new BridgeFailure('extension_disconnected', 'sent'));}
            this.pendingRequests.clear();
          });
        });
      });
      try {await this.startHttpApi();} catch (error) {await this.stop(); throw error;}
    }
    async startHttpApi() {
      await new Promise((resolve, reject) => {
        this.httpServer = http.createServer((request, response) => {
          const candidate = Buffer.from(request.headers.authorization || '');
          const expected = Buffer.from('Bearer ' + this.token);
          const host = request.headers.host;
          const valid = candidate.length === expected.length && timingSafeEqual(candidate, expected);
          if (!valid || request.headers.origin || !['127.0.0.1:' + (this.port + 1), 'localhost:' + (this.port + 1)].includes(host)) {response.writeHead(403); response.end(); return;}
          if (request.method !== 'GET' || request.url !== '/status') {response.writeHead(404); response.end(); return;}
          response.writeHead(200, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
          response.end(JSON.stringify({connected: this.isConnected(), mode: 'isolated-loopback'}));
        });
        this.httpServer.maxHeadersCount = 20;
        this.httpServer.headersTimeout = 3000;
        this.httpServer.requestTimeout = 3000;
        this.httpServer.once('error', reject);
        this.httpServer.listen(this.port + 1, '127.0.0.1', resolve);
      });
    }
    waitForConnection(timeout = config.timeout) {
      if (this.client?.readyState === ws.WebSocket.OPEN) return Promise.resolve();
      return new Promise((resolve, reject) => {
        const complete = () => {clearTimeout(timer); this.waiters.delete(complete); resolve();};
        const timer = setTimeout(() => {this.waiters.delete(complete); reject(new BridgeFailure('extension_not_connected'));}, timeout);
        this.waiters.add(complete);
      });
    }
    request(method, params) {
      // Bypass upstream secondary forwarding/retry, even if a port is busy.
      return this.requestInternal(method, params);
    }
    handleMessage(value) {
      let message;
      try {message = JSON.parse(value);} catch {return;}
      const pending = this.pendingRequests.get(message?.id);
      if (!pending) return;
      clearTimeout(pending.timeout); this.pendingRequests.delete(message.id);
      if (message.error) pending.reject(new BridgeFailure('extension_request_rejected', 'sent'));
      else pending.resolve(message.result);
    }
    async stop() {
      for (const pending of this.pendingRequests.values()) {clearTimeout(pending.timeout); pending.reject(new BridgeFailure('bridge_stopped', 'sent'));}
      this.pendingRequests.clear();
      for (const socket of this.wss?.clients || []) socket.terminate();
      const webSocket = this.wss, localHttp = this.httpServer;
      this.wss = null; this.httpServer = null; this.client = null;
      await Promise.all([webSocket ? new Promise(resolve => webSocket.close(() => resolve())) : Promise.resolve(), localHttp ? new Promise(resolve => {localHttp.closeAllConnections(); localHttp.close(() => resolve());}) : Promise.resolve()]);
    }
  }();
}

function accountResult(auth, expected) {
  // Legacy connections bind the upstream username. New WeChat connections can
  // bind checkAuth.userId even when the extension did not parse a nickname.
  // Never substitute a platform name or silently rebind an existing account.
  const matched = auth?.isAuthenticated === true && [auth.username, auth.userId, auth.account]
    .some(value => typeof value === 'string' && Boolean(value.trim()) && value === expected);
  return {actual: matched ? expected : '', matched};
}

function remoteId(value) {
  const id = typeof value === 'number' && Number.isSafeInteger(value) ? String(value) : value;
  return typeof id === 'string' && /^[A-Za-z0-9_-]{1,256}$/.test(id) ? id : undefined;
}

async function preparedAssets(input) {
  const assets = input.assets || [];
  const manifest = input.revision?.asset_manifest || [];
  if (!Array.isArray(assets) || !Array.isArray(manifest) || assets.length !== manifest.length || assets.length > 12) throw new BridgeFailure('asset_manifest_mismatch');
  const result = [];
  for (let index = 0; index < manifest.length; index++) {
    const asset = assets[index], expected = manifest[index];
    if (!asset || asset.id !== expected.id || asset.sha256 !== expected.sha256 || asset.mime !== expected.mime || asset.size !== expected.size || typeof asset.path !== 'string' || !path.isAbsolute(asset.path) || !/^image\/(png|jpeg|webp|gif)$/.test(asset.mime)) throw new BridgeFailure('asset_manifest_mismatch');
    const canonical = await realpath(asset.path);
    // This subprocess reads only exact server-resolved snapshot paths, never
    // Markdown file references, credential paths, URLs or directory traversals.
    if (path.resolve(asset.path) !== canonical) throw new BridgeFailure('asset_path_not_canonical');
    const info = await stat(canonical);
    if (!info.isFile() || info.size !== asset.size || info.size > 32 * 1024 * 1024) throw new BridgeFailure('asset_size_mismatch');
    const bytes = await readFile(canonical);
    if (sha(bytes) !== expected.sha256) throw new BridgeFailure('asset_hash_mismatch');
    result.push({...asset, bytes});
  }
  return result;
}

function responseBase() {return {protocol_version: 1, ok: false, code_verified: false, account_verified: false, verified: false, capabilities: noCapabilities(), phase: 'pre_send'};}

function discoveryAccounts(platforms, token) {
  if (!Array.isArray(platforms)) throw new BridgeFailure('invalid_platform_response');
  const accounts = [];
  for (const platform of platforms.slice(0, 80)) {
    if (!platform || typeof platform !== 'object' || Array.isArray(platform)) continue;
    const id = safeString(platform.id, token, 80);
    if (!id || !/^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(id)) continue;
    // Do not forward provider errors, edit URLs, cookie/session fields, avatars,
    // nested payloads or self-reported publishing capabilities from discovery.
    accounts.push({platform: id, name: safeString(platform.name, token, 200) || id,
      account: safeString(platform.username, token, 200) || '', authenticated: platform.isAuthenticated === true});
  }
  return accounts;
}

export async function execute(input, dependencies = {}) {
  let bridge, config, sent = false;
  const result = responseBase();
  try {
    config = configuration(input);
    if (input.op === 'sync' && (input.delivery?.action !== 'draft' || input.delivery?.pilot !== true)) throw new BridgeFailure('explicit_draft_pilot_required');
    const provider = input.op === 'getPlatforms' ? undefined : PROVIDERS[input.connection.platform];
    if (input.op === 'sync' && (!provider.draft || input.revision?.content_kind !== provider.content_kind)) throw new BridgeFailure(provider.reason || 'unsupported_content_kind');
    const official = await (dependencies.loadBridge || loadOfficialBridge)(config.toolRoot);
    result.code_verified = true;
    result.evidence = [{kind: 'local_code', ...official.source}];
    result.extension_id = config.extensionId;
    // Official extension 2.0.9 has no readback/getDraft/getArticle RPC. Local
    // sync history or a successful write response cannot verify remote bytes.
    if (input.op === 'readback' || input.op === 'reconcile') return {...result, reason: 'official_connector_has_no_remote_readback', remote_state: 'unknown'};
    const assets = input.op === 'sync' ? await preparedAssets(input) : [];
    if (input.op === 'sync' && (typeof input.revision?.title !== 'string' || !input.revision.title.trim() || typeof input.revision?.body !== 'string' || !input.revision.body.trim() || !/^[a-f0-9]{64}$/.test(input.revision?.hash || '') || input.revision.account !== input.connection.account || input.revision.connection_id !== input.connection.id)) throw new BridgeFailure('revision_binding_mismatch');
    bridge = (dependencies.bridgeFactory || restrictedBridge)(official, config);
    await bridge.start();
    await bridge.waitForConnection(config.timeout);
    if (input.op === 'getPlatforms') {
      const platforms = await bridge.request('listPlatforms', {forceRefresh: true});
      return {...result, ok: true, accounts: discoveryAccounts(platforms, config.token)};
    }
    const auth = await bridge.request('checkAuth', {platform: provider.id});
    const account = accountResult(auth, input.connection.account);
    result.account_verified = account.matched;
    if (account.actual) result.account = safeString(account.actual, config.token, 200);
    result.capabilities.draft = Boolean(provider.draft && account.matched);
    result.evidence.push({kind: 'extension_account_check', provider: provider.id, account: result.account || '', matched: account.matched});
    if (input.op === 'probe') return {...result, ok: account.matched, reason: !account.matched ? 'exact_account_not_authenticated' : provider.reason || 'draft_pilot_only_no_remote_readback'};
    if (!account.matched) throw new BridgeFailure('exact_account_not_authenticated');
    let markdown = input.revision.body;
    for (const asset of assets) {
      sent = true;
      const uploaded = await bridge.uploadImageChunked(asset.bytes.toString('base64'), asset.mime, provider.id);
      const imageUrl = uploaded?.url;
      if (!publicUrl(imageUrl) || [...new URL(imageUrl).searchParams.keys()].some(key => /token|secret|session|auth|cookie|password|^key$|^code$/i.test(key)) || new URL(imageUrl).hash) throw new BridgeFailure('uploaded_image_url_not_safe', 'sent');
      markdown += '\n\n![](' + imageUrl + ')';
    }
    sent = true;
    const response = await bridge.request('syncArticle', {platforms: [provider.id], article: {title: input.revision.title, markdown}, draftOnly: true});
    const receipts = response?.results;
    if (!Array.isArray(receipts) || receipts.length !== 1 || receipts[0].platform !== provider.id) throw new BridgeFailure('remote_receipt_mismatch', 'sent');
    const receipt = receipts[0];
    const safeId = remoteId(receipt.postId), safeLink = publicUrl(receipt.postUrl);
    return {...result, ok: receipt.success === true, phase: 'sent', remote_state: 'unknown', verified: false,
      ...(safeId ? {remote_id: safeId} : {}), ...(safeLink ? {safe_url: safeLink} : {}),
      reason: receipt.success === true ? 'draft_write_receipt_requires_independent_readback' : 'draft_write_rejected_without_independent_readback',
      evidence: [...result.evidence, {kind: 'connector_write_receipt', provider: provider.id, success: receipt.success === true, draft_only_reported: receipt.draftOnly === true, readback: false}]};
  } catch (error) {
    const code = error instanceof BridgeFailure ? error.code : error?.code === 'EADDRINUSE' ? 'loopback_port_in_use_no_forwarding' : error?.message?.startsWith('Request timeout:') ? 'extension_request_timeout' : 'bridge_operation_failed';
    return {...result, ok: false, verified: false, remote_state: sent ? 'unknown' : 'failed', phase: sent ? 'sent' : 'pre_send', error_code: code, reason: code};
  } finally {
    if (bridge) await bridge.stop().catch(() => {});
    if (config) config.token = '';
  }
}

async function stdinRequest() {
  const chunks = []; let size = 0;
  for await (const chunk of process.stdin) {size += chunk.length; if (size > 2 * 1024 * 1024) throw new BridgeFailure('stdin_request_too_large'); chunks.push(chunk);}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

async function main() {
  let input, result;
  try {input = await stdinRequest(); result = await execute(input);} catch {result = {...responseBase(), remote_state: 'failed', error_code: 'invalid_stdin_json', reason: 'invalid_stdin_json'};}
  // A final literal-token scrub is defense in depth even for adapter usernames.
  let serialized = JSON.stringify(result);
  const token = input?.settings?.WECHATSYNC_TOKEN;
  if (typeof token === 'string' && token) serialized = serialized.split(token).join('[redacted]');
  process.stdout.write(serialized + '\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
