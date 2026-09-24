/**
 * Laya 决策服务 TypeScript 客户端（零依赖，Node 18+ / 浏览器 fetch 均可）。
 *
 * 心智模型：给「情境 + 要判断的问题」→ 回「结论 + 把握程度」。
 * 三种问法：choose 选择类 / rate 程度类 / yesNo 是非类。
 */

export interface Usage {
  latency_ms: number;
  queue_wait_ms: number;
  input_tokens: number;
  output_tokens: number;
  cold_start: boolean;
}

export interface EngineInfo {
  model: string;
  backend: string;
  pkg?: string;
  engine_mode?: string;
}

export interface DecideResponse {
  api_version: string;
  request_id?: string | null;
  engine: EngineInfo;
  answers: Record<string, any>;
  usage: Usage;
  warnings: string[];
}

/** 语义层结论：结论字段 + 把握程度 + 是否可自动处理。 */
export interface Decision {
  kind: 'choice' | 'score' | 'yes_no';
  label?: string;                 // choose
  score?: number;                 // rate
  level?: string;                 // rate
  answer?: boolean;               // yesNo
  probability?: number;           // yesNo: P(true)
  confidence: number;
  auto: boolean;
  needsReview: boolean;
  distribution: Record<string, number>;
  usage: Usage;
  raw: DecideResponse;
}

export class LayaError extends Error {
  // 不写参数属性（constructor(public x)）：Node 的 type-stripping 模式不支持该语法
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(`${code} (${status}): ${message}`);
    this.code = code;
    this.status = status;
  }
}

export class LayaClient {
  static readonly TAU_DEFAULT = 0.6;
  private readonly base: string;
  private readonly apiKey?: string;

  constructor(baseUrl = 'http://127.0.0.1:8765', apiKey?: string) {
    this.base = baseUrl.replace(/\/$/, '');
    this.apiKey = apiKey;
  }

  // ---------------- 原始契约
  async decide(payload: {
    state: unknown;
    questions?: Record<string, unknown>;
    preset?: string;
    policy?: Record<string, unknown>;
  }): Promise<DecideResponse> {
    return this.request<DecideResponse>('POST', '/v1/decide', payload);
  }

  async status(): Promise<any> { return this.request('GET', '/v1/status'); }
  async healthz(): Promise<any> { return this.request('GET', '/healthz'); }
  async presets(): Promise<string[]> { return (await this.request<{ presets: string[] }>('GET', '/v1/presets')).presets; }

  // ---------------- 三种问法
  /** 选择类：这属于哪一类 / 该给谁。options 是「标签 → 说明」。 */
  async choose(state: unknown, question: string, options: Record<string, string> | string[],
               tau = LayaClient.TAU_DEFAULT): Promise<Decision> {
    const r = await this.decide({ state, questions: { choice: { type: 'choice', instructions: question, criteria: options } } });
    return this.toDecision(r, 'choice', tau);
  }

  /** 程度类：多严重 / 几分。levels 从低到高。 */
  async rate(state: unknown, question: string, levels: string[],
             tau = LayaClient.TAU_DEFAULT): Promise<Decision> {
    const r = await this.decide({ state, questions: { rating: { type: 'score', instructions: question, criteria: levels } } });
    return this.toDecision(r, 'rating', tau);
  }

  /** 是非类：要不要 / 是不是。 */
  async yesNo(state: unknown, question: string, tau = LayaClient.TAU_DEFAULT): Promise<Decision> {
    const r = await this.decide({ state, questions: { yes_no: { type: 'noul', instructions: question } } });
    return this.toDecision(r, 'yes_no', tau);
  }

  // ---------------- 内部
  private toDecision(resp: DecideResponse, qid: string, tau: number): Decision {
    const a = resp.answers?.[qid] ?? {};
    const confidence = Number(a.confidence ?? 0);
    const base = { confidence, auto: confidence >= tau, needsReview: confidence < tau,
                   distribution: a.probabilities ?? {}, usage: resp.usage, raw: resp };
    if (a.type === 'choice') return { ...base, kind: 'choice', label: a.choice };
    if (a.type === 'score') {
      const legend: Record<string, string> = a.legend ?? {};
      return { ...base, kind: 'score', score: Number(a.score ?? 0),
               level: legend[String(Math.round(Number(a.score ?? 0)))] };
    }
    const p = Number(a.noul ?? 0);
    return { ...base, kind: 'yes_no', probability: p, answer: p >= 0.5 };
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (this.apiKey) headers['X-API-Key'] = this.apiKey;
    const res = await fetch(this.base + path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status >= 400) {
      throw new LayaError(data?.error?.code ?? 'INTERNAL', data?.error?.message ?? res.statusText, res.status);
    }
    return data as T;
  }
}
