import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import childProcess from 'node:child_process';
import { createRequire } from 'node:module';

const projectRoot = process.env.EASEL_ROOT || fileURLToPath(new URL('../../../../../', import.meta.url));
const sourceRoot = path.join(projectRoot, 'skills/shared/workbench/neo-source');

export function countCharacters(text) {
  return [...text.replace(/[\r\n\u2028\u2029]/gu, '')].length;
}

export async function readPolicy(files = {}) {
  const writing = await fs.readFile(files.writing ?? path.join(sourceRoot, '规范/公众号贴图写作要求.md'), 'utf8');
  const image = await fs.readFile(files.images ?? path.join(sourceRoot, '规范/图片制作要求.md'), 'utf8');
  const titleLimit = writing.match(/\| 标题 \| 不超过 (\d+) 字/);
  const bodyLimit = writing.match(/\| 正文 \| 不超过 (\d+) 字/);
  const size = image.match(/\| 贴图 HTML 页 \| 默认 (\d+) × (\d+) 像素/);
  if (!titleLimit || !bodyLimit || !size) throw new Error('无法读取当前规范表格，须核对规范与工具接口；没有使用旧默认值。');
  return {
    titleLimit: Number(titleLimit[1]), bodyLimit: Number(bodyLimit[1]),
    fixedTechPulseTitle: writing.includes('本栏目标题固定为 `Tech Pulse｜科技脉搏 YYYY-MM-DD`'),
    width: Number(size[1]), height: Number(size[2]),
    writingVersion: writing.match(/version: "([^"]+)"/)[1],
    imageVersion: image.match(/version: "([^"]+)"/)[1],
  };
}

function inside(base, target) {
  const relative = path.relative(base, target);
  return relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

export async function itemPath(base, relative, { exists = true, nonEmpty = false } = {}) {
  if (typeof relative !== 'string' || !relative.trim() || path.isAbsolute(relative)) {
    throw new Error('材料路径须为相对草稿包的非空路径');
  }
  const target = path.resolve(base, relative);
  if (!inside(base, target)) throw new Error(`路径超出单篇目录：${relative}`);
  const realBase = await fs.realpath(base);
  let ancestor = target;
  while (true) {
    try {
      const realAncestor = await fs.realpath(ancestor);
      if (!inside(realBase, realAncestor)) throw new Error(`路径经链接超出单篇目录：${relative}`);
      break;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      const parent = path.dirname(ancestor);
      if (parent === ancestor) throw error;
      ancestor = parent;
    }
  }
  if (exists) {
    const stat = await fs.stat(target);
    if (!stat.isFile() || (nonEmpty && stat.size === 0)) throw new Error(`材料不是非空文件：${relative}`);
  }
  return target;
}

export function imageInfo(bytes) {
  if (bytes.length >= 24 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    return { format: 'png', width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  }
  if (bytes[0] === 0xff && bytes[1] === 0xd8) {
    let offset = 2;
    while (offset + 4 <= bytes.length) {
      if (bytes[offset] !== 0xff) break;
      const marker = bytes[offset + 1];
      if (marker === 0xd9 || marker === 0xda) break;
      if (marker === 0xff) { offset++; continue; }
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { offset += 2; continue; }
      const length = bytes.readUInt16BE(offset + 2);
      if (length < 2 || offset + 2 + length > bytes.length) break;
      if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker) && length >= 7) {
        return { format: 'jpeg', width: bytes.readUInt16BE(offset + 7), height: bytes.readUInt16BE(offset + 5) };
      }
      offset += 2 + length;
    }
  }
  throw new Error('图片不是可识别的 PNG/JPEG，或文件已损坏');
}

