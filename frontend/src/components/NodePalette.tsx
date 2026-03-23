import type { NodeTypeMetadata } from "../types";
import { NodeIcon } from "./NodeIcon";

interface Props {
  nodeTypes: NodeTypeMetadata[];
}

let toolIdCounter = 0;

export default function NodePalette({ nodeTypes }: Props) {
  const onDragStart = (e: React.DragEvent, nt: NodeTypeMetadata) => {
    // Always set the standard node type for canvas drops
    e.dataTransfer.setData("application/agentbuilder-node", nt.type);

    // If tool-compatible, also set tool data so the LLM drop zone can capture it
    if (nt.tool_compatible) {
      const toolData = JSON.stringify({
        id: `tool_${++toolIdCounter}`,
        type: nt.type,
        display_name: nt.display_name,
        icon: nt.icon,
        color: nt.color,
        config: {},
      });
      e.dataTransfer.setData("application/agentbuilder-tool", toolData);
    }

    e.dataTransfer.effectAllowed = "move";
  };

  const grouped = nodeTypes.reduce<Record<string, NodeTypeMetadata[]>>(
    (acc, nt) => {
      const cat = nt.category || "general";
      (acc[cat] ??= []).push(nt);
      return acc;
    },
    {}
  );

  return (
    <div className="palette">
      <h2>Components</h2>
      {Object.entries(grouped).map(([category, types]) => (
        <div key={category}>
          <h2>{category}</h2>
          {types.map((nt) => (
            <div
              key={nt.type}
              className="palette-item"
              draggable
              onDragStart={(e) => onDragStart(e, nt)}
            >
              <div
                className="palette-icon"
                style={{ background: nt.color }}
              >
                <NodeIcon name={nt.icon} size={14} />
              </div>
              <div>
                <div className="palette-label">{nt.display_name}</div>
                <div className="palette-desc">{nt.description}</div>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
