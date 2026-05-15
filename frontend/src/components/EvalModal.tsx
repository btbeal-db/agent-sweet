import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, ClipboardList, Loader2, Play, Plus, Sparkles, Trash2, XCircle } from "lucide-react";
import {
  generateEvalDataset,
  runEval,
  suggestScorers,
} from "../api";
import type {
  EvalRow,
  EvalRowResult,
  EvalRunResponse,
  GraphDef,
  ScorerMeta,
} from "../types";
import SearchableSelect from "./SearchableSelect";

export interface RowDraft {
  id: number;
  input: string;
  expected: string;
}

export interface ScorerSelection {
  enabled: boolean;
  guidelines?: string;
}

export interface EvalSessionState {
  rows: RowDraft[];
  selections: Record<string, ScorerSelection>;
  judgeModel: string;
  result: EvalRunResponse | null;
  error: string | null;
}

const DEFAULT_GUIDELINES =
  "Response must be concise.\nResponse must avoid speculation about the user.";

let _rowIdSeq = 1;
const nextRowId = () => _rowIdSeq++;

export function newRow(input = "", expected = ""): RowDraft {
  return { id: nextRowId(), input, expected };
}

export function newEvalSession(): EvalSessionState {
  return {
    rows: [newRow("Hello, what can you do?")],
    selections: {},
    judgeModel: "databricks-gpt-5-mini",
    result: null,
    error: null,
  };
}

export function enabledScorerConfigs(session: EvalSessionState) {
  return Object.entries(session.selections)
    .filter(([, s]) => s.enabled)
    .map(([key, s]) => ({
      key,
      config: key === "guidelines" && s.guidelines ? { guidelines: s.guidelines } : {},
    }));
}

interface Props {
  graphGetter: (() => GraphDef) | null;
  onClose: () => void;
  session: EvalSessionState;
  setSession: React.Dispatch<React.SetStateAction<EvalSessionState>>;
}

type Tab = "dataset" | "scorers" | "results";

function draftsFromBackendRows(rows: EvalRow[]): RowDraft[] {
  return rows.map((r) => {
    const inputVal = typeof r.inputs.input === "string" ? r.inputs.input : "";
    const expectedVal =
      r.expectations && typeof r.expectations.expected_response === "string"
        ? r.expectations.expected_response
        : "";
    return newRow(inputVal, expectedVal);
  });
}