async function imageFile(base, relative) {
  const file = await itemPath(base, relative, { nonEmpty: true });
  const bytes = await fs.readFile(file);
  const info = imageInfo(bytes);
  const extension = path.extname(file).toLowerCase();
  if ((info.format === 'png' && extension !== '.png') || (info.format === 'jpeg' && !['.jpg', '.jpeg'].includes(extension))) {
    throw new Error(`扩展名与实际编码不一致：${relative}，实际 ${info.format}`);
  }
  return { file: relative, ...info, sha256: createHash('sha256').update(bytes).digest('hex') };
}

export async function loadDraft(manifestPath) {
  const absolute = path.resolve(manifestPath);
  const data = JSON.parse((await fs.readFile(absolute, 'utf8')).replace(/^\uFEFF/u, ''));
  if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error('草稿包须为 JSON 对象');
  return { absolute, base: path.dirname(absolute), data };
}

async function checkCreativeReview(draft, { requireOutputs }) {
  const { base, data } = draft;
  const reviewFile = await itemPath(base, data.creative_review, { nonEmpty: true });
  if (path.dirname(reviewFile) !== path.resolve(base)
    || path.dirname(await fs.realpath(reviewFile)) !== await fs.realpath(base)) {
    throw new Error('创作检查须与草稿包处于同一目录，避免成品相对路径错位');
  }
  const args = [path.join(projectRoot, 'skills/shared/workbench/neo-tools/内容工作流/creative_review.py'), 'check',
    '--file', reviewFile, '--stage', requireOutputs ? 'delivery' : 'plan',
    '--root', projectRoot, '--expected-title', String(data.title ?? ''), '--expected-format', 'poster'];
  for (const [key, flag] of [['work_id', '--expected-work-id'], ['version', '--expected-version']]) {
    if (Object.hasOwn(data, key)) {
      if (typeof data[key] !== 'string' || !data[key].trim()) throw new Error(`草稿包 ${key} 须为非空字符串，不能跳过作品/版本核对`);
      args.push(flag, data[key]);
    }
  }
  if (requireOutputs) {
    // With HTML pages, assets are source material. Imagegen bundles have no pages:
    // their assets are the actual final images that the assessment must cover.
    const files = [data.body_file, ...(data.pages?.length ? data.pages.map(page => page?.output) : (data.assets ?? []).map(asset => asset?.file))];
    for (const relative of new Set(files)) {
      await itemPath(base, relative, { nonEmpty: true });
      args.push('--expect-file', relative);
    }
  }
  const { error, stdout } = await new Promise(resolve => {
    childProcess.execFile(process.env.NEO_CONTENT_PYTHON || 'python', args, {
      encoding: 'utf8', timeout: 15000, maxBuffer: 1024 * 1024,
      windowsHide: true, shell: false,
      env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
    }, (error, stdout) => resolve({ error, stdout }));
  });
  let report;
  try { report = JSON.parse((stdout || '').replace(/^\uFEFF/u, '')); }
  catch { throw new Error(error ? `反馈检查程序未能完成（${error.code ?? 'error'}）` : '反馈检查程序未返回有效JSON'); }
  if (!report || Array.isArray(report) || typeof report.ok !== 'boolean' || !Array.isArray(report.errors)
    || report.errors.some(message => typeof message !== 'string')) throw new Error('反馈检查报告结构无效');
  if (report.basis !== 'assistant_assessment' || report.user_approval !== 'pending') {
    throw new Error('反馈检查只能记录助手判断，不能代替用户采纳');
  }
  if (error && (report.ok || error.killed || error.code !== 1)) throw new Error(`反馈检查程序未能完成（${error.code ?? 'error'}）`);
  if (report.ok && report.errors.length) throw new Error('反馈检查报告的状态与错误列表不一致');
  return { ...report, stage: requireOutputs ? 'delivery' : 'plan' };
}

