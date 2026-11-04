import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
const root = process.env.EASEL_ROOT || fileURLToPath(new URL('../../../../../', import.meta.url));
const require = createRequire(path.join(root, '.runtime/neo-poster-tools/package.json'));
const { chromium } = require('playwright');
const [file, output, ...options] = process.argv.slice(2);
const errors = [], previews = [];
let creativeReview;
const required = options.includes('--require-creative-review');
const manifestFlag = options.indexOf('--article-manifest');
const manifest = manifestFlag >= 0 ? options[manifestFlag + 1] : null;
const unknown = options.filter((value, index) => value !== '--require-creative-review' && value !== '--article-manifest' && !(manifestFlag >= 0 && index === manifestFlag + 1));
if (unknown.length || (manifestFlag >= 0 && (!manifest || manifest.startsWith('--')))) errors.push('文章创作检查参数无效');
if (required && !manifest) errors.push('新文章交付检查须提供 --article-manifest');
let browser;
try {
  browser = await chromium.launch({ headless: true });
  await fs.mkdir(output, { recursive: true });
  for (const width of [640, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1200 }, deviceScaleFactor: 1 });
    page.on('pageerror', error => errors.push(error.message));
    await page.route(/^https?:\/\//u, route => route.abort());
    await page.goto(pathToFileURL(path.resolve(file)).href, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    const report = await page.evaluate(() => {
      const article = document.querySelector('#article');
      const errors = [];
      if (!article || !article.textContent.trim()) errors.push('正文复制区缺失');
      if (document.documentElement.scrollWidth > innerWidth + 1) errors.push('移动端横向溢出');
      for (const img of document.images) if (!img.complete || !img.naturalWidth) errors.push('图片未加载');
      if (article && [...article.querySelectorAll('a')].some(a => !/^https?:\/\//.test(a.href))) errors.push('来源链接无效');
      if (article?.querySelector('h1,.tools,button')) errors.push('复制区混入标题或操作控件');
      return { errors, height: Math.ceil(document.documentElement.scrollHeight) };
    });
    errors.push(...report.errors.map(error => `${width}px: ${error}`));
    // 按视口连续截图，便于实际逐屏查看；不仿造任何第三方页面。
    for (let offset = 0, index = 1; offset < report.height; offset += 1200, index++) {
      await page.evaluate(y => scrollTo(0, y), offset);
      const target = path.join(output, `${width}-${String(index).padStart(2, '0')}.png`);
      await page.screenshot({ path: target, fullPage: false });
      previews.push(path.relative(path.dirname(file), target).split(path.sep).join('/'));
    }
    await page.close();
  }
} catch (error) { errors.push(error.message); }
finally { await browser?.close(); }
if (manifest && !errors.length) {
  try {
    const delivery = JSON.parse((await fs.readFile(manifest, 'utf8')).replace(/^\uFEFF/u, ''));
    if (!delivery.html_file || await fs.realpath(path.resolve(path.dirname(manifest), delivery.html_file)) !== await fs.realpath(file)) throw new Error('创作检查所绑定的HTML与本次检查文件不一致');
    const args = [path.join(root, 'skills/shared/workbench/neo-tools/内容工作流/creative_review.py'), 'check', '--article-manifest', path.resolve(manifest), '--root', root];
    let stdout, executionError;
    try { ({ stdout } = await promisify(execFile)(process.env.NEO_CONTENT_PYTHON || 'python', args, { encoding: 'utf8', timeout: 15000, windowsHide: true, shell: false, env: { ...process.env, PYTHONUTF8: '1' } })); }
    catch (error) { stdout = error.stdout; executionError = error; }
    creativeReview = JSON.parse(stdout || 'null');
    if (!creativeReview || typeof creativeReview.ok !== 'boolean' || !Array.isArray(creativeReview.errors) || creativeReview.errors.some(message => typeof message !== 'string') || creativeReview.basis !== 'assistant_assessment' || creativeReview.user_approval !== 'pending') throw new Error('文章创作检查未返回有效助手报告');
    if (executionError && (executionError.code !== 1 || creativeReview.ok)) throw new Error('文章创作检查未能完成');
    if (creativeReview.ok && creativeReview.errors.length) throw new Error('文章创作检查状态与错误列表不一致');
    if (!creativeReview.ok) errors.push(...(creativeReview.errors.length ? creativeReview.errors : ['未通过但缺少说明']).map(message => `创作检查：${message}`));
  } catch (error) { errors.push(error.message); }
}
console.log(JSON.stringify({ ok: errors.length === 0, errors, previews, wechat_paste_verified: false, ...(creativeReview ? { creative_review: creativeReview } : {}) }, null, 2));
process.exitCode = errors.length ? 1 : 0;
