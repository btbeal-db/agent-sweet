import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, ClipboardList, Loader2, Play, Sparkles, XCircle } from "lucide-react";
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

interface Props {
  graphGetter: (() => GraphDef) | null;
  onClose: () => void;
}

type Tab = "dataset" | "scorers" | "results";

interface ScorerSelection {
  enabled: boolean;
  guidelines?: string;
}

const DEFAULT_GUIDELINES =
  "Response must be concise.\nResponse must avoid speculation about the user.";

function rowsToJsonl(rows: EvalRow[]): string {
  return rows.map((r) => JSON.stringify(r)).join("\n");
}

function parseJsonl(text: string): { rows: EvalRow[]; error: string | null } {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const rows: EvalRow[] = [];
  for (let i = 0; i < lines.length; i++) {
    try {
      const parsed = JSON.parse(lines[i]);
      if (!parsed.inputs || typeof parsed.inputs !== "object") {
        return { rows: [], error: `Line ${i + 1}: missing "inputs" object.` };
      }
      rows.push({ inputs: parsed.inputs, expectations: parsed.expectations ?? null });
    } catch (e) {
      return { rows: [], error: `Line ${i + 1}: ${(e as Error).message}` };
    }
  }
  return { rows, error: null };
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
  const [datasetText, setDatasetText] = useState<string>(
    JSON.stringify({ inputs: { input: "Hello, what can you do?" } }),
  );
  const [generating, setGenerating] = useState(false);
  const [genDescription, setGenDescription] = useState("");
  const [genCount, setGenCount] = useState(5);
  const [genError, setGenError] = useState<string | null>(null);

  const [catalog, setCatalog] = useState<ScorerMeta[]>([]);
  const [selections, setSelections] = useState<Record<string, ScorerSelection>>({});

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

  const datasetParse = useMemo(() => parseJsonl(datasetText), [datasetText]);

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
      setDatasetText(rowsToJsonl(res.rows));
    } catch (e) {
      setGenError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }, [graphGetter, genDescription, genCount]);

  const handleRun = useCallback(async () => {
    if (!graphGetter) return;
    if (datasetParse.error || !datasetParse.rows.length) {
      setRunError(datasetParse.error || "Add at least one dataset row.");
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
      const res = await runEval(graph, datasetParse.rows, scorerConfigs, null);
      setResult(res);
    } catch (e) {
      setRunError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }, [graphGetter, datasetParse, selections]);

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
            <span className="eval-tab-count">{datasetParse.rows.length}</span>
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
                >
                  {generating ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                  Generate
                </button>
              </div>
              {genError && <div className="eval-error">{genError}</div>}
              <label className="deploy-label">
                Dataset (JSONL — one row per line, each with <code>inputs</code> and optional <code>expectations</code>)
                <textarea
                  className="deploy-input eval-textarea"
                  spellCheck={false}
                  value={datasetText}
                  onChange={(e) => setDatasetText(e.target.value)}
                />
              </label>
              {datasetParse.error && <div className="eval-error">{datasetParse.error}</div>}
              {!datasetParse.error && (
                <div className="eval-hint">
                  Parsed {datasetParse.rows.length} row(s). Example:{" "}
                  <code>{'{"inputs": {"input": "..."}, "expectations": {"expected_response": "..."}}'}</code>
                </div>
              )}
            </div>
          )}

          {tab === "scorers" && (
            <div className="eval-section">
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
                  <Loader2 size={14} className="spin" /> Running graph against {datasetParse.rows.length} row(s)…
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
            disabled={running || !graphGetter || !datasetParse.rows.length}
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
          return (
            <div key={n} className={`eval-col-scorer ${a ? passColor(a.value) : "eval-neutral"}`}>
              {a ? renderValue(a.value) : "—"}
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
