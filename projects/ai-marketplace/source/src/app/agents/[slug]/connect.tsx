"use client";

/**
 * Connect panel — shows connection details, access key, and ready-to-paste
 * config snippets for active subscribers. Only renders data gated behind
 * subscription.connectionDetails (server-side active-subscription check).
 */
import { useState } from "react";
import { api } from "@/lib/trpc";
import { extractTools } from "@/lib/listing-format";
import styles from "@/app/_components/storefront.module.css";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className={styles.copyBtn}
      onClick={() => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function CodeBlock({ label, code, note }: { label: string; code: string; note?: string }) {
  return (
    <div className={styles.codeSection}>
      <div className={styles.codeLabel}>
        <span>{label}</span>
        <CopyButton text={code} />
      </div>
      <pre className={styles.codeBlock}>{code}</pre>
      {note && <p style={{ fontSize: "0.72rem", color: "var(--muted)", margin: "0.3rem 0 0", lineHeight: 1.45 }}>{note}</p>}
    </div>
  );
}

function buildRemoteMcpConfig(
  serverName: string,
  endpointUrl: string,
  authType: string | null,
  accessKey: string | null,
) {
  const args: string[] = ["-y", "mcp-remote@latest", endpointUrl];
  if (authType === "API_KEY" && accessKey) {
    args.push("--header", `Authorization: Bearer ${accessKey}`);
  }
  return JSON.stringify({ mcpServers: { [serverName]: { command: "npx", args } } }, null, 2);
}

function buildStdioMcpConfig(
  serverName: string,
  authType: string | null,
  accessKey: string | null,
) {
  const entry: Record<string, unknown> = {
    command: "<path-to-server-binary>",
    args: [],
  };
  if (authType === "API_KEY" && accessKey) {
    entry.env = { MCP_API_KEY: accessKey };
  }
  return JSON.stringify({ mcpServers: { [serverName]: entry } }, null, 2);
}

export function ConnectPanel({ listingId }: { listingId: string }) {
  const { data, isLoading, error } = api.subscription.connectionDetails.useQuery(
    { listingId },
  );

  if (isLoading) return <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Loading connection details...</p>;
  if (error) return null;
  if (!data) return null;

  const tools = extractTools(data.capabilities);
  const serverName = data.slug ?? "mcp-server";
  const isRemote = data.transport === "STREAMABLE_HTTP" || data.transport === "SSE";
  const isOAuth = data.authType === "OAUTH";

  // Build config snippets per transport
  let claudeConfig: string;
  let claudeNote: string;
  let cursorConfig: string;
  let cursorNote: string;

  if (isRemote && data.endpointUrl) {
    claudeConfig = buildRemoteMcpConfig(serverName, data.endpointUrl, data.authType, data.accessKey);
    claudeNote =
      "Add to ~/Library/Application Support/Claude/claude_desktop_config.json (macOS) or %APPDATA%\\Claude\\claude_desktop_config.json (Windows). Restart Claude Desktop after editing.";
    cursorConfig = buildRemoteMcpConfig(serverName, data.endpointUrl, data.authType, data.accessKey);
    cursorNote = "Add to ~/.cursor/mcp.json. Cursor picks up changes automatically.";
  } else {
    // STDIO
    claudeConfig = buildStdioMcpConfig(serverName, data.authType, data.accessKey);
    claudeNote =
      "Replace <path-to-server-binary> with the command the seller provides. Add to ~/Library/Application Support/Claude/claude_desktop_config.json (macOS) or %APPDATA%\\Claude\\claude_desktop_config.json (Windows). Restart Claude Desktop after editing.";
    cursorConfig = buildStdioMcpConfig(serverName, data.authType, data.accessKey);
    cursorNote = "Replace <path-to-server-binary> with the command the seller provides. Add to ~/.cursor/mcp.json.";
  }

  const genericLines = [
    `Server: ${data.name}`,
    `Transport: ${data.transport}`,
    ...(data.endpointUrl ? [`Endpoint: ${data.endpointUrl}`] : []),
    `Auth: ${data.authType ?? "NONE"}`,
    ...(data.accessKey ? [`API Key: ${data.accessKey}`] : []),
    ...(data.protocolVersion ? [`Protocol: ${data.protocolVersion}`] : []),
  ].join("\n");

  return (
    <div className={styles.connectPanel}>
      <div className={styles.connectHeader}>Connection details</div>

      <div className={styles.connectGrid}>
        {data.endpointUrl && (
          <div className={styles.connectRow}>
            <span className={styles.connectK}>Endpoint</span>
            <span className={styles.connectV}>{data.endpointUrl}</span>
          </div>
        )}
        <div className={styles.connectRow}>
          <span className={styles.connectK}>Transport</span>
          <span className={styles.connectV}>{data.transport}</span>
        </div>
        <div className={styles.connectRow}>
          <span className={styles.connectK}>Auth</span>
          <span className={styles.connectV}>{data.authType ?? "none"}</span>
        </div>
        {data.protocolVersion && (
          <div className={styles.connectRow}>
            <span className={styles.connectK}>Protocol</span>
            <span className={styles.connectV}>{data.protocolVersion}</span>
          </div>
        )}
      </div>

      {data.accessKey && (
        <div className={styles.keySection}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className={styles.connectK}>Your API key</span>
            <CopyButton text={data.accessKey} />
          </div>
          <div className={styles.keyField}>{data.accessKey}</div>
          <div className={styles.keyNote}>Keep this secret. Do not share it or commit it to version control.</div>
        </div>
      )}

      {isOAuth && (
        <p style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "0.5rem 0 0", lineHeight: 1.45 }}>
          This server uses OAuth — your client will prompt you to authorize on first connect.
        </p>
      )}

      {tools.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          <div className={styles.connectK} style={{ marginBottom: "0.4rem" }}>Available tools ({tools.length})</div>
          <div style={{ display: "grid", gap: "0.3rem" }}>
            {tools.map((t, i) => (
              <div key={i} className={styles.connectTool}>
                <span className={styles.connectToolName}>{t.name}</span>
                {t.description && <span className={styles.connectToolDesc}>{t.description}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: "1.25rem" }}>
        <div className={styles.connectK} style={{ marginBottom: "0.6rem" }}>Client config snippets</div>
        <CodeBlock label="Claude Desktop" code={claudeConfig} note={claudeNote} />
        {isRemote && (
          <p style={{ fontSize: "0.72rem", color: "var(--muted)", margin: "-0.4rem 0 0.75rem", lineHeight: 1.45 }}>
            On Claude Desktop Pro/Max/Team/Enterprise, you can also add this server via Settings → Connectors → Add custom connector (paste the endpoint URL).
          </p>
        )}
        <CodeBlock label="Cursor" code={cursorConfig} note={cursorNote} />
        <CodeBlock label="Generic / raw" code={genericLines} />
      </div>
    </div>
  );
}
