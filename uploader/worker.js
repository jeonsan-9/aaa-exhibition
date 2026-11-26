// AAA 천체사진전 — 올리기 서버 (Cloudflare Worker)
//
// 사이트의 "전시 올리기" 페이지가 보낸 zip 을 받아, 비밀번호를 확인한 뒤
// GitHub 릴리스에 첨부한다. 그러면 레포의 Actions 가 사이트를 다시 만든다.
//
// Cloudflare 에 넣어야 하는 값 (Settings → Variables and Secrets)
//   UPLOAD_PASSWORD  (Secret)  올리기 비밀번호
//   GITHUB_TOKEN     (Secret)  이 레포에 Contents·Actions 쓰기 권한이 있는 토큰
//   GITHUB_REPO      (Text)    예: jeonsan-9/aaa-exhibition
//   SITE_URL         (Text)    예: https://jeonsan-9.github.io/aaa-exhibition
//   ALLOWED_ORIGIN   (Text, 선택) 예: https://jeonsan-9.github.io

const NAME_RE = /^[0-9A-Za-z][0-9A-Za-z_-]{0,39}$/;
const RESERVED = ["upload", "assets", "index"];
const MAX_BYTES = 95 * 1024 * 1024;
const WORKFLOW = "deploy.yml";

// 비밀번호 찍어 맞히기 막기: 같은 곳에서 10분에 5번, 전체로 1시간에 30번 틀리면 잠근다.
// (Worker 메모리에 두는 값이라 서버가 새로 뜨면 초기화된다. 완벽한 잠금은 아니다.)
const PER_IP = { limit: 5, windowMs: 10 * 60 * 1000 };
const GLOBAL = { limit: 30, windowMs: 60 * 60 * 1000 };
const fails = new Map();

function blocked(key, rule, now) {
  const list = (fails.get(key) || []).filter((t) => now - t < rule.windowMs);
  fails.set(key, list);
  return list.length >= rule.limit;
}
function recordFail(key, now) {
  const list = fails.get(key) || [];
  list.push(now);
  fails.set(key, list);
  if (fails.size > 5000) fails.clear();
}

async function sameText(a, b) {
  const enc = new TextEncoder();
  const [x, y] = await Promise.all([crypto.subtle.digest("SHA-256", enc.encode(a)), crypto.subtle.digest("SHA-256", enc.encode(b))]);
  const p = new Uint8Array(x), q = new Uint8Array(y);
  let diff = 0;
  for (let i = 0; i < p.length; i++) diff |= p[i] ^ q[i];
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allowed = (env.ALLOWED_ORIGIN || "").split(",").map((s) => s.trim()).filter(Boolean);
    const cors = {
      "Access-Control-Allow-Origin": allowed.length === 0 ? "*" : allowed.includes(origin) ? origin : allowed[0],
      "Access-Control-Allow-Methods": "PUT, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-Password",
      "Access-Control-Max-Age": "86400",
      Vary: "Origin",
    };
    const json = (status, body) =>
      new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json; charset=utf-8" } });

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (request.method === "GET") return json(200, { ok: true, service: "aaa-exhibition-uploader" });
    if (request.method !== "PUT") return json(405, { error: "지원하지 않는 요청입니다." });
    if (allowed.length && origin && !allowed.includes(origin)) return json(403, { error: "이 사이트에서는 올릴 수 없습니다." });
    if (!env.UPLOAD_PASSWORD || !env.GITHUB_TOKEN || !env.GITHUB_REPO) {
      return json(500, { error: "서버 설정이 끝나지 않았습니다. 관리자에게 알려 주세요." });
    }

    // 1. 비밀번호
    const now = Date.now();
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    if (blocked("ip:" + ip, PER_IP, now) || blocked("all", GLOBAL, now)) {
      return json(429, { error: "비밀번호를 여러 번 틀려 잠시 막혔습니다. 10분 뒤에 다시 해 주세요." });
    }
    if (!(await sameText(request.headers.get("X-Password") || "", env.UPLOAD_PASSWORD))) {
      recordFail("ip:" + ip, now);
      recordFail("all", now);
      await new Promise((r) => setTimeout(r, 1500));
      return json(401, { error: "비밀번호가 맞지 않습니다." });
    }

    // 2. 이름과 파일 확인
    const name = (new URL(request.url).searchParams.get("name") || "").trim().toLowerCase();
    if (!NAME_RE.test(name) || RESERVED.includes(name)) {
      return json(400, { error: "전시 이름은 영문, 숫자, - 만 쓸 수 있습니다. 예: 2026-2" });
    }
    // 올리기 전에 페이지가 비밀번호와 이름만 먼저 확인해 보는 요청
    if (new URL(request.url).searchParams.has("check")) return json(200, { ok: true, check: true });
    const size = Number(request.headers.get("Content-Length") || 0);
    if (!size || !request.body) return json(411, { error: "파일이 비어 있습니다." });
    if (size > MAX_BYTES) return json(413, { error: "파일이 너무 큽니다. 95MB 이하로 줄여 주세요." });

    // 본문은 읽지 않고 그대로 GitHub 으로 흘려보낸다 (길이가 유지되고, 큰 파일도 부담이 없다).
    const body = request.body;

    // 3. GitHub 릴리스에 첨부
    const repo = env.GITHUB_REPO;
    const auth = {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "aaa-exhibition-uploader",
    };
    const gh = (path, init = {}) => fetch("https://api.github.com" + path, { ...init, headers: { ...auth, ...(init.headers || {}) } });
    const fail = async (step, res) => {
      console.log("github error", step, res.status, (await res.text()).slice(0, 300));
      return json(502, { error: `GitHub 에 올리다 실패했습니다 (${step}, ${res.status}). 관리자에게 알려 주세요.` });
    };

    let release, isNew = false;
    const found = await gh(`/repos/${repo}/releases/tags/${name}`);
    if (found.ok) {
      release = await found.json();
    } else if (found.status === 404) {
      const made = await gh(`/repos/${repo}/releases`, {
        method: "POST",
        body: JSON.stringify({ tag_name: name, name: `${name} 전시`, body: "올리기 페이지에서 올린 전시 자료입니다.", draft: true }),
      });
      if (!made.ok) return fail("전시 만들기", made);
      release = await made.json();
      isNew = true;
    } else {
      return fail("전시 찾기", found);
    }

    for (const a of release.assets || []) {
      if (a.name.toLowerCase().endsWith(".zip")) await gh(`/repos/${repo}/releases/assets/${a.id}`, { method: "DELETE" });
    }
    const up = await fetch(`https://uploads.github.com/repos/${repo}/releases/${release.id}/assets?name=${name}.zip`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/zip", "Content-Length": String(size) },
      body,
      duplex: "half",
    });
    if (!up.ok) {
      if (isNew) await gh(`/repos/${repo}/releases/${release.id}`, { method: "DELETE" });
      return fail("파일 올리기", up);
    }

    // 4. 사이트 다시 만들기: 새 전시는 공개하는 순간, 기존 전시는 직접 실행시킨다.
    const kick = isNew
      ? await gh(`/repos/${repo}/releases/${release.id}`, { method: "PATCH", body: JSON.stringify({ draft: false }) })
      : await gh(`/repos/${repo}/actions/workflows/${WORKFLOW}/dispatches`, { method: "POST", body: JSON.stringify({ ref: env.GITHUB_BRANCH || "main" }) });
    if (!kick.ok) return fail("사이트 만들기 시작", kick);

    const site = (env.SITE_URL || "").replace(/\/+$/, "");
    return json(200, { ok: true, name, replaced: !isNew, url: site ? `${site}/${name}/` : null });
  },
};
