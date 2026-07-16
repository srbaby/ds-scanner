// Cloudflare Worker：定时触发 X-Plan 的 GitHub Actions 扫描（中控升级版）
//
// 外部调度映射关系（由中央调度器在对应北京时间发起请求）：
//   12:00  → action=scan (午休扫描)
//   14:49  → action=scan (尾盘扫描)
//   20:30  → action=observe (量化观察兜底)

export default {
  // 唯一的安全网页/URL 触发入口
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const token = url.searchParams.get("token");

    // 1. 安全校验：必须匹配你在网页端设置的秘密暗号 CRON_TOKEN
    if (!token || token !== env.CRON_TOKEN) {
      return new Response("Forbidden: Invalid or Missing Token", {
        status: 403,
      });
    }

    const action = url.searchParams.get("action");

    if (action === "scan") {
      try {
        const result = await dispatch(env, "http-center-scan", "scan.yml");
        return new Response(`[Success] ${result}`, { status: 200 });
      } catch (err) {
        return new Response(`[Error] ${err.message}`, { status: 500 });
      }
    } else if (action === "observe") {
      try {
        const result = await dispatch(env, "http-center-observe", "observe.yml");
        return new Response(`[Success] ${result}`, { status: 200 });
      } catch (err) {
        return new Response(`[Error] ${err.message}`, { status: 500 });
      }
    } else {
      return new Response("Unknown action. Available: scan, observe", { status: 400 });
    }
  },
};

async function dispatch(env, source, workflow) {
  const url = `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${workflow}/dispatches`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "cf-worker-ds-trigger",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const msg = `[${source}:${workflow}] dispatch -> ${r.status}${r.status === 204 ? " OK" : " FAIL: " + (await r.text())}`;
  console.log(msg);
  return msg;
}
