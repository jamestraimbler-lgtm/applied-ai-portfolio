/**
 * MCP capability prober — verifies a server's real tools against seller claims.
 *
 * Makes a real JSON-RPC `tools/list` call to the endpoint (when safe to do so)
 * and compares the result against the claimed capabilities. The probe result
 * feeds into the approval agent as additional risk signals.
 *
 * SSRF protection is mandatory: the endpoint URL is validated against private
 * ranges, reserved hosts, and non-standard ports BEFORE any network call.
 */
import { probeResultSchema, type ProbeResult } from "@/schemas";
import { lookup } from "node:dns/promises";

// ---------------------------------------------------------------------------
//  Sensitive tool name patterns — case-insensitive substring match.
// ---------------------------------------------------------------------------

const SENSITIVE_PATTERNS = [
  "exec",
  "eval",
  "shell",
  "read_file",
  "write_file",
  "delete",
  "filesystem",
  "env",
  "secret",
  "credential",
  "password",
  "ssh",
  "sudo",
  "http_request",
  "fetch_url",
  "network",
];

function isSensitiveTool(name: string): boolean {
  const lower = name.toLowerCase();
  return SENSITIVE_PATTERNS.some((p) => lower.includes(p));
}

// ---------------------------------------------------------------------------
//  SSRF validation
// ---------------------------------------------------------------------------

const BLOCKED_HOSTS = new Set([
  "localhost",
  "metadata.google.internal",
  "169.254.169.254",
]);

/** Returns true if the IPv4 address falls in a private/reserved range. */
function isPrivateIPv4(ip: string): boolean {
  const parts = ip.split(".").map(Number);
  if (parts.length !== 4 || parts.some((p) => isNaN(p))) return false;
  const [a, b] = parts;
  // 127.0.0.0/8
  if (a === 127) return true;
  // 10.0.0.0/8
  if (a === 10) return true;
  // 172.16.0.0/12
  if (a === 172 && b! >= 16 && b! <= 31) return true;
  // 192.168.0.0/16
  if (a === 192 && b === 168) return true;
  // 169.254.0.0/16 (link-local / cloud metadata)
  if (a === 169 && b === 254) return true;
  // 0.0.0.0
  if (a === 0) return true;
  return false;
}

function isPrivateIPv6(ip: string): boolean {
  const normalized = ip.toLowerCase();
  // ::1 loopback
  if (normalized === "::1" || normalized === "0000:0000:0000:0000:0000:0000:0000:0001") return true;
  // fc00::/7 (unique local)
  if (normalized.startsWith("fc") || normalized.startsWith("fd")) return true;
  // fe80::/10 (link-local)
  if (normalized.startsWith("fe80")) return true;
  return false;
}

interface SafetyResult {
  ok: boolean;
  error?: string;
}

async function validateEndpointUrl(urlStr: string): Promise<SafetyResult> {
  let parsed: URL;
  try {
    parsed = new URL(urlStr);
  } catch {
    return { ok: false, error: "endpoint failed safety validation" };
  }

  // Must be https
  if (parsed.protocol !== "https:") {
    return { ok: false, error: "endpoint failed safety validation" };
  }

  // Port check: only 443 (the default for https)
  // If no explicit port, it's 443 by default. If explicit, must be "443".
  if (parsed.port && parsed.port !== "443") {
    return { ok: false, error: "endpoint failed safety validation" };
  }

  // Blocked hostnames
  if (BLOCKED_HOSTS.has(parsed.hostname.toLowerCase())) {
    return { ok: false, error: "endpoint failed safety validation" };
  }

  // DNS resolution to check for private IPs
  try {
    const results = await lookup(parsed.hostname, { all: true });
    for (const result of results) {
      if (result.family === 4 && isPrivateIPv4(result.address)) {
        return { ok: false, error: "endpoint failed safety validation" };
      }
      if (result.family === 6 && isPrivateIPv6(result.address)) {
        return { ok: false, error: "endpoint failed safety validation" };
      }
    }
  } catch {
    // DNS resolution failed — can't verify, treat as unreachable
    return { ok: false, error: "endpoint failed safety validation" };
  }

  return { ok: true };
}

// ---------------------------------------------------------------------------
//  The prober
// ---------------------------------------------------------------------------

interface ProbeSpec {
  transport: "STDIO" | "SSE" | "STREAMABLE_HTTP";
  endpointUrl: string | null;
  authType: "NONE" | "API_KEY" | "OAUTH";
  capabilities: unknown;
}

function extractClaimedTools(capabilities: unknown): string[] {
  if (
    capabilities &&
    typeof capabilities === "object" &&
    "tools" in capabilities &&
    Array.isArray((capabilities as { tools: unknown }).tools)
  ) {
    return (capabilities as { tools: Array<{ name?: string }> }).tools
      .map((t) => t.name)
      .filter((n): n is string => typeof n === "string");
  }
  return [];
}

function makeUnprobeableResult(error: string): ProbeResult {
  return probeResultSchema.parse({
    reachable: false,
    probedTools: null,
    mismatch: null,
    error,
    sensitiveUndeclared: [],
  });
}

export async function probeListing(spec: ProbeSpec): Promise<ProbeResult> {
  // Gate: only probe remote transports with no auth and a URL
  if (spec.transport === "STDIO") {
    return makeUnprobeableResult("local transport — cannot probe STDIO servers");
  }

  if (spec.authType !== "NONE") {
    return makeUnprobeableResult(
      `requires authentication (${spec.authType}) — cannot probe without credentials`,
    );
  }

  if (!spec.endpointUrl) {
    return makeUnprobeableResult("no endpoint URL provided");
  }

  // SSRF validation — MUST pass before any network call
  const safety = await validateEndpointUrl(spec.endpointUrl);
  if (!safety.ok) {
    return makeUnprobeableResult(safety.error!);
  }

  // Make the MCP JSON-RPC tools/list call
  let probedToolNames: string[];
  try {
    const response = await fetch(spec.endpointUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "tools/list",
        id: 1,
        params: {},
      }),
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok) {
      return makeUnprobeableResult(
        `server returned HTTP ${response.status}`,
      );
    }

    const body: unknown = await response.json();

    // Parse the JSON-RPC response
    if (
      !body ||
      typeof body !== "object" ||
      !("result" in body) ||
      !body.result ||
      typeof body.result !== "object" ||
      !("tools" in body.result) ||
      !Array.isArray((body.result as { tools: unknown }).tools)
    ) {
      return makeUnprobeableResult(
        "server responded but tools/list returned an unexpected shape",
      );
    }

    const tools = (body.result as { tools: Array<{ name?: string }> }).tools;
    probedToolNames = tools
      .map((t) => t.name)
      .filter((n): n is string => typeof n === "string");
  } catch (err) {
    const msg =
      err instanceof DOMException && err.name === "TimeoutError"
        ? "request timed out after 5s"
        : err instanceof Error
          ? err.message
          : "unknown fetch error";
    return makeUnprobeableResult(msg);
  }

  // Compare probed vs claimed
  const claimed = extractClaimedTools(spec.capabilities);
  const claimedSet = new Set(claimed);
  const probedSet = new Set(probedToolNames);

  const undeclared = probedToolNames.filter((t) => !claimedSet.has(t));
  const missing = claimed.filter((t) => !probedSet.has(t));
  const sensitiveUndeclared = undeclared.filter(isSensitiveTool);

  return probeResultSchema.parse({
    reachable: true,
    probedTools: probedToolNames,
    mismatch:
      undeclared.length > 0 || missing.length > 0
        ? { undeclared, missing }
        : null,
    error: null,
    sensitiveUndeclared,
  });
}
