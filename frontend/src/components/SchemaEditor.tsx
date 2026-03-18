const FIELD_TYPES = [
  { value: "str", label: "Text" },
  { value: "int", label: "Integer" },
  { value: "float", label: "Number" },
  { value: "bool", label: "True / False" },
  { value: "list[str]", label: "List of Text" },
  { value: "list[int]", label: "List of Integers" },
  { value: "list[float]", label: "List of Numbers" },
];

export interface SchemaField {
  name: string;
  type: string;
  description: string;
}

interface Props {
  fields: SchemaField[];
  onChange: (fields: SchemaField[]) => void;
}

export default function SchemaEditor({ fields, onChange }: Props) {
  const updateField = (index: number, key: keyof SchemaField, value: string) => {
    const updated = fields.map((f, i) => (i === index ? { ...f, [key]: value } : f));
    onChange(updated);
  };

  const addField = () => {
    onChange([...fields, { name: "", type: "str", description: "" }]);
  };

  const removeField = (index: number) => {
    onChange(fields.filter((_, i) => i !== index));
  };

  return (
    <div className="schema-editor">
      <div className="schema-editor-header">
        Define the fields the LLM should return.
      </div>

      <div className="schema-list">
        {fields.map((field, i) => (
          <div key={i} className="schema-row">
            <div className="schema-fields">
              <div className="schema-top-row">
                <input
                  className="schema-name"
                  value={field.name}
                  placeholder="field name"
                  onChange={(e) => updateField(i, "name", e.target.value)}
                />
                <select
                  className="schema-type"
                  value={field.type}
                  onChange={(e) => updateField(i, "type", e.target.value)}
                >
                  {FIELD_TYPES.map((ft) => (
                    <option key={ft.value} value={ft.value}>
                      {ft.label}
                    </option>
                  ))}
                </select>
              </div>
              <input
                className="schema-desc"
                value={field.description}
                placeholder="description (helps the LLM)"
                onChange={(e) => updateField(i, "description", e.target.value)}
              />
            </div>
            <button
              className="route-remove"
              onClick={() => removeField(i)}
              title="Remove field"
            >
              &times;
            </button>
          </div>
        ))}
      </div>

      <button className="btn btn-sm schema-add" onClick={addField}>
        + Add Field
      </button>
    </div>
  );
}
