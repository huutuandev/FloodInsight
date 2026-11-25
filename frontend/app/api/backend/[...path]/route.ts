import type { NextRequest } from "next/server";

const reads = new Set([
  "locations", "weather/latest", "rainfall/coverage", "rainfall/daily", "rainfall/weekly", "rainfall/monthly",
  "analytics", "clustering/results", "clustering/metrics", "predictions/results",
  "predictions/metrics", "classifications/results", "classifications/metrics",
  "weather/ingestion/history", "weather/etl/status", "weather/quality", "system/status",
]);
const writes = new Set(["analytics/generate", "weather/ingestion/run"]);

type Context = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const path = (await context.params).path.join("/");
  const post = request.method === "POST";
  if (!(post ? writes : reads).has(path)) {
    return Response.json({ error: { message: "Dashboard resource not found" } }, { status: 404 });
  }

  if (post && (request.headers.get("sec-fetch-site") === "cross-site"
    || !request.headers.get("content-type")?.startsWith("application/json"))) {
    return Response.json({ error: { message: "Use a same-origin JSON request." } }, { status: 403 });
  }

  try {
    const base = process.env.FLOODINSIGHT_API_URL || "http://127.0.0.1:8000";
    const target = new URL("/api/v1/" + path, base);
    target.search = request.nextUrl.search;
    const upstream = await fetch(target, {
      method: request.method,
      body: post ? await request.text() : undefined,
      headers: post ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(post ? 185_000 : 15_000),
      redirect: "error",
    });
    const headers = new Headers({
      "Content-Type": upstream.headers.get("content-type") || "application/json",
      "Cache-Control": "no-store",
    });
    const id = upstream.headers.get("x-request-id");
    if (id) headers.set("X-Request-ID", id);
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return Response.json(
      { error: { message: timedOut ? "The gateway request timed out." : "The FloodInsight gateway is unavailable." } },
      { status: timedOut ? 504 : 503 },
    );
  }
}

export { proxy as GET, proxy as POST };
