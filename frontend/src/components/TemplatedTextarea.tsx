import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  placeholder?: string;
  variables: string[];
  onChange: (value: string) => void;
}

/** Textarea with a row of clickable state-variable chips that insert
 *  ``{name}`` at the current cursor position.
 *
 *  We hold the textarea text in *local* state and only sync from the
 *  ``value`` prop when it diverges from what the user last typed.
 *  Without that buffer, any re-render of the parent (xyflow store
 *  refreshes, popover repositioning, etc.) that briefly fed a stale
 *  ``value`` back in mid-keystroke would yank the controlled value out
 *  from under the DOM and React would reset the cursor to the end. */
export default function TemplatedTextarea({ value, placeholder, variables, onChange }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [local, setLocal] = useState(value);
  // Track the last value we committed locally so we can tell when the
  // prop changed for an *external* reason (graph import, chip insert,
  // programmatic edit) vs. when it's just echoing our own onChange back.
  const lastLocalRef = useRef(value);

  useEffect(() => {
    if (value !== lastLocalRef.current) {
      lastLocalRef.current = value;
      setLocal(value);
    }
  }, [value]);

  const commit = (next: string) => {
    lastLocalRef.current = next;
    setLocal(next);
    onChange(next);
  };

  const insert = (name: string) => {
    const ta = ref.current;
    const token = `{${name}}`;
    if (!ta) {
      commit(local + token);
      return;
    }
    const start = ta.selectionStart ?? local.length;
    const end = ta.selectionEnd ?? local.length;
    const next = local.slice(0, start) + token + local.slice(end);
    commit(next);
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
        value={local}
        placeholder={placeholder}
        onChange={(e) => commit(e.target.value)}
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