function draftsToBackendRows(drafts: RowDraft[]): EvalRow[] {
  const out: EvalRow[] = [];
  for (const d of drafts) {
    const input = d.input.trim();
    if (!input) continue;
    const row: EvalRow = { inputs: { input } };
    const expected = d.expected.trim();
    if (expected) row.expectations = { expected_response: expected };
    out.push(row);
  }
  return out;
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

function passColor(value: unknown): string {
  if (typeof value === "string") {
    const low = value.trim().toLowerCase();
    if (low === "yes" || low === "true" || low === "pass") return "eval-pass";
    if (low === "no" || low === "false" || low === "fail") return "eval-fail";
  }
  if (typeof value === "boolean") return value ? "eval-pass" : "eval-fail";
  if (typeof value === "number") return value > 0 ? "eval-pass" : "eval-fail";
  return "eval-neutral";
}

export default function EvalModal({ graphGetter, onClose, session, setSession }: Props) {
  const { rows, selections, judgeModel, result } = session;

  const [tab, setTab] = useState<Tab>(result ? "results" : "dataset");
  const [generating, setGenerating] = useState(false);
  const [genDescription, setGenDescription] = useState("");
  const [genCount, setGenCount] = useState(5);
  const [genError, setGenError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<ScorerMeta[]>([]);
  const [running, setRunning] = useState(false);
  const runError = session.error;

  const updateSession = useCallback(
    (patch: Partial<EvalSessionState>) => {
      setSession((prev) => ({ ...prev, ...patch }));
    },
    [setSession],
  );

  // Load catalog once. Initialize selections for any new scorer keys without
  // overwriting choices the user has already made.
  useEffect(() => {
    if (!graphGetter) return;
    let cancelled = false;
    (async () => {
      try {
        const graph = graphGetter();
        const data = await suggestScorers(graph);
        if (cancelled) return;
        setCatalog(data.catalog);
        setSession((prev) => {
          const next: Record<string, ScorerSelection> = { ...prev.selections };
          let changed = false;
          for (const s of data.catalog) {
            if (!(s.key in next)) {
              next[s.key] = {
                enabled: data.suggested.includes(s.key),
                guidelines: s.key === "guidelines" ? DEFAULT_GUIDELINES : undefined,
              };
              changed = true;
            }
          }
          return changed ? { ...prev, selections: next } : prev;
        });
      } catch (e) {
        updateSession({ error: (e as Error).message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [graphGetter, setSession, updateSession]);

  const backendRows = useMemo(() => draftsToBackendRows(rows), [rows]);

  const handleGenerate = useCallback(async () => {
    if (!graphGetter) return;
    setGenerating(true);
    setGenError(null);
    try {
      const graph = graphGetter();
      const res = await generateEvalDataset(graph, genDescription, genCount);
      if (!res.rows.length) {
        setGenError("Model returned no rows. Try a more specific description.");
        return;
      }
      updateSession({ rows: draftsFromBackendRows(res.rows) });
    } catch (e) {
      setGenError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }, [graphGetter, genDescription, genCount, updateSession]);

  const handleRun = useCallback(async () => {
    if (!graphGetter) return;
    if (!backendRows.length) {
      updateSession({ error: "Add at least one input row." });
      return;
    }
    const scorerConfigs = enabledScorerConfigs(session);
    if (!scorerConfigs.length) {
      updateSession({ error: "Pick at least one scorer." });
      setTab("scorers");
      return;
    }
    setRunning(true);
    updateSession({ error: null });
    setTab("results");
    try {
      const graph = graphGetter();
      const res = await runEval(graph, backendRows, scorerConfigs, judgeModel, null);
      updateSession({ result: res, error: null });
    } catch (e) {
      updateSession({ error: (e as Error).message });
    } finally {
      setRunning(false);
    }
  }, [graphGetter, backendRows, session, judgeModel, updateSession]);

  const updateRow = useCallback(
    (id: number, patch: Partial<RowDraft>) => {
      setSession((prev) => ({
        ...prev,
        rows: prev.rows.map((r) => (r.id === id ? { ...r, ...patch } : r)),
      }));
    },
    [setSession],
  );

  const removeRow = useCallback(
    (id: number) => {
      setSession((prev) =>
        prev.rows.length === 1 ? prev : { ...prev, rows: prev.rows.filter((r) => r.id !== id) },
      );
    },
    [setSession],
  );

  const addRow = useCallback(() => {
    setSession((prev) => ({ ...prev, rows: [...prev.rows, newRow()] }));
  }, [setSession]);

  const setSelection = useCallback(
    (key: string, patch: Partial<ScorerSelection>) => {
      setSession((prev) => ({
        ...prev,
        selections: { ...prev.selections, [key]: { ...prev.selections[key], ...patch } },
      }));
    },
    [setSession],
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card eval-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h1>Evaluate Agent</h1>
          <p>
            Run your graph against a dataset and score it with built-in LLM judges.
            Results persist for this session so you can iterate, then deploy the
            same scorers as production monitoring.
          </p>
        </div>

        <div className="eval-tabs">
          <button
            className={`eval-tab${tab === "dataset" ? " active" : ""}`}
            onClick={() => setTab("dataset")}
          >
            <ClipboardList size={14} /> Dataset
            <span className="eval-tab-count">{backendRows.length}</span>
          </button>
          <button
            className={`eval-tab${tab === "scorers" ? " active" : ""}`}
            onClick={() => setTab("scorers")}
          >
            <Sparkles size={14} /> Scorers
            <span className="eval-tab-count">
              {Object.values(selections).filter((s) => s.enabled).length}
            </span>
          </button>
          <button
            className={`eval-tab${tab === "results" ? " active" : ""}`}
            onClick={() => setTab("results")}
            disabled={!result && !running}
          >
            <CheckCircle2 size={14} /> Results
          </button>
        </div>

        <div className="modal-body">
          {tab === "dataset" && (
            <div className="eval-section">
              <div className="eval-hint">
                Each row is one test case. <strong>Input</strong> is the user message the agent receives.
                The optional <strong>Expected response</strong> is the ideal answer — required for the
                Correctness scorer.
              </div>
              <div className="eval-generate-row">
                <input
                  type="text"
                  className="deploy-input"
                  placeholder="Describe what the agent does (helps generation)…"
                  value={genDescription}
                  onChange={(e) => setGenDescription(e.target.value)}
                />
                <input
                  type="number"
                  className="deploy-input eval-count-input"
                  min={1}
                  max={20}
                  value={genCount}
                  onChange={(e) => setGenCount(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
                />
                <button
                  className="btn btn-playground btn-with-icon"
                  onClick={handleGenerate}
                  disabled={generating}
                  title="Replace rows with synthetically generated examples"
                >
                  {generating ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                  Generate
                </button>
              </div>
              {genError && <div className="eval-error">{genError}</div>}

              <div className="eval-row-editor">
                {rows.map((row, idx) => (
                  <div key={row.id} className="eval-row-edit-card">
                    <div className="eval-row-edit-head">
                      <span className="eval-row-edit-index">#{idx + 1}</span>
                      <button
                        type="button"
                        className="eval-row-edit-remove"
                        onClick={() => removeRow(row.id)}
                        disabled={rows.length === 1}
                        title="Remove row"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <label className="eval-row-edit-label">
                      Input
                      <textarea
                        className="deploy-input eval-row-edit-textarea"
                        value={row.input}
                        onChange={(e) => updateRow(row.id, { input: e.target.value })}
                        placeholder="The user message the agent should respond to"
                        rows={2}
                      />
                    </label>
                    <label className="eval-row-edit-label">
                      Expected response <span className="eval-row-edit-optional">(optional)</span>
                      <textarea
                        className="deploy-input eval-row-edit-textarea"
                        value={row.expected}
                        onChange={(e) => updateRow(row.id, { expected: e.target.value })}
                        placeholder="The ideal answer — leave blank if there's no single right answer"
                        rows={2}
                      />
                    </label>
                  </div>
                ))}
                <button type="button" className="eval-row-edit-add" onClick={addRow}>
                  <Plus size={14} /> Add row
                </button>
              </div>
            </div>
          )}

          {tab === "scorers" && (
            <div className="eval-section">
              <div className="eval-judge-row">
                <label className="deploy-label eval-judge-label">
                  Judge model
                  <SearchableSelect
                    value={judgeModel}
                    onChange={(value) => updateSession({ judgeModel: value })}
                    fetchEndpoint="/api/discover/serving-endpoints"
                    placeholder="Pick a serving endpoint"
                    showProviderIcons
                  />
                </label>
                <div className="eval-hint">
                  The LLM that grades your agent's answers. Use a strong model
                  (e.g. <code>databricks-gpt-5-mini</code> or
                  <code> databricks-claude-sonnet-4</code>) for reliable judgements.
                </div>
              </div>

              {catalog.map((sc) => {
                const sel = selections[sc.key] || { enabled: false };
                return (
                  <div key={sc.key} className="eval-scorer-row">
                    <label className="eval-scorer-label">
                      <input
                        type="checkbox"
                        checked={sel.enabled}
                        onChange={(e) => setSelection(sc.key, { enabled: e.target.checked })}
                      />
                      <span className="eval-scorer-title">{sc.label}</span>
                    </label>
                    <div className="eval-scorer-desc">{sc.description}</div>
                    {sc.supports_guidelines && sel.enabled && (
                      <textarea
                        className="deploy-input eval-textarea eval-guidelines"
                        value={sel.guidelines ?? ""}
                        onChange={(e) => setSelection(sc.key, { guidelines: e.target.value })}
                        placeholder="One rule per line, e.g. 'Response must be polite.'"
                      />
                    )}
                  </div>
                );
              })}
              {!catalog.length && <div className="eval-hint">Loading scorers…</div>}
            </div>
          )}

          {tab === "results" && (
            <div className="eval-section">
              {running && (
                <div className="eval-hint">
                  <Loader2 size={14} className="spin" /> Running graph against {backendRows.length} row(s)…
                </div>
              )}
              {runError && (
                <div className="eval-error">
                  <XCircle size={14} /> {runError}
                </div>
              )}
              {result && (
                <>
                  <div className="eval-deploy-hint">
                    Like what you see? Open <strong>Deploy</strong> and turn on
                    <em> Production monitoring</em> to run these same scorers
                    against live traffic.
                  </div>
                  <ResultsView result={result} />
                </>
              )}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
          <button
            className="btn btn-deploy btn-with-icon"
            onClick={handleRun}
            disabled={running || !graphGetter || !backendRows.length}
          >
            {running ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
            Run Evaluation
          </button>
        </div>
      </div>
    </div>
  );
}

function ResultsView({ result }: { result: EvalRunResponse }) {
  const scorerNames = useMemo(() => {
    const names = new Set<string>();
    for (const row of result.rows) {
      for (const name of Object.keys(row.assessments)) names.add(name);
    }
    return Array.from(names);
  }, [result]);

  return (
    <div className="eval-results">
      <div className="eval-summary">
        {scorerNames.length === 0 && (
          <div className="eval-hint">No scorers returned numeric results.</div>
        )}
        {scorerNames.map((name) => {
          const score = result.summary[name];
          const pct = score !== undefined ? Math.round(score * 100) : null;
          const bucket =
            pct !== null && pct >= 80 ? "eval-pass" : pct !== null && pct < 50 ? "eval-fail" : "eval-neutral";
          return (
            <div key={name} className="eval-summary-card">
              <div className="eval-summary-name">{name}</div>
              <div className={`eval-summary-value ${bucket}`}>
                {pct !== null ? `${pct}%` : "—"}
              </div>
            </div>
          );
        })}
      </div>

      <div className="eval-rows-scroll">
        <div
          className="eval-rows-table"
          style={{ ["--scorer-cols" as string]: String(Math.max(1, scorerNames.length)) } as React.CSSProperties}
        >
          <div className="eval-rows-head">
            <div className="eval-col-input">Input</div>
            <div className="eval-col-output">Output</div>
            {scorerNames.map((n) => (
              <div key={n} className="eval-col-scorer">{n}</div>
            ))}
          </div>
          {result.rows.map((row, i) => (
            <RowDetails key={i} row={row} scorerNames={scorerNames} />
          ))}
        </div>
      </div>
    </div>
  );
}

function RowDetails({ row, scorerNames }: { row: EvalRowResult; scorerNames: string[] }) {
  const [open, setOpen] = useState(false);
  const input = row.inputs.input ?? Object.values(row.inputs)[0];
  return (
    <div className="eval-row-card">
      <button className="eval-row-summary" onClick={() => setOpen((v) => !v)}>
        <div className="eval-col-input" title={renderValue(input)}>{renderValue(input)}</div>
        <div className="eval-col-output" title={row.output}>{row.output || "—"}</div>
        {scorerNames.map((n) => {
          const a = row.assessments[n];
          if (!a) {
            return <div key={n} className="eval-col-scorer eval-neutral">—</div>;
          }
          if (a.error) {
            return (
              <div key={n} className="eval-col-scorer eval-fail" title={a.error}>
                ERR
              </div>
            );
          }
          return (
            <div key={n} className={`eval-col-scorer ${passColor(a.value)}`}>
              {renderValue(a.value)}
            </div>
          );
        })}
      </button>
      {open && (
        <div className="eval-row-detail">
          <div className="eval-detail-block">
            <div className="eval-detail-label">Input</div>
            <div className="eval-detail-prose">{renderValue(input)}</div>
          </div>
          <div className="eval-detail-block">
            <div className="eval-detail-label">Response</div>
            <div className="eval-detail-prose">{row.output || "(no response)"}</div>
          </div>
          {row.expectations && (
            <div className="eval-detail-block">
              <div className="eval-detail-label">Expected</div>
              <div className="eval-detail-prose">
                {typeof row.expectations.expected_response === "string"
                  ? row.expectations.expected_response
                  : JSON.stringify(row.expectations, null, 2)}
              </div>
            </div>
          )}
          {scorerNames.map((n) => {
            const a = row.assessments[n];
            if (!a) return null;
            return (
              <div key={n} className="eval-detail-block">
                <div className="eval-detail-label">
                  {n} — <span className={passColor(a.value)}>{renderValue(a.value)}</span>
                </div>
                {a.rationale && <div className="eval-detail-rationale">{a.rationale}</div>}
                {a.error && <div className="eval-error">{a.error}</div>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
