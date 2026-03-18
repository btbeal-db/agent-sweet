export interface Route {
  name: string;
  condition_type: "keywords" | "json_field";
  condition: string;       // keywords: "sales, revenue" | json_field: unused
  json_field: string;      // field name to check in JSON
  json_value: string;      // expected value (e.g. "true", "false", "good")
}

const EMPTY_ROUTE: Route = {
  name: "",
  condition_type: "keywords",
  condition: "",
  json_field: "",
  json_value: "",
};

interface Props {
  routes: Route[];
  onChange: (routes: Route[]) => void;
}

function normalizeRoute(r: Partial<Route> & { name: string }): Route {
  return { ...EMPTY_ROUTE, ...r };
}

export default function RouteEditor({ routes, onChange }: Props) {
  // Normalize on read so old format routes still work
  const normalized = routes.map(normalizeRoute);

  const updateRoute = (index: number, updates: Partial<Route>) => {
    const updated = normalized.map((r, i) => (i === index ? { ...r, ...updates } : r));
    onChange(updated);
  };

  const addRoute = () => {
    const name = `route_${normalized.length + 1}`;
    onChange([
      ...normalized.slice(0, -1),
      { ...EMPTY_ROUTE, name },
      normalized[normalized.length - 1],
    ]);
  };

  const removeRoute = (index: number) => {
    if (normalized.length <= 1) return;
    onChange(normalized.filter((_, i) => i !== index));
  };

  return (
    <div className="route-editor">
      <div className="route-editor-header">
        Routes are evaluated top-to-bottom. First match wins. Last route is the fallback.
      </div>

      <div className="route-list">
        {normalized.map((route, i) => {
          const isLast = i === normalized.length - 1;
          return (
            <div key={i} className={`route-row${isLast ? " route-fallback" : ""}`}>
              <div className="route-fields">
                <input
                  className="route-name"
                  value={route.name}
                  placeholder="route name"
                  onChange={(e) => updateRoute(i, { name: e.target.value })}
                />

                {isLast ? (
                  <span className="route-fallback-label">fallback (always matches)</span>
                ) : (
                  <>
                    <select
                      className="route-condition-type"
                      value={route.condition_type}
                      onChange={(e) =>
                        updateRoute(i, {
                          condition_type: e.target.value as Route["condition_type"],
                        })
                      }
                    >
                      <option value="keywords">Keywords</option>
                      <option value="json_field">JSON Field Equals</option>
                    </select>

                    {route.condition_type === "keywords" ? (
                      <input
                        className="route-condition"
                        value={route.condition}
                        placeholder="match keywords: data, sales, revenue"
                        onChange={(e) => updateRoute(i, { condition: e.target.value })}
                      />
                    ) : (
                      <div className="route-json-fields">
                        <input
                          className="route-json-field"
                          value={route.json_field}
                          placeholder="field name (e.g. good)"
                          onChange={(e) => updateRoute(i, { json_field: e.target.value })}
                        />
                        <span className="route-json-eq">=</span>
                        <input
                          className="route-json-value"
                          value={route.json_value}
                          placeholder="value (e.g. true)"
                          onChange={(e) => updateRoute(i, { json_value: e.target.value })}
                        />
                      </div>
                    )}
                  </>
                )}
              </div>

              {normalized.length > 1 && (
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
    </div>
  );
}
