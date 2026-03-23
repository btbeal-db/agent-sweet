import { useCallback } from "react";
import { useReactFlow, useNodes } from "@xyflow/react";
import type { NodeTypeMetadata, AttachedTool } from "../types";
import { useStateVars } from "../StateContext";

interface Props {
  /** The React Flow node ID that owns this tool. */
  parentNodeId: string;
  /** The tool's ID within the parent's tools array. */
  toolId: string;
  /** All node type metadata (to look up config_fields for the tool type). */
  nodeTypes: NodeTypeMetadata[];
}

export default function ToolConfigPanel({ parentNodeId, toolId, nodeTypes }: Props) {
  const { setNodes } = useReactFlow();
  const nodes = useNodes();
  const stateVars = useStateVars();

  const parentNode = nodes.find((n) => n.id === parentNodeId);
  const tools = (parentNode?.data.tools ?? []) as AttachedTool[];
  const tool = tools.find((t) => t.id === toolId);

  const meta = nodeTypes.find((nt) => nt.type === tool?.type);

  const updateToolConfig = useCallback(
    (fieldName: string, value: unknown) => {
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id !== parentNodeId) return n;
          const updatedTools = ((n.data.tools ?? []) as AttachedTool[]).map((t) =>
            t.id === toolId
              ? { ...t, config: { ...t.config, [fieldName]: value } }
              : t
          );
          return { ...n, data: { ...n.data, tools: updatedTools } };
        })
      );
    },
    [parentNodeId, toolId, setNodes]
  );

  if (!tool || !meta) return null;

  // Filter out fields that only make sense as graph nodes (state_variable refs, etc.)
  const fields = meta.config_fields.filter(
    (f) => f.field_type !== "state_variable" && f.field_type !== "route_editor" && f.field_type !== "schema_editor"
  );

  const descriptionVal = (tool.config.tool_description ?? "") as string;

  return (
    <div className="config-panel">
      <h3>{meta.display_name} Tool</h3>

      <div className="config-field">
        <label>Tool Description</label>
        <textarea
          value={descriptionVal}
          placeholder={`Describe when the LLM should use this tool, e.g. "Search our product catalog for relevant items"`}
          onChange={(e) => updateToolConfig("tool_description", e.target.value)}
        />
        <span className="config-hint">
          Tells the LLM when to use this tool. Leave blank for an auto-generated description.
        </span>
      </div>

      {fields.map((field) => {
        const val = (tool.config[field.name] ?? field.default ?? "") as string;

        return (
          <div key={field.name} className="config-field">
            <label>
              {field.label}
              {field.required && " *"}
            </label>

            {field.field_type === "textarea" ? (
              <textarea
                value={val}
                placeholder={field.placeholder}
                onChange={(e) => updateToolConfig(field.name, e.target.value)}
              />
            ) : field.field_type === "select" && field.options ? (
              <select
                value={val}
                onChange={(e) => updateToolConfig(field.name, e.target.value)}
              >
                {field.options.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            ) : (
              <input
                type={field.field_type === "number" ? "number" : "text"}
                value={val}
                placeholder={field.placeholder}
                onChange={(e) =>
                  updateToolConfig(
                    field.name,
                    field.field_type === "number"
                      ? parseFloat(e.target.value) || 0
                      : e.target.value
                  )
                }
              />
            )}
            {field.help_text && (
              <span className="config-hint">{field.help_text}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
