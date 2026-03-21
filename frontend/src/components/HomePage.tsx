import {
  Brain,
  GitBranch,
  Search,
  BarChart3,
  Rocket,
  MessageSquare,
  Save,
  Upload,
  FileCode,
  Shield,
  Workflow,
  ArrowRight,
} from "lucide-react";

interface Props {
  onGetStarted: () => void;
}

export default function HomePage({ onGetStarted }: Props) {
  return (
    <div className="home">
      {/* Hero */}
      <section className="home-hero">
        <div className="home-hero-badge">Visual Agent Builder</div>
        <h1>Build AI agents without writing code</h1>
        <p>
          Design, test, and deploy LangGraph agents on Databricks using a
          drag-and-drop interface. Connect LLMs, data retrieval, and routing
          logic — then deploy to a production serving endpoint in one click.
        </p>
        <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
          Start building
          <ArrowRight size={16} />
        </button>
      </section>

      {/* How it works */}
      <section className="home-section">
        <h2>How it works</h2>
        <div className="home-steps">
          <div className="home-step">
            <div className="home-step-num">1</div>
            <h3>Define your state model</h3>
            <p>
              Start by defining the data your agent works with — user input,
              retrieved context, analysis results. Each field flows through
              every step of your agent.
            </p>
          </div>
          <div className="home-step">
            <div className="home-step-num">2</div>
            <h3>Build your graph</h3>
            <p>
              Drag components onto the canvas and connect them. Each node
              performs one job — call an LLM, search a vector index, route
              based on conditions — and passes results to the next.
            </p>
          </div>
          <div className="home-step">
            <div className="home-step-num">3</div>
            <h3>Test in the playground</h3>
            <p>
              Open the Chat Playground to send messages to your agent and see
              how it responds. Inspect the execution trace and state at every
              step to debug and refine.
            </p>
          </div>
          <div className="home-step">
            <div className="home-step-num">4</div>
            <h3>Deploy to Databricks</h3>
            <p>
              One click logs your agent to MLflow, registers it in Unity
              Catalog, and creates a Model Serving endpoint — ready for
              production traffic.
            </p>
          </div>
        </div>
      </section>

      {/* Available components */}
      <section className="home-section">
        <h2>Available components</h2>
        <div className="home-cards">
          <div className="home-card">
            <div className="home-card-icon" style={{ background: "#8b5cf6" }}>
              <Brain size={18} />
            </div>
            <div>
              <h3>LLM</h3>
              <p>
                Call any Foundation Model endpoint on Databricks. Supports
                system prompts with state variable references, structured
                output, and temperature control.
              </p>
            </div>
          </div>
          <div className="home-card">
            <div className="home-card-icon" style={{ background: "#06b6d4" }}>
              <Search size={18} />
            </div>
            <div>
              <h3>Vector Search</h3>
              <p>
                Query a Databricks Vector Search index to retrieve relevant
                documents. Results are injected into the agent state for
                downstream LLM calls.
              </p>
            </div>
          </div>
          <div className="home-card">
            <div className="home-card-icon" style={{ background: "#f59e0b" }}>
              <BarChart3 size={18} />
            </div>
            <div>
              <h3>Genie Room</h3>
              <p>
                Ask natural-language questions against a Databricks Genie Room
                to get structured data answers from your tables.
              </p>
            </div>
          </div>
          <div className="home-card">
            <div className="home-card-icon" style={{ background: "#ef4444" }}>
              <GitBranch size={18} />
            </div>
            <div>
              <h3>Router</h3>
              <p>
                Branch your agent's flow based on state values. Supports
                boolean, string matching, and multi-way routing with
                fallback paths.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Toolbar reference */}
      <section className="home-section">
        <h2>Toolbar actions</h2>
        <div className="home-ref-grid">
          <div className="home-ref-item">
            <Save size={16} />
            <div>
              <strong>Save JSON</strong>
              <span>Export your graph config to a file for version control or sharing</span>
            </div>
          </div>
          <div className="home-ref-item">
            <Upload size={16} />
            <div>
              <strong>Load JSON</strong>
              <span>Import a previously saved graph to continue editing</span>
            </div>
          </div>
          <div className="home-ref-item">
            <FileCode size={16} />
            <div>
              <strong>Export Python</strong>
              <span>Generate a standalone Python file to run your agent outside this tool</span>
            </div>
          </div>
          <div className="home-ref-item">
            <MessageSquare size={16} />
            <div>
              <strong>Chat Playground</strong>
              <span>Test your agent with real conversations and inspect each step</span>
            </div>
          </div>
          <div className="home-ref-item">
            <Rocket size={16} />
            <div>
              <strong>Deploy</strong>
              <span>Log to MLflow, register in Unity Catalog, and create a serving endpoint</span>
            </div>
          </div>
        </div>
      </section>

      {/* Permissions */}
      <section className="home-section">
        <h2>Required permissions</h2>
        <p className="home-section-desc">
          To build and deploy agents, you'll need the following access in your
          Databricks workspace. Contact your workspace admin if any of these
          are missing.
        </p>
        <div className="home-perms">
          <div className="home-perm">
            <Shield size={16} />
            <div>
              <strong>Foundation Model endpoints</strong>
              <span>CAN QUERY access to the serving endpoints your LLM nodes reference</span>
            </div>
          </div>
          <div className="home-perm">
            <Search size={16} />
            <div>
              <strong>Vector Search indexes</strong>
              <span>CAN USE access to any Vector Search indexes your agent queries</span>
            </div>
          </div>
          <div className="home-perm">
            <BarChart3 size={16} />
            <div>
              <strong>Genie Rooms</strong>
              <span>CAN RUN access to Genie Rooms used in your agent flow</span>
            </div>
          </div>
          <div className="home-perm">
            <Workflow size={16} />
            <div>
              <strong>Unity Catalog</strong>
              <span>CREATE MODEL permission on the catalog and schema where you deploy</span>
            </div>
          </div>
          <div className="home-perm">
            <Rocket size={16} />
            <div>
              <strong>Model Serving</strong>
              <span>CAN MANAGE permission to create or update serving endpoints</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
