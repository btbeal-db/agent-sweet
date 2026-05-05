import { useState } from "react";
import type { StateFieldDef } from "../types";

export interface Route {
  label: string;       // displayed on the handle and in the UI
  match_value: string; // what to match against (e.g. "true", "sales,revenue")
}

interface Props {
  evaluatedField: StateFieldDef | null;
  /** For structured fields — which sub-field to branch on */
  subField: string;
  onSubFieldChange: (name: string) => void;
  routes: Route[];
  onChange: (routes: Route[]) => void;
}

/** Mirror the backend keyword-match logic so the test box reflects what will
 *  actually happen at runtime. Lowercase substring match, comma-split keywords,
 *  first match wins, trailing route with no match_value is the fallback. */
function matchRoute(value: string, routes: Route[]): Route | null {
  const lower = value.trim().toLowerCase();
  if (!lower) return null;

  let fallback: Route | null = null;
  for (const route of routes) {
    const matchValue = route.match_value.trim().toLowerCase();
    if (!matchValue) {
      if (!fallback) fallback = route;
      continue;
    }
    if (lower === "true" || lower === "false") {
      if (lower === matchValue) return route;
      continue;
    }
    const keywords = matchValue.split(",").map((k) => k.trim()).filter(Boolean);
    if (keywords.some((kw) => lower.includes(kw))) return route;
  }
  return fallback ?? routes[routes.length - 1] ?? null;
}

export default function RouteEditor({
  evaluatedField,
  subField,
  onSubFieldChange,
  routes,
  onChange,
}: Props) {
  const fieldType = resolveFieldType(evaluatedField, subField);

  // ── Bool: fixed True / False routes, no editing ──────────────
  if (fieldType === "bool") {
    return (
      <div className="route-editor">
        <div className="route-editor-header">
          Routes based on <strong>{evaluatedField?.name}{subField ? `.${subField}` : ""}</strong> (True / False)
        </div>
        <div className="route-list">
          <div className="route-row route-fixed">
            <span className="route-fixed-label route-true">True</span>
          </div>
          <div className="route-row route-fixed">
            <span className="route-fixed-label route-false">False</span>
          </div>
        </div>
      </div>
    );
  }

  // ── Structured: pick a sub-field first, then recurse on its type ──
  if (fieldType === "structured" && evaluatedField) {
    const subs = evaluatedField.sub_fields;
    return (
      <div className="route-editor">
        <div className="route-editor-header">
          Pick which field inside <strong>{evaluatedField.name}</strong> to branch on:
        </div>
        <div className="config-field">
          <select
            value={subField}
            onChange={(e) => onSubFieldChange(e.target.value)}
          >
            <option value="">select sub-field...</option>
            {subs.map((sf) => (
              <option key={sf.name} value={sf.name}>
                {sf.name} ({sf.type})
              </option>
            ))}
          </select>
        </div>
        {subField && (
          <RouteEditor
            evaluatedField={evaluatedField}
            subField={subField}
            onSubFieldChange={onSubFieldChange}
            routes={routes}
            onChange={onChange}
          />
        )}
      </div>
    );
  }

  // ── String / other: keyword-match routes + fallback ──────────
  return (
    <KeywordRouteEditor
      fieldName={evaluatedField?.name ?? "field"}
      subField={subField}
      routes={routes}
      onChange={onChange}
    />
  );
}

interface KeywordEditorProps {
  fieldName: string;
  subField: string;
  routes: Route[];
  onChange: (routes: Route[]) => void;
}

function KeywordRouteEditor({ fieldName, subField, routes, onChange }: KeywordEditorProps) {
  const [testValue, setTestValue] = useState("");

  const fullField = subField ? `${fieldName}.${subField}` : fieldName;
  const matched = testValue ? matchRoute(testValue, routes) : null;

  const updateRoute = (index: number, updates: Partial<Route>) => {
    onChange(routes.map((r, i) => (i === index ? { ...r, ...updates } : r)));
  };

  const addRoute = () => {
    const fallback = routes[routes.length - 1];
    const newLabel = `route_${routes.length}`;
    onChange([
      ...routes.slice(0, -1),
      { label: newLabel, match_value: "" },
      fallback,
    ]);
  };

  const removeRoute = (index: number) => {
    if (routes.length <= 1) return;
    onChange(routes.filter((_, i) => i !== index));
  };

  return (
    <div className="route-editor">
      <div className="route-editor-header">
        Each route has a <strong>label</strong> (what shows on the graph) and
        <strong> match phrases</strong> (what the router actually looks for in <strong>{fullField}</strong>).
        Matching is case-insensitive and substring-based; the first matching route wins, and the last row catches everything else.
      </div>

      <div className="route-list">
        {routes.map((route, i) => {
          const isLast = i === routes.length - 1;
          return (
            <div key={i} className={`route-row${isLast ? " route-fallback" : ""}`}>
              <div className="route-fields">
                <div className="route-field-row">
                  <span className="route-field-tag">Label</span>
                  <input
                    className="route-name"
                    value={route.label}
                    placeholder={isLast ? "fallback" : "route label"}
                    onChange={(e) => updateRoute(i, { label: e.target.value })}
                  />
                </div>
                {isLast ? (
                  <div className="route-field-row">
                    <span className="route-field-tag">Matches</span>
                    <span className="route-fallback-label">anything not matched above</span>
                  </div>
                ) : (
                  <div className="route-field-row">
                    <span className="route-field-tag">Matches</span>
                    <input
                      className="route-condition"
                      value={route.match_value}
                      placeholder="yes, sure, lgtm"
                      onChange={(e) => updateRoute(i, { match_value: e.target.value })}
                    />
                  </div>
                )}
              </div>
              {routes.length > 1 && (
                <button
                  className="route-remove"
                  onClick={() => removeRoute(i)}
                  title="Remove route"
                >
                  &times;
                </button>
              )}
            </div>
          );
        })}
      </div>

      <button className="btn btn-sm route-add" onClick={addRoute}>
        + Add Route
      </button>

      <div className="route-test">
        <label className="route-test-label">Try a value:</label>
        <input
          className="route-test-input"
          value={testValue}
          placeholder={`e.g. a sample ${fullField} value`}
          onChange={(e) => setTestValue(e.target.value)}
        />
        {testValue && matched && (
          <div className="route-test-result">
            → routes to <strong>{matched.label}</strong>
            {!matched.match_value && <span className="route-test-fallback"> (fallback)</span>}
          </div>
        )}
        {testValue && !matched && (
          <div className="route-test-result route-test-empty">
            no route would match
          </div>
        )}
      </div>
    </div>
  );
}

/** Resolve the effective type to route on, following into structured sub-fields. */
function resolveFieldType(
  field: StateFieldDef | null,
  subField: string
): string {
  if (!field) return "str";
  if (field.type !== "structured" || !subField) return field.type;
  const sf = field.sub_fields.find((s) => s.name === subField);
  return sf?.type ?? "str";
}
