import { X } from "lucide-react";
import { NodeIcon } from "../NodeIcon";
import type { AttachedTool } from "../../types";

interface Props {
  tool: AttachedTool;
  onClick: () => void;
  onRemove: () => void;
}

export default function ToolChip({ tool, onClick, onRemove }: Props) {
  return (
    <div className="tool-chip" onClick={(e) => { e.stopPropagation(); onClick(); }}>
      <div className="tool-chip-icon" style={{ background: tool.color }}>
        <NodeIcon name={tool.icon} size={11} />
      </div>
      <span className="tool-chip-label">{tool.display_name}</span>
      <button
        className="tool-chip-remove"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
      >
        <X size={10} />
      </button>
    </div>
  );
}
