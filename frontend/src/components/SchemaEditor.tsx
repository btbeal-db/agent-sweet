const FIELD_TYPES = [
  { value: "str", label: "Text" },
  { value: "int", label: "Integer" },
  { value: "float", label: "Number" },
  { value: "bool", label: "True / False" },
  { value: "list[str]", label: "List of Text" },
  { value: "list[int]", label: "List of Integers" },
  { value: "list[float]", label: "List of Numbers" },
  { value: "vector_search_filter", label: "Vector Search Filter" },
];

const DEFAULT_DESCRIPTIONS: Record<string, string> = {
  vector_search_filter:
    'JSON filter for Vector Search. Format: {"column_name operator": value}. ' +
    'Operators: =, !=, <, <=, >, >=, LIKE, NOT LIKE, IS, IS NOT. ' +
    'Example: {"department =": "cardiology", "year >=": 2020}. ' +
    'Return {} if no filters are needed.',
};

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
                  onChange={(e) => {
                    const newType = e.target.value;
                    const prevDefault = DEFAULT_DESCRIPTIONS[field.type];
                    const shouldAutoFill = newType in DEFAULT_DESCRIPTIONS && (!field.description || field.description === prevDefault);
                    const updated = fields.map((f, j) =>
                      j === i
                        ? { ...f, type: newType, ...(shouldAutoFill ? { description: DEFAULT_DESCRIPTIONS[newType] } : {}) }
                        : f
                    );
                    onChange(updated);
                  }}
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
