import type { StateFieldDef } from "../types";

interface Props {
  fields: StateFieldDef[];
  onEdit: () => void;
}

export default function StateSummary({ fields, onEdit }: Props) {
  return (
    <div className="state-summary">
      <div className="state-summary-header">
        <h2>State Model</h2>
        <button className="btn btn-sm" onClick={onEdit}>Edit</button>
      </div>
      <div className="state-summary-fields">
        {fields.map((f) => (
          <div key={f.name} className="state-summary-field">
            <span className="state-summary-name">{f.name}</span>
            <span className="state-summary-type">
              {f.type === "structured" ? `{${f.sub_fields.map(s => s.name).join(", ")}}` : f.type}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
