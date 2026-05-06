import { Type, Hash, ToggleLeft, List, Filter, Braces, type LucideIcon } from "lucide-react";
import type { SchemaField } from "../SchemaEditor";

const TYPE_ICON: Record<string, LucideIcon> = {
  str: Type,
  int: Hash,
  float: Hash,
  bool: ToggleLeft,
  "list[str]": List,
  "list[int]": List,
  "list[float]": List,
  vector_search_filter: Filter,
  structured: Braces,
};

const TYPE_LABEL: Record<string, string> = {
  str: "Text",
  int: "Integer",
  float: "Number",
  bool: "Boolean",
  "list[str]": "List of text",
  "list[int]": "List of integers",
  "list[float]": "List of numbers",
  vector_search_filter: "VS filter",
  structured: "Structured",
};

interface Props {
  schema: SchemaField[];
}

/** Per-field rows shown on an LLM node when it has a structured output schema.
 *  Each row: type icon + field name. Hover for the human-readable type. */
export default function OutputSchemaList({ schema }: Props) {
  const valid = schema.filter((f) => f.name?.trim());
  if (valid.length === 0) return null;

  return (
    <div className="agent-node-outputs">
      {valid.map((field) => {
        const Icon = TYPE_ICON[field.type] ?? Type;
        const typeLabel = TYPE_LABEL[field.type] ?? field.type;
        return (
          <div
            key={field.name}
            className="agent-node-output-row"
            title={`${field.name}: ${typeLabel}`}
          >
            <Icon size={11} className="agent-node-output-icon" />
            <span className="agent-node-output-name">{field.name}</span>
          </div>
        );
      })}
    </div>
  );
}
