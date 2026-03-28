import { useCallback } from "react";
import { Handle, Position, useReactFlow } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { useStateVars } from "../../StateContext";

export default function SentinelNode({ id, data }: NodeProps) {
  const stateVarNames = useStateVars();
  const kind = (data.kind as string) ?? "start"; // "start" | "end"
  const isStart = kind === "start";
  const { updateNodeData } = useReactFlow();

  const outputFields = (data.output_fields as string[]) ?? [];

  const toggleField = useCallback(
    (field: string) => {
      const current = (data.output_fields as string[]) ?? [];
      const next = current.includes(field)
        ? current.filter((f) => f !== field)
        : [...current, field];
      updateNodeData(id, { output_fields: next });
    },
    [id, data.output_fields, updateNodeData],
  );

  return (
    <div className={`sentinel-node sentinel-${kind}`}>
      {!isStart && <Handle type="target" position={Position.Top} />}

      <div className="sentinel-label">{isStart ? "START" : "END"}</div>

      {isStart ? (
        <div className="sentinel-fields">
          <span className="sentinel-field">input</span>
        </div>
      ) : (
        <div className="sentinel-fields">
          {stateVarNames.map((v) => {
            const selected = outputFields.length === 0 || outputFields.includes(v);
            return (
              <span
                key={v}
                className={`sentinel-field sentinel-field-toggle${selected ? " sentinel-field-selected" : ""}`}
                onClick={() => toggleField(v)}
              >
                {v}
              </span>
            );
          })}
        </div>
      )}

      {isStart && <Handle type="source" position={Position.Bottom} />}
    </div>
  );
}
