import { useState, useEffect, useCallback, useRef } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Home, Hammer, Trash2, CloudDownload, Save, Upload, MessageSquare, Rocket, Sparkles, Settings, Package, X, HelpCircle, CakeSlice } from "lucide-react";
import Canvas from "./components/Canvas";
import NodePalette from "./components/NodePalette";
import StateModelModal from "./components/StateModelModal";
import StatePanel from "./components/StatePanel";
import ChatPlayground from "./components/ChatPlayground";
import DeployModal from "./components/DeployModal";
import HomePage from "./components/HomePage";
import BuilderWalkthrough from "./components/BuilderWalkthrough";
import AIChatDropdown from "./components/AIChatDropdown";
import SetupPage from "./components/SetupPage";
import ModelsPage from "./components/ModelsPage";
import { StateProvider } from "./StateContext";
import { fetchNodeTypes, fetchModels, getSetupStatus } from "./api";
import type { NodeTypeMetadata, GraphDef, StateFieldDef, SetupStatusResponse, ModelInfo } from "./types";

type AppView = "home" | "builder" | "models" | "setup";

export default function App() {
  const [nodeTypes, setNodeTypes] = useState<NodeTypeMetadata[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [graphGetter, setGraphGetter] = useState<(() => GraphDef) | null>(null);
  const [stateFields, setStateFields] = useState<StateFieldDef[]>([
    { name: "input", type: "str", description: "The initial input", sub_fields: [] },
  ]);
  const [showStateModal, setShowStateModal] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [showAIChat, setShowAIChat] = useState(false);
  const aiChatWrapperRef = useRef<HTMLDivElement>(null);
  const [showDeploy, setShowDeploy] = useState(false);
  const [showImportJson, setShowImportJson] = useState(false);
  const [importJsonInput, setImportJsonInput] = useState("");
  const [importJsonError, setImportJsonError] = useState("");
  const [importJsonPreview, setImportJsonPreview] = useState<GraphDef | null>(null);
  const [graphImporter, setGraphImporter] = useState<((g: GraphDef) => void) | null>(null);
  const [view, setView] = useState<AppView>("home");
  const [showWalkthrough, setShowWalkthrough] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [setupStatus, setSetupStatus] = useState<SetupStatusResponse | null>(null);
  const [experimentPath, setExperimentPath] = useState<string | null>(null);
  const [cachedModels, setCachedModels] = useState<ModelInfo[] | null>(null);
  const [modelsLoading, setModelsLoading] = useState(false);

  const refreshModels = useCallback(() => {
    setModelsLoading(true);
    fetchModels()
      .then((res) => setCachedModels(res.models))
      .catch(console.error)
      .finally(() => setModelsLoading(false));
  }, []);

  const stateVariableNames = stateFields.flatMap((f) => {
    const paths = [f.name];
    if ((f.type === "structured" || f.type === "vector_search_filter") && f.sub_fields?.length) {
      for (const sf of f.sub_fields) {
        if (sf.name) paths.push(`${f.name}.${sf.name}`);
      }
    }
    return paths;
  });
  const stateFieldsRef = useRef(stateFields);
  stateFieldsRef.current = stateFields;
  const nodesUpdaterRef = useRef<((fn: (nodes: any[]) => any[]) => void) | null>(null);

  useEffect(() => {
    fetchNodeTypes().then(setNodeTypes).catch(console.error);
    getSetupStatus()
      .then((status) => {
        setSetupStatus(status);
        if (status.setup_complete && status.experiment_path) {
          setExperimentPath(status.experiment_path);
        }
      })
      .catch(console.error);
  }, []);

  const addField = useCallback((field: StateFieldDef) => {
    setStateFields((prev) => {
      if (prev.some((f) => f.name === field.name)) return prev;
      return [...prev, field];
    });
  }, []);

  const removeField = useCallback((name: string) => {
    setStateFields((prev) => prev.filter((f) => f.name !== name));
  }, []);

  const renameField = useCallback((oldName: string, newName: string) => {
    if (!newName || oldName === newName) return;
    setStateFields((prev) =>
      prev.map((f) => (f.name === oldName ? { ...f, name: newName } : f))
    );
    // Cascade: update all node references
    const updater = nodesUpdaterRef.current;
    if (updater) {
      updater((nodes) =>
        nodes.map((n) => {
          let changed = false;
          const data = { ...n.data };

          if (data.writes_to === oldName) {
            data.writes_to = newName;
            changed = true;
          }

          if (data.config) {
            const config = { ...data.config } as Record<string, unknown>;
            for (const key of Object.keys(config)) {
              if (config[key] === oldName) {
                config[key] = newName;
                changed = true;
              }
              // Replace {oldName} references in string values (e.g. system_prompt)
              if (typeof config[key] === "string" && (config[key] as string).includes(`{${oldName}}`)) {
                config[key] = (config[key] as string).split(`{${oldName}}`).join(`{${newName}}`);
                changed = true;
              }
            }
            if (changed) data.config = config;
          }

          return changed ? { ...n, data } : n;
        })
      );
    }
  }, []);

  const handleSaveJson = useCallback(() => {
    if (!graphGetter) return;
    const graph = graphGetter();
    graph.state_fields = stateFieldsRef.current;
    const json = JSON.stringify(graph, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "graph.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [graphGetter]);

  const handleLoadJson = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || !graphImporter) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const graph = JSON.parse(reader.result as string) as GraphDef;
          if (graph.state_fields?.length) {
            setStateFields(graph.state_fields);
          }
          graphImporter(graph);
          setShowStateModal(false);
          setView("builder");
        } catch (err) {
          console.error("Failed to parse graph JSON:", err);
        }
      };
      reader.readAsText(file);
      e.target.value = "";
    },
    [graphImporter]
  );

  const openBuilder = useCallback(() => {
    setView("builder");
  }, []);

  const handleClearAll = useCallback(() => {
    if (!graphImporter) return;
    graphImporter({ nodes: [], edges: [], state_fields: [], output_fields: [] });
    setStateFields([
      { name: "input", type: "str", description: "The initial input", sub_fields: [] },
    ]);
    setSelectedNodeId(null);
  }, [graphImporter]);

  const handleImportJsonParse = useCallback(() => {
    setImportJsonError("");
    setImportJsonPreview(null);
    try {
      const parsed = JSON.parse(importJsonInput.trim());
      if (!parsed.nodes || !parsed.edges) {
        setImportJsonError("JSON must contain \"nodes\" and \"edges\" fields.");
        return;
      }
      setImportJsonPreview(parsed as GraphDef);
    } catch {
      setImportJsonError("Invalid JSON.");
    }
  }, [importJsonInput]);

  const handleImportJsonAccept = useCallback(() => {
    if (!importJsonPreview || !graphImporter) return;
    if (importJsonPreview.state_fields?.length) {
      setStateFields(importJsonPreview.state_fields);
    }
    graphImporter(importJsonPreview);
    setShowImportJson(false);
    setImportJsonInput("");
    setImportJsonPreview(null);
    setView("builder");
  }, [graphImporter, importJsonPreview]);

  return (
    <ReactFlowProvider>
      <StateProvider value={{ names: stateVariableNames, fields: stateFields, addField, removeField, renameField }}>
      <div className={`app${showStateModal && view === "builder" ? " app-blurred" : ""}`}>
        <header className="header">
          <div className="header-left">
            <div className="header-logo">
              <CakeSlice size={20} className="header-logo-icon" />
              <span>AgentSweet</span>
            </div>
          </div>
          {view === "builder" && (
            <div className="header-actions">
              <div className="header-group">
                <button className="btn btn-ghost btn-with-icon" onClick={handleSaveJson}>
                  <Save size={14} />
                  Save
                </button>
                <button className="btn btn-ghost btn-with-icon" onClick={() => fileInputRef.current?.click()}>
                  <Upload size={14} />
                  Load
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json"
                  style={{ display: "none" }}
                  onChange={handleLoadJson}
                />
                <button className="btn btn-ghost btn-with-icon" onClick={() => setShowImportJson(true)} title="Import graph from JSON (e.g. from an MLflow run artifact)">
                  <CloudDownload size={14} />
                  Import
                </button>
                <button className="btn btn-ghost btn-danger-ghost" onClick={handleClearAll}>
                  <Trash2 size={14} />
                  Clear All
                </button>
                <button className="btn btn-ghost btn-with-icon" onClick={() => setShowWalkthrough(true)} title="Take a guided tour">
                  <HelpCircle size={14} />
                  Tour
                </button>
              </div>
              <div className="header-divider" />
              <div className="header-group">
                <button className="btn btn-playground btn-with-icon" onClick={() => setShowChat(true)}>
                  <MessageSquare size={14} />
                  Playground
                </button>
                <button className="btn btn-deploy btn-with-icon" onClick={() => setShowDeploy(true)}>
                  <Rocket size={14} />
                  Deploy
                </button>
              </div>
            </div>
          )}
        </header>

        <div className="main">
          <nav className="nav-rail" onKeyDown={(e) => e.stopPropagation()}>
            <button
              className={`nav-rail-btn${view === "home" ? " active" : ""}`}
              onClick={() => setView("home")}
              title="Home"
            >
              <Home size={18} />
              <span>Home</span>
            </button>
            <button
              className={`nav-rail-btn${view === "builder" ? " active" : ""}`}
              onClick={openBuilder}
              title="Builder"
            >
              <Hammer size={18} />
              <span>Builder</span>
            </button>
            <button
              className={`nav-rail-btn${view === "models" ? " active" : ""}`}
              onClick={() => setView("models")}
              title="Models"
            >
              <Package size={18} />
              <span>Models</span>
            </button>
            <button
              className={`nav-rail-btn${view === "setup" ? " active" : ""}`}
              onClick={() => setView("setup")}
              title="Setup"
            >
              <Settings size={18} />
              <span>Setup</span>
            </button>
          </nav>

          {view === "home" && (
            <HomePage
              onGetStarted={openBuilder}
              onTakeTour={() => { setView("builder"); setShowWalkthrough(true); }}
              userEmail={setupStatus?.user_email ?? ""}
            />
          )}

          {view === "models" && (
            <ModelsPage
              graphImporter={graphImporter}
              setStateFields={setStateFields}
              onSwitchToBuilder={() => setView("builder")}
              cachedModels={cachedModels}
              modelsLoading={modelsLoading}
              onRefresh={refreshModels}
            />
          )}

          {view === "setup" && (
            <SetupPage
              setupStatus={setupStatus}
              onSetupComplete={(path) => {
                setExperimentPath(path);
                setSetupStatus((prev) =>
                  prev ? { ...prev, setup_complete: true, experiment_path: path } : prev
                );
              }}
            />
          )}

          <div className="builder-container" style={{ display: view === "builder" ? "contents" : "none" }}>
            <div className="left-panel" onKeyDown={(e) => e.stopPropagation()}>
              <StatePanel
                fields={stateFields}
                onChange={setStateFields}
                onOpenModal={() => setShowStateModal(true)}
              />
              <NodePalette nodeTypes={nodeTypes} />
            </div>

            <Canvas
              nodeTypes={nodeTypes}
              stateVariableNames={stateVariableNames}
              selectedNodeId={selectedNodeId}
              onNodeSelect={setSelectedNodeId}
              onGraphReady={(getter) => setGraphGetter(() => getter)}
              onImportReady={(importer) => setGraphImporter(() => importer)}
              onNodesUpdaterReady={(updater) => { nodesUpdaterRef.current = updater; }}
              visible={view === "builder"}
            />
          </div>

          {showWalkthrough && view === "builder" && (
            <BuilderWalkthrough onDismiss={() => setShowWalkthrough(false)} />
          )}
        </div>
      </div>

      {/* Floating AI Chat bubble */}
      {view === "builder" && (
        <div className="ai-chat-fab-container" ref={aiChatWrapperRef}>
          {showAIChat && (
            <AIChatDropdown
              graphGetter={graphGetter}
              graphImporter={graphImporter}
              stateFields={stateFields}
              setStateFields={setStateFields}
              onSwitchToBuilder={() => setView("builder")}
              onClose={() => setShowAIChat(false)}
              wrapperRef={aiChatWrapperRef}
            />
          )}
          <button
            className={`ai-chat-fab${showAIChat ? " ai-chat-fab-active" : ""}`}
            onClick={() => setShowAIChat((v) => !v)}
            title="AI Chat"
          >
            {showAIChat ? <X size={20} /> : <Sparkles size={20} />}
          </button>
        </div>
      )}

      {showStateModal && (
        <StateModelModal
          fields={stateFields}
          onChange={setStateFields}
          onClose={() => setShowStateModal(false)}
        />
      )}

      {showChat && (
        <ChatPlayground
          graphGetter={graphGetter}
          stateFieldsRef={stateFieldsRef}
          onClose={() => setShowChat(false)}
        />
      )}

      {showDeploy && (
        <DeployModal
          graphGetter={graphGetter}
          stateFieldsRef={stateFieldsRef}
          onClose={() => { setShowDeploy(false); refreshModels(); }}
          defaultExperimentPath={experimentPath ?? ""}
          onGoToSetup={() => { setShowDeploy(false); setView("setup"); }}
        />
      )}

      {/* Import graph JSON modal */}
      {showImportJson && (
        <div className="modal-overlay" onClick={() => { setShowImportJson(false); setImportJsonError(""); setImportJsonPreview(null); setImportJsonInput(""); }}>
          <div className="modal-card" style={{ width: importJsonPreview ? 600 : 500 }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h1>Import Graph JSON</h1>
              {!importJsonPreview && (
                <p>
                  Paste the graph definition JSON below. You can copy this from
                  an MLflow run artifact or a saved graph file.
                </p>
              )}
            </div>
            <div className="modal-body">
              {!importJsonPreview ? (
                <>
                  <textarea
                    className="preview-input"
                    style={{ width: "100%", minHeight: 200, fontFamily: "monospace", fontSize: "0.8rem", resize: "vertical" }}
                    value={importJsonInput}
                    placeholder='{"nodes": [...], "edges": [...], ...}'
                    onChange={(e) => setImportJsonInput(e.target.value)}
                    autoFocus
                  />
                  {importJsonError && (
                    <pre className="result-error" style={{ marginTop: "0.5rem", fontSize: "0.75rem" }}>
                      {importJsonError}
                    </pre>
                  )}
                </>
              ) : (
                <div className="mlflow-load-preview">
                  <div className="mlflow-load-success">Valid graph definition</div>
                  <div className="mlflow-load-meta">
                    <div className="mlflow-load-row">
                      <span className="mlflow-load-label">Nodes</span>
                      <span>{importJsonPreview.nodes?.length ?? 0}</span>
                    </div>
                    <div className="mlflow-load-row">
                      <span className="mlflow-load-label">State fields</span>
                      <span>{importJsonPreview.state_fields?.map((f: { name: string }) => f.name).join(", ") || "none"}</span>
                    </div>
                  </div>
                  <details className="mlflow-load-json-details">
                    <summary>Graph JSON</summary>
                    <pre className="mlflow-load-json">
                      {JSON.stringify(importJsonPreview, null, 2)}
                    </pre>
                  </details>
                </div>
              )}
            </div>
            <div className="modal-footer">
              {!importJsonPreview ? (
                <>
                  <button
                    className="btn btn-ghost"
                    onClick={() => { setShowImportJson(false); setImportJsonError(""); setImportJsonInput(""); }}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={handleImportJsonParse}
                    disabled={!importJsonInput.trim()}
                  >
                    Parse
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="btn btn-ghost"
                    onClick={() => setImportJsonPreview(null)}
                  >
                    Back
                  </button>
                  <button className="btn btn-primary" onClick={handleImportJsonAccept}>
                    Import
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      </StateProvider>
    </ReactFlowProvider>
  );
}
