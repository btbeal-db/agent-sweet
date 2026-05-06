import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  type: "text" | "number";
  placeholder?: string;
  onChange: (value: string) => void;
}

/** A text/number input that holds its DOM value in local state and only
 *  syncs from props when the prop diverges from the last committed local
 *  value. Defends against parent re-renders that briefly feed a stale
 *  ``value`` back in mid-keystroke and reset the cursor to the end. */
export default function LocalInput({ value, type, placeholder, onChange }: Props) {
  const [local, setLocal] = useState(value);
  const lastLocalRef = useRef(value);

  useEffect(() => {
    if (value !== lastLocalRef.current) {
      lastLocalRef.current = value;
      setLocal(value);
    }
  }, [value]);

  return (
    <input
      type={type}
      value={local}
      placeholder={placeholder}
      onChange={(e) => {
        const next = e.target.value;
        lastLocalRef.current = next;
        setLocal(next);
        onChange(next);
      }}
    />
  );
}
