import { useCallback, useRef, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { X } from "lucide-react";

import AgentNode from "./nodes/AgentNode";
import SentinelNode from "./nodes/SentinelNode";
import ConfigPanel from "./ConfigPanel";
import type { NodeTypeMetadata, GraphDef } from "../types";

const START_ID = "__start__";
const END_ID = "__end__";

const INITIAL_NODES: Node[] = [
  {
    id: START_ID,
    type: "sentinelNode",
    position: { x: 250, y: 30 },
    data: { kind: "start" },
    deletable: false,
  },
  {
    id: END_ID,
    type: "sentinelNode",
    position: { x: 250, y: 500 },
    data: { kind: "end" },
    deletable: false,
  },
];

interface Props {
  nodeTypes: NodeTypeMetadata[];
  stateVariableNames: string[];
  onNodeSelect: (nodeId: string | null) => void;
  selectedNodeId: string | null;
  onGraphReady: (getter: () => GraphDef) => void;
  onImportReady?: (importer: (graph: GraphDef) => void) => void;
}

let nodeIdCounter = 0;

/** Compute screen-space position for the popover anchored to a node. */
function usePopoverPosition(selectedNodeId: string | null, wrapperRef: React.RefObject<HTMLDivElement | null>) {
  const { getNode, flowToScreenPosition } = useReactFlow();
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!selectedNodeId) { setPos(null); return; }
    const update = () => {
      const node = getNode(selectedNodeId);
      const wrapper = wrapperRef.current;
      if (!node || !wrapper) { setPos(null); return; }
      const wrapperRect = wrapper.getBoundingClientRect();
      // Anchor to the right edge of the node, vertically centered
      const screenPos = flowToScreenPosition({
        x: node.position.x + (node.measured?.width ?? 160),
        y: node.position.y,
      });
      setPos({
        x: screenPos.x - wrapperRect.left + 12,
        y: screenPos.y - wrapperRect.top,
      });
    };
    update();
    // Update on short interval to track panning/zooming
    const id = setInterval(update, 60);
    return () => clearInterval(id);
  }, [selectedNodeId, getNode, flowToScreenPosition, wrapperRef]);

  return pos;
}

