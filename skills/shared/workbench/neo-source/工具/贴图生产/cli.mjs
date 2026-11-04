import { loadDraft, checkDraft, renderDraft } from './lib.mjs';

const [command, ...args] = process.argv.slice(2);
let manifest, requireCreativeReview = false, invalid = false;
for (let index = 0; index < args.length; index++) {
  if (args[index] === '--manifest' && manifest === undefined && args[index + 1] && !args[index + 1].startsWith('--')) manifest = args[++index];
  else if (args[index] === '--require-creative-review' && !requireCreativeReview) requireCreativeReview = true;
  else invalid = true;
}
if (command === '--help' || !command) {
  console.log('用法：node cli.mjs <check|render> --manifest <草稿包-v0.1.json> [--require-creative-review]\ncheck 检查最终图片、字符与材料；render 检查并导出 HTML 页，拒绝覆盖旧图。\n新制作使用 --require-creative-review；历史包没有 creative_review 时保持原检查。有引用时始终核验，不以助手检查代替用户采纳。\nJSON 报告输出到标准输出；执行不会认可、提交或发布内容。');
} else if (!['check', 'render'].includes(command) || !manifest || invalid) {
  console.error('参数错误；请运行 node cli.mjs --help');
  process.exitCode = 2;
} else {
  try {
    const draft = await loadDraft(manifest);
    const options = { requireCreativeReview };
    const report = await (command === 'render' ? renderDraft(draft, options) : checkDraft(draft, options));
    console.log(JSON.stringify(report, null, 2));
    process.exitCode = report.ok ? 0 : 1;
  } catch (error) {
    console.error(JSON.stringify({ ok: false, errors: [error.message] }, null, 2));
    process.exitCode = 1;
  }
}
