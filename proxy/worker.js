// Promptioo TV stream proxy: a free Cloudflare Worker that lets the web page play http:// streams.
// Browsers block http:// video on https:// pages and many stream servers send no CORS headers.
// This worker fetches the stream for the page, adds CORS headers, and rewrites .m3u8 playlists so
// every segment also goes through the worker.   Use:  https://YOUR-WORKER.workers.dev/?url=<stream>
const ALLOWED_ORIGINS = [];   // e.g. ["https://aieditsram-svg.github.io"]; empty = any site may use it

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, OPTIONS",
  "access-control-allow-headers": "range, content-type",
  "access-control-expose-headers": "content-length, content-range, content-type",
};

function blocked(host) {
  return /^(localhost|127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|0\.|\[)/i.test(host) || !host.includes(".");
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    const origin = request.headers.get("origin") || "";
    if (ALLOWED_ORIGINS.length && origin && !ALLOWED_ORIGINS.includes(origin))
      return new Response("origin not allowed", { status: 403, headers: CORS });

    const self = new URL(request.url);
    const target = self.searchParams.get("url");
    let t;
    try { t = new URL(target); } catch { return new Response("use ?url=<stream address>", { status: 400, headers: CORS }); }
    if (!/^https?:$/.test(t.protocol) || blocked(t.hostname))
      return new Response("address not allowed", { status: 400, headers: CORS });

    // Edge cache: viewers of the same channel share one copy, so the stream server sees far fewer requests.
    const cache = caches.default;
    const cacheKey = new Request(self.origin + "/?url=" + encodeURIComponent(t.href));
    const hit = !request.headers.get("range") && (await cache.match(cacheKey));
    if (hit) return hit;

    const headers = new Headers();
    const range = request.headers.get("range");
    if (range) headers.set("range", range);
    let up;
    try { up = await fetch(t.href, { headers, redirect: "follow" }); }
    catch { return new Response("stream unreachable", { status: 502, headers: CORS }); }

    const type = up.headers.get("content-type") || "";
    const isPlaylist = /mpegurl/i.test(type) || /\.m3u8?(\?|$)/i.test(t.pathname + t.search);
    const out = new Headers(CORS);
    if (!isPlaylist) {
      for (const h of ["content-type", "content-length", "content-range", "accept-ranges"])
        if (up.headers.get(h)) out.set(h, up.headers.get(h));
      if (up.status === 200 && !range) {
        out.set("cache-control", "public, max-age=60");          // video segments never change
        const res = new Response(up.body, { status: 200, headers: out });
        ctx.waitUntil(cache.put(cacheKey, res.clone()));
        return res;
      }
      return new Response(up.body, { status: up.status, headers: out });
    }

    const base = new URL(up.url || t.href);
    const wrap = (u) => self.origin + "/?url=" + encodeURIComponent(new URL(u, base).href);
    const text = await up.text();
    const body = text.split(/\r?\n/).map((line) => {
      if (!line.trim()) return line;
      if (line.startsWith("#")) return line.replace(/URI="([^"]+)"/g, (m, u) => 'URI="' + wrap(u) + '"');
      return wrap(line.trim());
    }).join("\n");
    out.set("content-type", "application/vnd.apple.mpegurl");
    out.set("cache-control", "public, max-age=2");               // live playlists change every few seconds
    const res = new Response(body, { status: up.status, headers: out });
    if (up.status === 200) ctx.waitUntil(cache.put(cacheKey, res.clone()));
    return res;
  },
};
