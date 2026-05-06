import { useState } from "react";
import { Loader, FolderPlus, X } from "lucide-react";
import { autoSetup } from "../api";

interface Props {
  defaultPath: string;
  spDisplayName: string;
  onCreated: (experimentPath: string) => void;
  onDismiss: () => void;
  onGoToSetup: () => void;
}

/** First-sign-in prompt asking the user to create their MLflow experiment
 *  folder. Only shown when ``default_folder_exists`` is false on
 *  ``/setup/status``. The user can edit the path or cancel — cancelling
 *  falls through to the regular Setup page.
 */
export default function SetupPromptModal({
  defaultPath,
  spDisplayName,
  onCreated,
  onDismiss,
  onGoToSetup,
}: Props) {
  const [path, setPath] = useState(defaultPath);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!path.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await autoSetup(path);
      if (result.success) {
        onCreated(path);
      } else {
        setError(result.error || "Could not create the folder. Try the manual setup flow.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={loading ? undefined : onDismiss}>
      <div className="modal-card" style={{ width: 520 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h1>
            <FolderPlus size={20} style={{ verticalAlign: "-3px", marginRight: "0.4rem" }} />
            Set up your experiments folder
          </h1>
          <p>
            AgentSweet logs MLflow models and traces into a folder in your workspace.
            We'll create one for you and grant the app's service principal{" "}
            <strong>Can Manage</strong> on it. Both run on your behalf, so no admin
            help is needed.
          </p>
          {!loading && (
            <button
              className="modal-close"
              onClick={onDismiss}
              title="Skip for now"
              style={{ position: "absolute", top: "0.6rem", right: "0.6rem", background: "none", border: 0, cursor: "pointer", color: "var(--text-secondary)" }}
            >
              <X size={18} />
            </button>
          )}
        </div>
        <div className="modal-body">
          <div className="setup-field">
            <label>Folder path:</label>
            <input
              type="text"
              className="deploy-input"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              disabled={loading}
              autoFocus
            />
          </div>

          <p className="setup-hint" style={{ marginTop: "0.5rem" }}>
            Service principal: <code>{spDisplayName}</code>
          </p>

          {error && (
            <div className="setup-instructions-box setup-instructions-warning" style={{ marginTop: "0.75rem" }}>
              <p>{error}</p>
              <p style={{ marginTop: "0.5rem" }}>
                <button className="btn btn-link" onClick={onGoToSetup}>
                  Open the manual setup page →
                </button>
              </p>
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onDismiss} disabled={loading}>
            Skip for now
          </button>
          <button
            className="btn btn-primary"
            onClick={handleCreate}
            disabled={loading || !path.trim()}
          >
            {loading ? (
              <>
                <Loader size={14} className="spinning" />
                Creating...
              </>
            ) : (
              "Create"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
