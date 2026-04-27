import { useRef } from "react";

interface Props {
  value: string;
  placeholder?: string;
  variables: string[];
  onChange: (value: string) => void;
}

/** Textarea with a row of clickable state-variable chips that insert
 *  ``{name}`` at the current cursor position. */
export default function TemplatedTextarea({ value, placeholder, variables, onChange }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const insert = (name: string) => {
    const ta = ref.current;
    const token = `{${name}}`;
    if (!ta) {
      onChange(value + token);
      return;
    }
    const start = ta.selectionStart ?? value.length;
    const end = ta.selectionEnd ?? value.length;
    const next = value.slice(0, start) + token + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      ta.focus();
      const cursor = start + token.length;
      ta.setSelectionRange(cursor, cursor);
    });
  };

  return (
    <>
      <textarea
        ref={ref}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {variables.length > 0 && (
        <div className="state-var-chips">
          {variables.map((name) => (
            <button
              type="button"
              key={name}
              className="state-var-chip"
              onClick={() => insert(name)}
              title={`Insert {${name}} at cursor`}
            >
              {`{${name}}`}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
