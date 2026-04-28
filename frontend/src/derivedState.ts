import type { Node } from "@xyflow/react";
import type { SchemaField } from "./components/SchemaEditor";
import type { StateFieldDef } from "./types";

const RESERVED = new Set(["input", "messages"]);

/** Convert a free-form display name to a snake_case identifier. */
export function slugify(input: string): string {
  return input
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** Pick a field name for a node from its custom name, falling back to display name then id.
 *  ``existing`` is the set of names already taken; this function suffixes ``_2`` etc. on collision. */
export function deriveNodeFieldName(
  customName: string,
  displayName: string,
  fallbackId: string,
  existing: Set<string>,
): string {
  const base =
    slugify(customName) || slugify(displayName) || slugify(fallbackId) || "node";
  // Avoid colliding with reserved names or already-claimed names.
  let candidate = base;
  let counter = 1;
  while (RESERVED.has(candidate) || existing.has(candidate)) {
    counter++;
    candidate = `${base}_${counter}`;
  }
  return candidate;
}

/** Pick a fresh display label + matching slug for a newly dropped node. The label
 *  is the raw display name (e.g. "LLM"); on collision we append " 2", " 3", … so
 *  the header text and the state-field key stay aligned ("LLM 2" ↔ "llm_2"). */
export function deriveNewNodeLabel(
  displayName: string,
  existingFields: Set<string>,
): { name: string; writesTo: string } {
  let counter = 1;
  let label = displayName;
  let slug = slugify(label) || "node";
  while (RESERVED.has(slug) || existingFields.has(slug)) {
    counter++;
    label = `${displayName} ${counter}`;
    slug = slugify(label);
  }
  // First instance keeps the default header (no custom name needed); collisions
  // store the suffixed label so it renders in the header.
  return { name: counter === 1 ? "" : label, writesTo: slug };
}

function nodeWritesTo(node: Node): string {
  return (node.data?.writes_to as string) ?? "";
}

function nodeIsRouter(node: Node): boolean {
  return (node.data?.is_router as boolean) ?? false;
}

function nodeOutputSchema(node: Node): SchemaField[] {
  const config = (node.data?.config ?? {}) as Record<string, unknown>;
  const raw = config.output_schema;
  if (Array.isArray(raw)) return raw as SchemaField[];
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed as SchemaField[];
    } catch { /* ignore */ }
  }
  return [];
}

/** Build the canonical list of state fields derived from the current nodes.
 *  Always includes the special ``input`` field. Each non-router node contributes
 *  one state field keyed on ``data.writes_to`` (set by the canvas at drop time). */
export function deriveStateFields(nodes: Node[]): StateFieldDef[] {
  const fields: StateFieldDef[] = [
    { name: "input", type: "str", description: "The initial user input", sub_fields: [] },
  ];
  const seen = new Set<string>(["input"]);

  for (const node of nodes) {
    if (nodeIsRouter(node)) continue;
    const writesTo = nodeWritesTo(node);
    if (!writesTo || seen.has(writesTo)) continue;

    const nodeType = (node.data?.nodeType as string) ?? "";
    const displayName = (node.data?.display_name as string) ?? "Node";
    const customName = (node.data?.name as string) ?? "";
    const description = `${customName || displayName} output`;

    if (nodeType === "llm") {
      const schema = nodeOutputSchema(node);
      const subFields = schema
        .filter((sf) => sf.name)
        .map((sf) => ({ name: sf.name, type: sf.type ?? "str", description: sf.description ?? "" }));
      if (subFields.length > 0) {
        fields.push({ name: writesTo, type: "structured", description, sub_fields: subFields });
        seen.add(writesTo);
        continue;
      }
    }

    fields.push({ name: writesTo, type: "str", description, sub_fields: [] });
    seen.add(writesTo);
  }

  return fields;
}

/** Flat list of selectable identifiers for templating: field name + dotted sub-fields. */
export function deriveStateNames(fields: StateFieldDef[]): string[] {
  const names: string[] = [];
  for (const field of fields) {
    names.push(field.name);
    if ((field.type === "structured" || field.type === "vector_search_filter") && field.sub_fields?.length) {
      for (const sf of field.sub_fields) {
        if (sf.name) names.push(`${field.name}.${sf.name}`);
      }
    }
  }
  return names;
}
