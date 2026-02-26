import { NextResponse } from "next/server";

export const runtime = "edge";

/**
 * Cron-triggered keep-alive: pings the Render backend every 10 minutes
 * to prevent it from sleeping (free tier spins down after 15 min inactivity).
 */
export async function GET() {
  const backendUrl =
    process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

  try {
    const res = await fetch(`${backendUrl}/api/health`, {
      signal: AbortSignal.timeout(55_000),
    });
    const data = await res.json();
    return NextResponse.json({ backend: data, pinged_at: new Date().toISOString() });
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
