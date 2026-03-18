import type { NodeTypeMetadata } from "../types";
import { ICON_MAP } from "./nodes/AgentNode";

interface Props {
  nodeTypes: NodeTypeMetadata[];
}

export default function NodePalette({ nodeTypes }: Props) {
  const onDragStart = (e: React.DragEvent, nodeType: string) => {
    e.dataTransfer.setData("application/agentbuilder-node", nodeType);
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
              onDragStart={(e) => onDragStart(e, nt.type)}
            >
              <div
                className="palette-icon"
                style={{ background: nt.color }}
              >
                {ICON_MAP[nt.icon] ?? "?"}
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
