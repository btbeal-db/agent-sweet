/**
 * Provider icons for model endpoint dropdowns.
 * Uses Simple Icons from react-icons/si for accurate brand marks.
 */

import { Cpu } from "lucide-react";
import {
  SiMeta,
  SiAnthropic,
  SiOpenai,
  SiMistralai,
  SiDatabricks,
  SiGoogle,
} from "react-icons/si";

interface Props {
  provider: string;
  size?: number;
}

const BRAND_COLORS: Record<string, string> = {
  meta: "#0082FB",
  anthropic: "#D4A27F",
  openai: "#e8eaed",
  mistral: "#F7D046",
  databricks: "#FF3621",
  google: "#4285F4",
  qwen: "#7C3AED",
};

export function getProvider(endpointName: string): string {
  const n = endpointName.toLowerCase();
  if (n.includes("llama") || n.includes("meta")) return "meta";
  if (n.includes("claude") || n.includes("anthropic")) return "anthropic";
  if (n.includes("gpt") || n.includes("openai") || /\bo[13]-/.test(n)) return "openai";
  if (n.includes("mistral") || n.includes("mixtral")) return "mistral";
  if (n.includes("dbrx") || n.includes("databricks")) return "databricks";
  if (n.includes("gemini") || n.includes("google")) return "google";
  if (n.includes("qwen")) return "qwen";
  return "unknown";
}

export default function ProviderIcon({ provider, size = 16 }: Props) {
  const color = BRAND_COLORS[provider];
  const props = { size, color, style: { flexShrink: 0 } as const };

  switch (provider) {
    case "meta":
      return <SiMeta {...props} />;
    case "anthropic":
      return <SiAnthropic {...props} />;
    case "openai":
      return <SiOpenai {...props} />;
    case "mistral":
      return <SiMistralai {...props} />;
    case "databricks":
      return <SiDatabricks {...props} />;
    case "google":
      return <SiGoogle {...props} />;
    case "qwen":
      return (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: size,
            height: size,
            borderRadius: size / 2,
            background: "#7C3AED",
            color: "#fff",
            fontSize: size * 0.55,
            fontWeight: 700,
            lineHeight: 1,
            flexShrink: 0,
            fontFamily: "Inter, -apple-system, sans-serif",
          }}
        >
          Q
        </span>
      );
    default:
      return <Cpu size={size} style={{ flexShrink: 0, opacity: 0.5 }} />;
  }
}
