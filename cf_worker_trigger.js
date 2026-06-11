// Cloudflare Worker：定时触发 X_Python 的 GitHub Actions 扫描（scan.yml）
// 替代 iOS 快捷指令手动触发。盲触发即可：send_report.py 非交易日自动跳过。
//
// 需要配置（Worker → 设置 → 变量和机密）：
//   GH_REPO  (文本)   例如 srbaby/你的仓库名 —— 即托管 scan.yml 的仓库
//   GH_TOKEN (机密)   fine-grained PAT，仅授该仓库 Actions: Read and write
//
// Cron（UTC）：正式值 "49 6 * * MON-FRI" = 北京 14:49 周一至周五
// ⚠️ CF cron 星期字段 1=周日（非标准），务必用 MON-FRI 英文缩写

export default {
  // 定时触发入口
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env, `cron:${event.cron}`));
  },

  // 浏览器访问入口（仅用于验证，需带 ?key=GH_TOKEN第12-19位，即 github_pat_ 之后的8位）
  async fetch(request, env) {
    const key = new URL(request.url).searchParams.get("key");
    if (!key || key !== env.GH_TOKEN.slice(11, 19)) {
      return new Response("forbidden", { status: 403 });
    }
    const result = await dispatch(env, "manual");
    return new Response(result, { status: 200 });
  },
};

async function dispatch(env, source) {
  const url = `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/scan.yml/dispatches`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "cf-worker-ds-trigger",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  // 204 = 成功（GitHub 对 dispatch 成功不返回内容）
  const msg = `[${source}] dispatch -> ${r.status}${r.status === 204 ? " OK" : " FAIL: " + (await r.text())}`;
  console.log(msg);
  return msg;
}
