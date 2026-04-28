import { Brain, Search, BarChart3, FunctionSquare, Globe, MessageSquare } from "lucide-react";
import ProviderIcon, { getProvider } from "../ProviderIcon";
import ResourcePill from "./ResourcePill";
import OutputSchemaList from "./OutputSchemaList";
import type { SchemaField } from "../SchemaEditor";
import type { AttachedTool } from "../../types";
import { useDiscoveryLabel } from "./useDiscoveryLabel";

interface Props {
  nodeType: string;
  config: Record<string, unknown>;
  tools?: AttachedTool[];
}

const PROVIDER_FRIENDLY: Record<string, string> = {
  "databricks-meta-llama-3-3-70b-instruct": "Llama 3.3 70B",
  "databricks-meta-llama-3-1-405b-instruct": "Llama 3.1 405B",
  "databricks-claude-sonnet-4": "Claude Sonnet 4",
  "databricks-claude-3-7-sonnet": "Claude 3.7 Sonnet",
  "databricks-dbrx-instruct": "DBRX Instruct",
  "databricks-mixtral-8x7b-instruct": "Mixtral 8x7B",
};

const PILL_ICON_SIZE = 13;

function shortIndexName(name: string): string {
  if (!name) return "";
  const parts = name.split(".");
  return parts[parts.length - 1] || name;
}

function shortFnName(name: string): string {
  if (!name) return "";
  const parts = name.split(".");
  if (parts.length >= 2) return `${parts[parts.length - 2]}.${parts[parts.length - 1]}`;
  return name;
}

function trimText(text: string, max = 56): string {
  const normalized = text.trim().replace(/\s+/g, " ");
  if (normalized.length <= max) return normalized;
  return normalized.slice(0, max - 1).trimEnd() + "…";
}

function mcpServerLabel(url: string): string {
  if (!url) return "";
  const managed = url.match(/\/api\/2\.0\/mcp\/([^/]+)\/(.+)$/);
  if (managed) {
    const [, kind, rest] = managed;
    return `${kind}: ${rest.split("/").slice(-2).join("/")}`;
  }
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function MetaLine({ children }: { children: string }) {
  if (!children) return null;
  return <div className="agent-node-meta">{children}</div>;
}

function parseSchema(raw: unknown): SchemaField[] {
  if (Array.isArray(raw)) return raw as SchemaField[];
  if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed as SchemaField[];
    } catch { /* ignore */ }
  }
  return [];
}

function LlmSummary({ config, tools }: { config: Record<string, unknown>; tools?: AttachedTool[] }) {
  const endpoint = (config.endpoint as string) ?? "";
  const friendly = PROVIDER_FRIENDLY[endpoint];
  const discovered = useDiscoveryLabel("/api/discover/serving-endpoints", endpoint);
  const value = friendly ?? discovered ?? "";

  const provider = endpoint ? getProvider(endpoint) : "unknown";
  const icon = endpoint
    ? <ProviderIcon provider={provider} size={PILL_ICON_SIZE} />
    : <Brain size={PILL_ICON_SIZE} />;

  const schema = parseSchema(config.output_schema);
  const toolCount = tools?.length ?? 0;
  const meta = toolCount > 0 ? `${toolCount} tool${toolCount === 1 ? "" : "s"}` : "";

  return (
    <>
      <ResourcePill icon={icon} value={value} placeholder="Select a model" />
      <MetaLine>{meta}</MetaLine>
      <OutputSchemaList schema={schema} />
    </>
  );
}

function GenieSummary({ config }: { config: Record<string, unknown> }) {
  const roomId = (config.room_id as string) ?? "";
  const value = useDiscoveryLabel("/api/discover/genie-spaces", roomId);
  return <ResourcePill icon={<MessageSquare size={PILL_ICON_SIZE} />} value={value} placeholder="Select a Genie space" />;
}

function VectorSearchSummary({ config }: { config: Record<string, unknown> }) {
  return (
    <ResourcePill
      icon={<Search size={PILL_ICON_SIZE} />}
      value={shortIndexName((config.index_name as string) ?? "")}
      placeholder="Select an index"
    />
  );
}

function UCFunctionSummary({ config }: { config: Record<string, unknown> }) {
  return (
    <ResourcePill
      icon={<FunctionSquare size={PILL_ICON_SIZE} />}
      value={shortFnName((config.function_name as string) ?? "")}
      placeholder="Select a function"
    />
  );
}

function McpSummary({ config }: { config: Record<string, unknown> }) {
  return (
    <ResourcePill
      icon={<Globe size={PILL_ICON_SIZE} />}
      value={mcpServerLabel((config.server_url as string) ?? "")}
      placeholder="Select an MCP server"
    />
  );
}

function HumanInputSummary({ config }: { config: Record<string, unknown> }) {
  const prompt = (config.prompt as string) ?? "";
  return (
    <ResourcePill
      icon={<BarChart3 size={PILL_ICON_SIZE} />}
      value={prompt ? trimText(prompt) : ""}
      placeholder="Set a prompt"
    />
  );
}

export default function NodeSummary({ nodeType, config, tools }: Props) {
  switch (nodeType) {
    case "llm": return <LlmSummary config={config} tools={tools} />;
    case "vector_search": return <VectorSearchSummary config={config} />;
    case "genie": return <GenieSummary config={config} />;
    case "uc_function": return <UCFunctionSummary config={config} />;
    case "mcp_server": return <McpSummary config={config} />;
    case "human_input": return <HumanInputSummary config={config} />;
    default: return null;
  }
}
