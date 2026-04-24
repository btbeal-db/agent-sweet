import {
  Brain,
  GitBranch,
  Search,
  BarChart3,
  Rocket,
  ArrowRight,
  FunctionSquare,
  User,
  Wrench,
  Workflow,
  History,
  Server,
  Compass,
  Lightbulb,
  ChevronRight,
} from "lucide-react";

interface Props {
  onGetStarted: () => void;
  onTakeTour: () => void;
  userEmail: string;
}

function firstName(email: string): string {
  if (!email) return "";
  const local = email.split("@")[0] ?? "";
  const part = local.split(".")[0] ?? local;
  return part.charAt(0).toUpperCase() + part.slice(1);
}

export default function HomePage({ onGetStarted, onTakeTour, userEmail }: Props) {
  const name = firstName(userEmail);

  return (
    <div className="home">
      {/* ── Hero ──────────────────────────────────────────────────── */}
      <section className="home-hero">
        <h1>{name ? `Welcome back, ${name}` : "AgentSweet"}</h1>
        <p className="home-hero-sub">
          Design, test, and deploy AI agents on Databricks — no code required.
        </p>
        <div className="home-hero-actions">
          <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
            Start Building
            <ArrowRight size={16} />
          </button>
          <button className="btn btn-ghost btn-lg" onClick={onTakeTour}>
            <Compass size={16} />
            Take the Tour
          </button>
        </div>
      </section>

      {/* ── Quick Start ───────────────────────────────────────────── */}
      <section className="home-section">
        <h2>Quick start</h2>
        <div className="home-steps-inline">
          <div className="home-step-inline">
            <span className="home-step-num">1</span>
            <div>
              <strong>Drop nodes</strong>
              <span>Drag components from the palette onto the canvas</span>
            </div>
          </div>
          <ChevronRight size={16} className="home-step-arrow" />
          <div className="home-step-inline">
            <span className="home-step-num">2</span>
            <div>
              <strong>Connect & configure</strong>
              <span>Wire nodes together and set up each one</span>
            </div>
          </div>
          <ChevronRight size={16} className="home-step-arrow" />
          <div className="home-step-inline">
            <span className="home-step-num">3</span>
            <div>
              <strong>Test & deploy</strong>
              <span>Chat in the Playground, then deploy to a serving endpoint</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Node Types ────────────────────────────────────────────── */}
      <section className="home-section">
        <h2>Components</h2>
        <div className="home-node-grid">
          <NodeCard icon={<Brain size={16} />} color="#7C52D9" name="LLM" desc="Call any Foundation Model endpoint. Supports tools, structured output, and conversation." />
          <NodeCard icon={<Search size={16} />} color="#06b6d4" name="Vector Search" desc="Query a VS index for relevant documents. Standalone or as an LLM tool." />
          <NodeCard icon={<BarChart3 size={16} />} color="#f59e0b" name="Genie" desc="Natural-language queries against a Genie space for structured data." />
          <NodeCard icon={<FunctionSquare size={16} />} color="#7C52D9" name="UC Function" desc="Execute Unity Catalog functions as explicit steps or LLM tools." />
          <NodeCard icon={<Server size={16} />} color="#06b6d4" name="MCP Server" desc="Connect to Databricks MCP servers to expose external tools." />
          <NodeCard icon={<GitBranch size={16} />} color="#D65454" name="Router" desc="Branch the flow based on state values. Bool, keyword, or multi-way." />
          <NodeCard icon={<User size={16} />} color="#f59e0b" name="Human Input" desc="Pause the agent and prompt the user for input before continuing." />
        </div>
      </section>

      {/* ── Agent Patterns ────────────────────────────────────────── */}
      <section className="home-section">
        <h2>Agent patterns</h2>
        <div className="home-patterns">
          <div className="home-pattern">
            <div className="home-pattern-header">
              <Workflow size={18} />
              <h3>Prescriptive Graph</h3>
            </div>
            <p>
              Fixed sequence — retrieve, process, respond. You control every step.
            </p>
            <div className="home-pattern-diagram">
              <code>START &rarr; Vector Search &rarr; LLM &rarr; END</code>
            </div>
          </div>
          <div className="home-pattern">
            <div className="home-pattern-header">
              <Wrench size={18} />
              <h3>Tool Calling</h3>
            </div>
            <p>
              Drop tools onto an LLM node. The model decides what to call and loops
              until it has the answer.
            </p>
            <div className="home-pattern-diagram">
              <code>START &rarr; LLM [+ tools] &rarr; END</code>
            </div>
          </div>
          <div className="home-pattern">
            <div className="home-pattern-header">
              <History size={18} />
              <h3>Conversational</h3>
            </div>
            <p>
              Enable message history on any LLM node for multi-turn memory.
              Pair with Lakebase for persistence.
            </p>
            <div className="home-pattern-diagram">
              <code>START &rarr; LLM (conversational) &rarr; END</code>
            </div>
          </div>
        </div>
      </section>

      {/* ── Key Concepts ──────────────────────────────────────────── */}
      <section className="home-section">
        <h2>Key concepts</h2>
        <div className="home-concepts">
          <details className="home-concept">
            <summary>
              <Lightbulb size={14} />
              State Model
            </summary>
            <p>
              Every agent has a shared state — typed fields (str, int, float, bool,
              list[str], structured) that nodes read and write. Each node's "writes to"
              setting controls which field it updates. The <code>messages</code> field
              is special — it uses LangGraph's add_messages reducer for conversation
              history. Reference state fields in LLM system prompts
              with <code>{"{field_name}"}</code> notation — structured fields support
              dot notation like <code>{"{field.subfield}"}</code>.
            </p>
          </details>
          <details className="home-concept">
            <summary>
              <Wrench size={14} />
              Tools & Tool Calling
            </summary>
            <p>
              Drop a Vector Search, Genie, UC Function, or MCP node directly onto an
              LLM node to attach it as a tool. The LLM autonomously decides when to call
              each tool and loops until it has enough information. You can also wire these
              nodes as standalone graph steps for deterministic flows.
            </p>
          </details>
          <details className="home-concept">
            <summary>
              <Rocket size={14} />
              Deployment
            </summary>
            <p>
              Deploy logs your agent to MLflow, optionally registers it in Unity Catalog,
              and creates a serving endpoint. Three modes: Log Only, Log &amp; Register, or
              Full Deploy. <strong>Preview uses your workspace credentials automatically</strong> — a
              PAT is only needed for deploy (UC registration + serving endpoint creation).
            </p>
          </details>
        </div>
      </section>

      {/* ── Tips ──────────────────────────────────────────────────── */}
      <section className="home-section home-tips-section">
        <h2>Tips</h2>
        <ul className="home-tips">
          <li>Every path in your graph must start from START and end at END.</li>
          <li>Only Router nodes can have multiple outgoing edges — all other nodes get exactly one.</li>
          <li>Use the AI Chat bubble (bottom-right) to generate graphs from natural language.</li>
          <li>Save your graph often — it's just JSON you can version control.</li>
          <li>Open the Playground to see execution traces, tool calls, and MLflow spans at each step.</li>
        </ul>
      </section>
    </div>
  );
}

function NodeCard({ icon, color, name, desc }: { icon: JSX.Element; color: string; name: string; desc: string }) {
  return (
    <div className="home-node-card">
      <div className="home-node-card-icon" style={{ background: color }}>
        {icon}
      </div>
      <strong>{name}</strong>
      <span>{desc}</span>
    </div>
  );
}
