import { createContext, useContext } from "react";
import type { StateFieldDef } from "./types";

/** State fields are derived from the current nodes. The provider exposes the
 *  derived list (read-only) plus a ``renameNode`` callback that slugifies the
 *  new name into a state-field key and cascades references in templates. */
interface StateContextValue {
  names: string[];
  fields: StateFieldDef[];
  renameNode: (nodeId: string, newName: string) => void;
}

const noop = () => {};

const StateContext = createContext<StateContextValue>({
  names: [],
  fields: [],
  renameNode: noop,
});

export const StateProvider = StateContext.Provider;

export function useStateVars(): string[] {
  return useContext(StateContext).names;
}

export function useStateFields(): StateFieldDef[] {
  return useContext(StateContext).fields;
}

export function useStateField(name: string): StateFieldDef | undefined {
  return useContext(StateContext).fields.find((f) => f.name === name);
}

export function useRenameNode(): (nodeId: string, newName: string) => void {
  return useContext(StateContext).renameNode;
}
