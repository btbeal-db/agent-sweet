import { useCallback, useRef, useEffect, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import AgentNode from "./nodes/AgentNode";
import type { NodeTypeMetadata, GraphDef } from "../types";

interface Props {
  nodeTypes: NodeTypeMetadata[];
  stateVariableNames: string[];
  onNodeSelect: (nodeId: string | null) => void;
  onGraphReady: (getter: () => GraphDef) => void;
}

let nodeIdCounter = 0;

export default function Canvas({ nodeTypes, stateVariableNames, onNodeSelect, onGraphReady }: Props) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const customNodeTypes = useMemo(() => ({ agentNode: AgentNode }), []);

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds: Edge[]) => addEdge({ ...params, type: "smoothstep" }, eds));
    },
    [setEdges]
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect(node.id);
    },
    [onNodeSelect]
  );

  const onPaneClick = useCallback(() => {
    onNodeSelect(null);
  }, [onNodeSelect]);

  // Expose a function to serialize the current graph
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  nodesRef.current = nodes;
  edgesRef.current = edges;

  useEffect(() => {
    onGraphReady(() => {
      const graphNodes = nodesRef.current.map((n) => ({
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

  // Handle drop from palette
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

      // Build default config from field definitions
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

      // Default writes_to: first non-user_input state variable, or ""
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

  return (
    <div className="canvas-wrapper" ref={reactFlowWrapper}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
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
          style={{ background: "#1a1d27" }}
          maskColor="rgba(0,0,0,0.4)"
        />
      </ReactFlow>
    </div>
  );
}
