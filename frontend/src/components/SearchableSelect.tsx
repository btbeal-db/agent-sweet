/**
 * Async searchable dropdown for resource discovery fields.
 *
 * Fetches options from ``fetchEndpoint`` on first open, filters client-side,
 * and falls back to manual text entry if the backend is unreachable.
 */

import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { ChevronDown, Loader2, AlertTriangle } from "lucide-react";
import type { DiscoveryOption } from "../types";
import { fetchDiscoveryOptions, getDiscoveryCache } from "../api";
import ProviderIcon from "./ProviderIcon";

interface Props {
  value: string;
  onChange: (value: string) => void;
  fetchEndpoint: string;
  placeholder?: string;
  showProviderIcons?: boolean;
}

export default function SearchableSelect({
  value,
  onChange,
  fetchEndpoint,
  placeholder,
  showProviderIcons,
}: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<DiscoveryOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetched, setFetched] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Find the label for the currently-selected value
  const selectedLabel = useMemo(
    () => options.find((o) => o.value === value)?.label ?? "",
    [options, value],
  );

  // Fetch on first open (results are cached in api.ts across remounts)
  const doFetch = useCallback(async () => {
    if (fetched || loading) return;
    setLoading(true);
    setError(null);
    const res = await fetchDiscoveryOptions(fetchEndpoint);
    setOptions(res.options);
    if (res.error) setError(res.error);
    setFetched(true);
    setLoading(false);
  }, [fetchEndpoint, fetched, loading]);

  // On mount, restore cached data so selectedLabel resolves without a network call
  useEffect(() => {
    const cached = getDiscoveryCache(fetchEndpoint);
    if (cached && cached.options.length > 0) {
      setOptions(cached.options);
      setFetched(true);
    }
  }, [fetchEndpoint]);

  // Client-side filter
  const filtered = useMemo(() => {
    if (!search) return options;
    const q = search.toLowerCase();
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(q) ||
        o.value.toLowerCase().includes(q) ||
        o.description.toLowerCase().includes(q),
    );
  }, [options, search]);

  // Keep highlight in bounds
  useEffect(() => {
    setHighlightIndex(0);
  }, [filtered.length]);

  // Scroll highlighted item into view
  useEffect(() => {
    if (!isOpen || !listRef.current) return;
    const el = listRef.current.children[highlightIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [highlightIndex, isOpen]);

  // Click-outside to close
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen]);

  const handleOpen = () => {
    setIsOpen(true);
    setSearch("");
    doFetch();
  };

  const selectOption = (opt: DiscoveryOption) => {
    onChange(opt.value);
    setIsOpen(false);
    setSearch("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) {
      if (e.key === "ArrowDown" || e.key === "Enter") {
        e.preventDefault();
        handleOpen();
      }
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightIndex((i) => Math.min(i + 1, filtered.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightIndex((i) => Math.max(i - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        if (filtered[highlightIndex]) {
          selectOption(filtered[highlightIndex]);
        } else if (search) {
          // Allow manual entry
          onChange(search);
          setIsOpen(false);
          setSearch("");
        }
        break;
      case "Escape":
        setIsOpen(false);
        setSearch("");
        break;
      case "Tab":
        setIsOpen(false);
        setSearch("");
        break;
    }
  };

  // When the dropdown is closed, show selected label (or raw value).
  // When open, show the search input.
  const displayValue = isOpen ? search : selectedLabel || value;

  return (
    <div className="searchable-select" ref={containerRef}>
      <div className="searchable-select-input-wrapper">
        <input
          ref={inputRef}
          type="text"
          value={displayValue}
          placeholder={placeholder}
          onFocus={handleOpen}
          onChange={(e) => {
            setSearch(e.target.value);
            if (!isOpen) handleOpen();
          }}
          onKeyDown={handleKeyDown}
        />
        <span className="searchable-select-chevron" onClick={() => (isOpen ? setIsOpen(false) : handleOpen())}>
          {loading ? <Loader2 size={14} className="searchable-select-spinner" /> : <ChevronDown size={14} />}
        </span>
      </div>

      {isOpen && (
        <ul ref={listRef} className="searchable-select-dropdown">
          {loading && (
            <li className="searchable-select-status">
              <Loader2 size={14} className="searchable-select-spinner" />
              Loading...
            </li>
          )}

          {error && !loading && (
            <li className="searchable-select-status searchable-select-error">
              <AlertTriangle size={14} />
              {error} — type manually
            </li>
          )}

          {!loading &&
            filtered.map((opt, i) => (
              <li
                key={opt.value}
                className={`searchable-select-option${i === highlightIndex ? " highlighted" : ""}`}
                onMouseEnter={() => setHighlightIndex(i)}
                onClick={() => selectOption(opt)}
              >
                {showProviderIcons && opt.provider && (
                  <ProviderIcon provider={opt.provider} size={16} />
                )}
                <div className="searchable-select-option-text">
                  <span className="searchable-select-option-label">{opt.label}</span>
                  {opt.description && (
                    <span className="searchable-select-option-desc">{opt.description}</span>
                  )}
                </div>
              </li>
            ))}

          {!loading && fetched && filtered.length === 0 && !error && (
            <li className="searchable-select-status">
              No matches{search ? " — press Enter to use custom value" : ""}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
