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

interface Props {
  graphGetter: (() => GraphDef) | null;
  onClose: () => void;
}

type Tab = "dataset" | "scorers" | "results";

interface ScorerSelection {
  enabled: boolean;
  guidelines?: string;
}

interface RowDraft {
  id: number;
  input: string;
  expected: string;
}

const DEFAULT_GUIDELINES =
  "Response must be concise.\nResponse must avoid speculation about the user.";

let _rowIdSeq = 1;
const nextRowId = () => _rowIdSeq++;

function newRow(input = "", expected = ""): RowDraft {
  return { id: nextRowId(), input, expected };
}

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

export default function EvalModal({ graphGetter, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("dataset");
  const [rows, setRows] = useState<RowDraft[]>([newRow("Hello, what can you do?")]);
  const [generating, setGenerating] = useState(false);
  const [genDescription, setGenDescription] = useState("");
  const [genCount, setGenCount] = useState(5);
  const [genError, setGenError] = useState<string | null>(null);

  const [catalog, setCatalog] = useState<ScorerMeta[]>([]);
  const [selections, setSelections] = useState<Record<string, ScorerSelection>>({});
  const [judgeModel, setJudgeModel] = useState<string>("databricks-gpt-5-mini");

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<EvalRunResponse | null>(null);

  // Load catalog + suggestions when modal opens.
  useEffect(() => {
    if (!graphGetter) return;
    let cancelled = false;
    (async () => {
      try {
        const graph = graphGetter();
        const data = await suggestScorers(graph);
        if (cancelled) return;
        setCatalog(data.catalog);
        const initial: Record<string, ScorerSelection> = {};
        for (const s of data.catalog) {
          initial[s.key] = {
            enabled: data.suggested.includes(s.key),
            guidelines: s.key === "guidelines" ? DEFAULT_GUIDELINES : undefined,
          };
        }
        setSelections(initial);
      } catch (e) {
        setRunError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [graphGetter]);

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
      setRows(draftsFromBackendRows(res.rows));
    } catch (e) {
      setGenError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }, [graphGetter, genDescription, genCount]);

  const handleRun = useCallback(async () => {
    if (!graphGetter) return;
    if (!backendRows.length) {
      setRunError("Add at least one input row.");
      return;
    }
    const scorerConfigs = Object.entries(selections)
      .filter(([, s]) => s.enabled)
      .map(([key, s]) => ({
        key,
        config: key === "guidelines" && s.guidelines ? { guidelines: s.guidelines } : {},
      }));
    if (!scorerConfigs.length) {
      setRunError("Pick at least one scorer.");
      setTab("scorers");
      return;
    }
    setRunning(true);
    setRunError(null);
    setTab("results");
    try {
      const graph = graphGetter();
      const res = await runEval(graph, backendRows, scorerConfigs, judgeModel, null);
      setResult(res);
    } catch (e) {
      setRunError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }, [graphGetter, backendRows, selections, judgeModel]);

  const updateRow = useCallback((id: number, patch: Partial<RowDraft>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const removeRow = useCallback((id: number) => {
    setRows((prev) => (prev.length === 1 ? prev : prev.filter((r) => r.id !== id)));
  }, []);

  const addRow = useCallback(() => {
    setRows((prev) => [...prev, newRow()]);
  }, []);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card eval-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h1>Evaluate Agent</h1>
          <p>
            Run your graph against a dataset and score it with built-in LLM judges.
            Use these results to iterate before deploying.
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
                    onChange={setJudgeModel}
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
                        onChange={(e) =>
                          setSelections((prev) => ({
                            ...prev,
                            [sc.key]: { ...sel, enabled: e.target.checked },
                          }))
                        }
                      />
                      <span className="eval-scorer-title">{sc.label}</span>
                    </label>
                    <div className="eval-scorer-desc">{sc.description}</div>
                    {sc.supports_guidelines && sel.enabled && (
                      <textarea
                        className="deploy-input eval-textarea eval-guidelines"
                        value={sel.guidelines ?? ""}
                        onChange={(e) =>
                          setSelections((prev) => ({
                            ...prev,
                            [sc.key]: { ...sel, guidelines: e.target.value },
                          }))
                        }
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
              {result && <ResultsView result={result} />}
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
          return (
            <div key={name} className="eval-summary-card">
              <div className="eval-summary-name">{name}</div>
              <div className={`eval-summary-value ${pct !== null && pct >= 80 ? "eval-pass" : pct !== null && pct < 50 ? "eval-fail" : "eval-neutral"}`}>
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
          {row.expectations && (
            <div className="eval-detail-block">
              <div className="eval-detail-label">Expectations</div>
              <pre className="eval-detail-pre">{JSON.stringify(row.expectations, null, 2)}</pre>
            </div>
          )}
          {scorerNames.map((n) => {
            const a = row.assessments[n];
            if (!a) return null;
            return (
              <div key={n} className="eval-detail-block">
                <div className="eval-detail-label">{n} — {renderValue(a.value)}</div>
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
