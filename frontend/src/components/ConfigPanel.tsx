import { useReactFlow, useNodes } from "@xyflow/react";
import type { NodeTypeMetadata } from "../types";
import RouteEditor, { type Route } from "./RouteEditor";
import SchemaEditor, { type SchemaField } from "./SchemaEditor";

interface Props {
  selectedNodeId: string;
  nodeTypes: NodeTypeMetadata[];
  stateVariables: string[];
}

export default function ConfigPanel({ selectedNodeId, nodeTypes, stateVariables }: Props) {
  const { setNodes } = useReactFlow();

  const nodes = useNodes();
  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;

  const nodeType = (node.data.nodeType as string) ?? node.type;
  const meta = nodeTypes.find((nt) => nt.type === nodeType);
  if (!meta) return null;

  const config = (node.data.config ?? {}) as Record<string, unknown>;

  const updateConfig = (fieldName: string, value: unknown) => {
    setNodes((nds) =>
      nds.map((n) => {
        if (n.id !== selectedNodeId) return n;
        return {
          ...n,
          data: {
            ...n.data,
            config: { ...(n.data.config as Record<string, unknown>), [fieldName]: value },
          },
        };
      })
    );
  };

  return (
    <div className="config-panel">
      <h3>{meta.display_name} Config</h3>

      {meta.config_fields.map((field) => {

        // State variable — dropdown populated from user-defined state vars
        if (field.field_type === "state_variable") {
          const val = (config[field.name] as string) ?? (field.default as string) ?? stateVariables[0] ?? "";
          return (
            <div key={field.name} className="config-field">
              <label>{field.label}</label>
              <select value={val} onChange={(e) => updateConfig(field.name, e.target.value)}>
                {stateVariables.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
          );
        }

        // Route editor
        if (field.field_type === "route_editor") {
          const raw = config[field.name];
          let routes: Route[];
          const defaultRoute: Route = { name: "default", condition_type: "keywords", condition: "", json_field: "", json_value: "" };
          if (typeof raw === "string") {
            try { routes = JSON.parse(raw); } catch { routes = [defaultRoute]; }
          } else if (Array.isArray(raw)) {
            routes = raw as Route[];
          } else {
            routes = [defaultRoute];
          }

          return (
            <div key={field.name} className="config-field">
              <RouteEditor
                routes={routes}
                onChange={(updated) => updateConfig(field.name, updated)}
              />
            </div>
          );
        }

        // Schema editor
        if (field.field_type === "schema_editor") {
          const raw = config[field.name];
          let fields: SchemaField[];
          if (typeof raw === "string") {
            try { fields = JSON.parse(raw); } catch { fields = []; }
          } else if (Array.isArray(raw)) {
            fields = raw as SchemaField[];
          } else {
            fields = [];
          }

          return (
            <div key={field.name} className="config-field">
              <SchemaEditor
                fields={fields}
                onChange={(updated) => updateConfig(field.name, updated)}
              />
            </div>
          );
        }

        const val = (config[field.name] ?? field.default ?? "") as string;

        return (
          <div key={field.name} className="config-field">
            <label>
              {field.label}
              {field.required && " *"}
            </label>

            {field.field_type === "textarea" ? (
              <>
                <textarea
                  value={val}
                  placeholder={field.placeholder}
                  onChange={(e) => updateConfig(field.name, e.target.value)}
                />
                {field.name === "system_prompt" && stateVariables.length > 0 && (
                  <span className="config-hint">
                    Use {"{field_name}"} to reference state: {stateVariables.map(v => `{${v}}`).join(", ")}
                  </span>
                )}
              </>
            ) : field.field_type === "select" && field.options ? (
              <select
                value={val}
                onChange={(e) => updateConfig(field.name, e.target.value)}
              >
                {field.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={field.field_type === "number" ? "number" : "text"}
                value={val}
                placeholder={field.placeholder}
                onChange={(e) =>
                  updateConfig(
                    field.name,
                    field.field_type === "number"
                      ? parseFloat(e.target.value) || 0
                      : e.target.value
                  )
                }
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
