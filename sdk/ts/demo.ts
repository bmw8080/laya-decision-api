/** 端到端示例：node sdk/ts/demo.ts [baseUrl]（密钥读 LAYA_API_KEY）。 */
import { LayaClient, LayaError } from './laya-client.ts';

const base = process.argv[2] ?? 'http://127.0.0.1:8765';
const c = new LayaClient(base, process.env.LAYA_API_KEY);

console.log('健康检查：', await c.healthz());
console.log('内置问题集：', await c.presets());

const ticket = { body: '账单重复扣款，请退款' };
const d = await c.choose(ticket, '该由哪个团队处理？', { billing: '退款/计费', technical: '故障/缺陷' }, 0.6);
console.log('choose  →', d.kind, d.label, 'conf=' + d.confidence, 'auto=' + d.auto, d.distribution);

const u = await c.rate({ body: '系统登录失败，全组都无法使用' }, '紧急程度', ['低', '中', '高'], 0.6);
console.log('rate    → score=' + u.score, 'level=' + u.level, 'conf=' + u.confidence, 'needsReview=' + u.needsReview);

const h = await c.yesNo(ticket, '需要人工介入吗？', 0.6);
console.log('yes_no  → answer=' + h.answer, 'P(true)=' + h.probability, 'conf=' + h.confidence);

try {
  await c.decide({ state: { body: 'x' }, questions: { bad: { type: 'choice', instructions: 'i', criteria: ['a', 'a'] } } });
} catch (e) {
  if (e instanceof LayaError) console.log('错误契约 →', e.message);
  else throw e;
}
