import type { ReactNode } from "react";

interface Props {
  icon: ReactNode;
  value: string;
  placeholder: string;
}

/** Compact, read-only resource indicator inspired by Dify's inline ModelSelector.
 *  Shows the configured resource (with its provider/type icon) directly on the
 *  node body. Empty state mirrors the same shape so the layout never collapses. */
export default function ResourcePill({ icon, value, placeholder }: Props) {
  const empty = !value;
  return (
    <div className={`resource-pill${empty ? " resource-pill-empty" : ""}`}>
      <span className="resource-pill-icon">{icon}</span>
      <span className="resource-pill-value">{value || placeholder}</span>
    </div>
  );
}
