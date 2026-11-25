export async function GET() {
  try {
    const base = process.env.FLOODINSIGHT_API_URL || "http://127.0.0.1:8000";
    const response = await fetch(new URL("/health", base), {
      cache: "no-store", signal: AbortSignal.timeout(5_000),
    });
    return new Response(response.body, {
      status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ status: "unavailable", service: "api-service" }, { status: 503 });
  }
}