export async function checkDraft(draft, { requireOutputs = true, requireCreativeReview = false } = {}) {
  const { base, data } = draft;
  const policyFiles = data.policy_files ? {
    writing: await itemPath(base, data.policy_files.writing, { nonEmpty: true }),
    images: await itemPath(base, data.policy_files.images, { nonEmpty: true }),
  } : {};
  const policy = await readPolicy(policyFiles);
  const errors = [];
  const warnings = ['机器检查不证明事实核验、实际试用或用户认可；交付前须目视检查图片及来源。'];
  const images = [];
  const capture = async (label, action) => {
    try { return await action(); } catch (error) { errors.push(`${label}：${error.message}`); return undefined; }
  };
  if (data.schema_version !== 1) errors.push('schema_version 须为 1');
  if (data.status !== '草稿' || data.review !== '待用户评审') errors.push('此工具只处理“草稿，待用户评审”，不得记录为已认可或已发布');
  if (!['news', 'tool', 'opinion', 'explainer', 'text'].includes(data.kind)) errors.push('kind 须为 news/tool/opinion/explainer/text');
  if (typeof data.title !== 'string' || !data.title.trim()) errors.push('title 须为非空标题');
  const titleCount = typeof data.title === 'string' ? countCharacters(data.title) : 0;
  const fixedTitle = policy.fixedTechPulseTitle && /^Tech Pulse｜科技脉搏 \d{4}-\d{2}-\d{2}$/u.test(data.title);
  if (!fixedTitle && titleCount > policy.titleLimit) errors.push(`标题 ${titleCount} 字符，超过 ${policy.titleLimit}`);
  let bodyCount;
  await capture('配文', async () => {
    const file = await itemPath(base, data.body_file, { nonEmpty: true });
    const body = (await fs.readFile(file, 'utf8')).replace(/^\uFEFF/u, '');
    if (!body.trim()) throw new Error('配文为空');
    bodyCount = countCharacters(body);
    if (bodyCount > policy.bodyLimit) throw new Error(`${bodyCount} 字符，超过 ${policy.bodyLimit}`);
  });
  const pages = Array.isArray(data.pages) ? data.pages : [];
  const assets = Array.isArray(data.assets) ? data.assets : [];
  if (!Array.isArray(data.pages) || !Array.isArray(data.assets)) errors.push('pages 和 assets 须为数组');
  if (!pages.length && !assets.length && data.kind !== 'text') errors.push('没有图片；纯文字内容须明确 kind=text');
  if (data.sources_file) await capture('来源记录', () => itemPath(base, data.sources_file, { nonEmpty: true }));
  else if (['news', 'tool'].includes(data.kind)) errors.push('新闻与工具稿须提供 sources_file');
  if (data.test?.required !== undefined && typeof data.test.required !== 'boolean') errors.push('test.required 须为布尔值');
  if (data.test?.required === true || data.test?.status === 'completed') {
    if (data.test?.status !== 'completed') errors.push('本篇主张需要的最小实测未完成，不能写成亲测稿');
    await capture('实测记录', () => itemPath(base, data.test?.record, { nonEmpty: true }));
    if (!Array.isArray(data.test?.outputs) || !data.test.outputs.length) errors.push('实测须引用至少一个真实输出文件或原始日志');
    else for (const file of data.test.outputs) await capture('实测输出', () => itemPath(base, file, { nonEmpty: true }));
  }
  for (const [index, asset] of assets.entries()) {
    await capture(`素材 ${index + 1}`, async () => {
      if (!asset || !['image', 'post-screenshot', 'run-screenshot'].includes(asset.kind)) throw new Error('未知素材类型');
      if (asset.kind === 'post-screenshot') {
        for (const key of ['source_url', 'author', 'published_at', 'captured_at', 'scope', 'context_file']) {
          if (typeof asset[key] !== 'string' || !asset[key].trim()) throw new Error(`原帖截图缺少 ${key}`);
        }
        if (!/^https?:\/\//u.test(asset.source_url)) throw new Error('原帖须记录 HTTP(S) 永久链接');
        await imageFile(base, asset.context_file);
        if (!data.sources_file) throw new Error('原帖截图须引用 sources_file');
      }
      if (asset.kind === 'run-screenshot') await itemPath(base, asset.record, { nonEmpty: true });
      images.push(await imageFile(base, asset.file));
    });
  }
  const outputs = new Set();
  for (const [index, entry] of pages.entries()) {
    await capture(`HTML 页 ${index + 1}`, async () => {
      if (!entry || typeof entry !== 'object') throw new Error('页面配置须为对象');
      const input = await itemPath(base, entry.html, { nonEmpty: true });
      const output = await itemPath(base, entry.output, { exists: false });
      if (path.extname(input).toLowerCase() !== '.html' || path.extname(output).toLowerCase() !== '.png') throw new Error('HTML 页输入须为 .html，输出须为 .png');
      if (outputs.has(output)) throw new Error('多页输出文件重复');
      outputs.add(output);
      const width = entry.width ?? policy.width, height = entry.height ?? policy.height;
      if (![width, height].every(n => Number.isInteger(n) && n > 0 && n <= 8192)) throw new Error('尺寸须为 1～8192 的整数像素');
      if (typeof entry.selector !== 'string' || !entry.selector.trim()) throw new Error('须指定唯一的页面 selector');
      if (requireOutputs) {
        const info = await imageFile(base, entry.output);
        if (info.width !== width || info.height !== height) throw new Error(`输出 ${info.width}×${info.height}，要求 ${width}×${height}`);
        images.push(info);
      }
    });
  }
  let creativeReview;
  let reviewScopeValid = true;
  if (requireCreativeReview) {
    for (const key of ['work_id', 'version']) {
      if (typeof data[key] !== 'string' || !data[key].trim()) {
        errors.push(`新制作须提供非空字符串 ${key}，不能省略作品/版本关联`);
        reviewScopeValid = false;
      }
    }
  }
  if (Object.hasOwn(data, 'creative_review') && reviewScopeValid) {
    creativeReview = await capture('创作反馈检查', () => checkCreativeReview(draft, { requireOutputs }));
    if (creativeReview && !creativeReview.ok) errors.push(...(creativeReview.errors.length ? creativeReview.errors : ['检查未通过但没有说明原因']).map(message => `创作反馈检查：${message}`));
  } else if (requireCreativeReview && !Object.hasOwn(data, 'creative_review')) {
    errors.push('新制作须提供 creative_review，不能缺少创作反馈检查记录');
  }
  return { ok: errors.length === 0, errors, warnings, counts: { title: titleCount, body: bodyCount }, policy, images,
    ...(creativeReview ? { creative_review: creativeReview } : {}) };
}

export async function renderDraft(draft, { requireCreativeReview = false } = {}) {
  const preflight = await checkDraft(draft, { requireOutputs: false, requireCreativeReview });
  if (!preflight.ok) return { ...preflight, rendered: [] };
  const require = createRequire(path.join(projectRoot, '.runtime/neo-poster-tools/package.json'));
  const { chromium } = require('playwright');
  const browser = await chromium.launch({ headless: true }).catch(error => {
    throw new Error(`浏览器启动失败，请在工具目录执行 npm run setup:browser。${error.message}`);
  });
  const rendered = [];
  const errors = [];
  try {
    // Stage the whole batch before writing; a later failed page leaves no partial deliverables.
    const staged = [];
    for (const entry of draft.data.pages) {
      const output = await itemPath(draft.base, entry.output, { exists: false });
      try { await fs.access(output); throw new Error(`输出已存在，请使用新版本文件名：${entry.output}`); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      const width = entry.width ?? preflight.policy.width, height = entry.height ?? preflight.policy.height;
      const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
      const failures = [];
      const localResources = new Set();
      page.on('request', request => { if (request.url().startsWith('file:')) localResources.add(request.url()); });
      page.on('pageerror', error => failures.push(`脚本错误：${error.message}`));
      page.on('requestfailed', request => failures.push(`素材加载失败：${request.url()}`));
      page.on('response', response => { if (response.status() >= 400) failures.push(`素材 HTTP ${response.status()}：${response.url()}`); });
      try {
        // Rendering is local-only; source-site screenshots must use the in-app browser.
        await page.route(/^https?:\/\//u, route => route.abort('blockedbyclient'));
        await page.goto(pathToFileURL(await itemPath(draft.base, entry.html)).href, { waitUntil: 'load', timeout: 30000 });
        await page.evaluate(async () => {
          await document.fonts.ready;
          await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
        });
        for (const resource of localResources) {
          await itemPath(draft.base, path.relative(draft.base, fileURLToPath(resource)), { nonEmpty: true });
        }
        const target = page.locator(entry.selector);
        if (await target.count() !== 1) throw new Error('selector 必须且只能匹配一页');
        const inspection = await target.evaluate((element, expected) => {
          const root = element.getBoundingClientRect();
          const issues = [];
          if (Math.abs(root.width - expected.width) > 0.5 || Math.abs(root.height - expected.height) > 0.5) issues.push(`页面实际 ${root.width}×${root.height}，要求 ${expected.width}×${expected.height}`);
          if (element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1) issues.push('页面内容溢出');
          for (const node of element.querySelectorAll('*')) {
            const rect = node.getBoundingClientRect();
            const css = getComputedStyle(node);
            if (!rect.width || !rect.height || css.display === 'none' || css.visibility === 'hidden') continue;
            if (rect.left < root.left - 1 || rect.top < root.top - 1 || rect.right > root.right + 1 || rect.bottom > root.bottom + 1) issues.push(`元素超出页面：${node.tagName}`);
            const row = node.closest('[data-layout-row]');
            if (row && row !== node) {
              const boundary = row.getBoundingClientRect();
              if (rect.top < boundary.top - 1 || rect.bottom > boundary.bottom + 1) issues.push('条目内容超出行边界');
            }
            if ((css.overflowX === 'hidden' || css.overflowX === 'clip') && node.scrollWidth > node.clientWidth + 1) issues.push(`元素横向截断：${node.tagName}`);
            if ((css.overflowY === 'hidden' || css.overflowY === 'clip') && node.scrollHeight > node.clientHeight + 1) issues.push(`元素纵向截断：${node.tagName}`);
          }
          const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            const node = walker.currentNode;
            if (!node.textContent.trim() || ['SCRIPT', 'STYLE'].includes(node.parentElement?.tagName)) continue;
            const css = getComputedStyle(node.parentElement);
            if (css.display === 'none' || css.visibility === 'hidden') continue;
            const range = document.createRange(); range.selectNodeContents(node);
            for (const rect of range.getClientRects()) {
              if (rect.width && rect.height && (rect.left < root.left - 1 || rect.top < root.top - 1 || rect.right > root.right + 1 || rect.bottom > root.bottom + 1)) issues.push('文字超出页面');
            }
          }
          for (const image of element.querySelectorAll('img')) if (!image.complete || !image.naturalWidth) issues.push(`图片未加载：${image.getAttribute('src')}`);
          return [...new Set(issues)];
        }, { width, height });
        if (failures.length || inspection.length) throw new Error([...failures, ...inspection].join('；'));
        const bytes = await target.screenshot({ type: 'png', animations: 'disabled', timeout: 30000 });
        const info = imageInfo(bytes);
        if (info.width !== width || info.height !== height) throw new Error('截图实际尺寸不符');
        staged.push({ output, bytes, relative: entry.output, info });
      } finally { await page.close(); }
    }
    const written = [];
    try {
      for (const item of staged) {
        await fs.mkdir(path.dirname(item.output), { recursive: true });
        await fs.writeFile(item.output, item.bytes, { flag: 'wx' });
        written.push(item.output);
        rendered.push({ file: item.relative, ...item.info });
      }
    } catch (error) {
      for (const file of written) await fs.unlink(file);
      rendered.length = 0;
      throw error;
    }
  } catch (error) { errors.push(error.message); }
  finally { await browser.close(); }
  return { ...preflight, ok: errors.length === 0, errors, rendered };
}