export default function Canvas({ nodeTypes, stateVariableNames, onNodeSelect, selectedNodeId, onGraphReady, onImportReady }: Props) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const customNodeTypes = useMemo(
    () => ({ agentNode: AgentNode, sentinelNode: SentinelNode }),
    []
  );

  const SENTINEL_IDS = new Set([START_ID, END_ID]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const safe = changes.filter(
        (c) => c.type !== "remove" || !SENTINEL_IDS.has(c.id)
      );
      const removedIds = safe
        .filter((c) => c.type === "remove")
        .map((c) => c.id);
      if (removedIds.length > 0) {
        onNodeSelect(null);
      }
      onNodesChange(safe);
    },
    [onNodesChange, onNodeSelect]
  );

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds: Edge[]) => addEdge({ ...params, type: "smoothstep" }, eds));
    },
    [setEdges]
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (SENTINEL_IDS.has(node.id)) return;
      onNodeSelect(node.id);
    },
    [onNodeSelect]
  );

  const onPaneClick = useCallback(() => {
    onNodeSelect(null);
  }, [onNodeSelect]);

  // Expose graph serialization
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  nodesRef.current = nodes;
  edgesRef.current = edges;

  useEffect(() => {
    onGraphReady(() => {
      const graphNodes = nodesRef.current
        .filter((n) => n.id !== START_ID && n.id !== END_ID)
        .map((n) => ({
          id: n.id,
          type: (n.data.nodeType as string) ?? "llm",
          writes_to: (n.data.writes_to as string) ?? "",
          config: (n.data.config as Record<string, unknown>) ?? {},
          position: n.position,
        }));
      const graphEdges = edgesRef.current.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        source_handle: e.sourceHandle ?? null,
      }));
      return { nodes: graphNodes, edges: graphEdges, state_fields: [] } as GraphDef;
    });
  }, [onGraphReady]);

  // Import handler
  useEffect(() => {
    if (!onImportReady) return;
    onImportReady((graph: GraphDef) => {
      const newNodes: Node[] = [...INITIAL_NODES];
      for (const gn of graph.nodes) {
        const meta = nodeTypes.find((nt) => nt.type === gn.type);
        nodeIdCounter = Math.max(nodeIdCounter, parseInt(gn.id.replace(/\D/g, "") || "0", 10));
        newNodes.push({
          id: gn.id,
          type: "agentNode",
          position: gn.position ?? { x: 250, y: 200 },
          data: {
            nodeType: gn.type,
            display_name: meta?.display_name ?? gn.type,
            description: meta?.description ?? "",
            icon: meta?.icon ?? "",
            color: meta?.color ?? "#6366f1",
            config_fields: meta?.config_fields ?? [],
            is_router: gn.type === "router",
            writes_to: gn.writes_to ?? "",
            config: gn.config ?? {},
          },
        });
      }
      const newEdges: Edge[] = graph.edges.map((ge) => ({
        id: ge.id,
        source: ge.source,
        target: ge.target,
        sourceHandle: ge.source_handle ?? undefined,
        type: "smoothstep",
      }));
      setNodes(newNodes);
      setEdges(newEdges);
    });
  }, [onImportReady, nodeTypes, setNodes, setEdges]);

  // Drop from palette
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const nodeType = e.dataTransfer.getData("application/agentbuilder-node");
      if (!nodeType) return;

      const meta = nodeTypes.find((nt) => nt.type === nodeType);
      if (!meta) return;

      const wrapperBounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!wrapperBounds) return;

      const position = {
        x: e.clientX - wrapperBounds.left - 80,
        y: e.clientY - wrapperBounds.top - 20,
      };

      const defaultConfig: Record<string, unknown> = {};
      for (const field of meta.config_fields) {
        if (field.default != null) {
          if (field.field_type === "route_editor" && typeof field.default === "string") {
            try { defaultConfig[field.name] = JSON.parse(field.default); } catch { defaultConfig[field.name] = field.default; }
          } else {
            defaultConfig[field.name] = field.default;
          }
        }
      }

      const defaultWritesTo = meta.type === "router"
        ? ""
        : stateVariableNames.find((v) => v !== "user_input") ?? "";

      const newNode: Node = {
        id: `node_${++nodeIdCounter}`,
        type: "agentNode",
        position,
        data: {
          nodeType: meta.type,
          display_name: meta.display_name,
          description: meta.description,
          icon: meta.icon,
          color: meta.color,
          config_fields: meta.config_fields,
          is_router: meta.type === "router",
          writes_to: defaultWritesTo,
          config: defaultConfig,
        },
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [nodeTypes, setNodes]
  );

  // Floating popover position
  const popoverPos = usePopoverPosition(selectedNodeId, reactFlowWrapper);

  return (
    <div className="canvas-wrapper" ref={reactFlowWrapper}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={customNodeTypes}
        fitView
        defaultEdgeOptions={{ type: "smoothstep" }}
      >
        <Background />
        <Controls />
        <MiniMap
          style={{ background: "#12151c" }}
          maskColor="rgba(0,0,0,0.4)"
        />
      </ReactFlow>

      {/* Floating config popover */}
      {selectedNodeId && popoverPos && (
        <div
          className="config-popover"
          style={{ left: popoverPos.x, top: popoverPos.y }}
          onKeyDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <button className="config-popover-close" onClick={() => onNodeSelect(null)}>
            <X size={14} />
          </button>
          <ConfigPanel
            selectedNodeId={selectedNodeId}
            nodeTypes={nodeTypes}
            stateVariables={stateVariableNames}
          />
        </div>
      )}
    </div>
  );
}
