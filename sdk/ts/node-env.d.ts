/** 仅声明 demo 用到的 Node 全局，避免为了类型检查引入 @types/node（保持零依赖）。 */
declare const process: {
  argv: string[];
  env: Record<string, string | undefined>;
};
