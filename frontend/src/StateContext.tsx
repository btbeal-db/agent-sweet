import { createContext, useContext } from "react";

const StateVarsContext = createContext<string[]>([]);

export const StateVarsProvider = StateVarsContext.Provider;

export function useStateVars() {
  return useContext(StateVarsContext);
}
