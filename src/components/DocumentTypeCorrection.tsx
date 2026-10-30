import { useEffect, useState } from 'react';

type ActiveDocumentType = { id: string; display_name: string; status: string };
type Correction = {
  id: number;
  previous_document_type: string;
  corrected_document_type: string;
  original_prediction: string | null;
  reason: string;
  created_at: string;
};

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

async function request<T>(url: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${url}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json() as { detail?: string };
      message = body.detail || message;
    } catch {
      // Keep the HTTP status when an error response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function DocumentTypeCorrection({
  applicationId,
  documentId,
  currentType,
  predictedType,
  types,
  token,
  onCorrected,
}: {
  applicationId: number;
  documentId: number;
  currentType: string;
  predictedType: string | null;
  types: ActiveDocumentType[];
  token: string;
  onCorrected: () => void;
}) {
  const [history, setHistory] = useState<Correction[]>([]);
  const [targetType, setTargetType] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let current = true;
    void request<Correction[]>(
      `/api/applications/${applicationId}/documents/${documentId}/type-corrections`,
      token,
    ).then(items => {
      if (current) setHistory(items);
    }).catch(cause => {
      if (current) setError(cause instanceof Error ? cause.message : 'Could not load type correction history.');
    });
    return () => { current = false; };
  }, [applicationId, documentId, token]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!targetType || !reason.trim()) return;
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      await request(
        `/api/applications/${applicationId}/documents/${documentId}/type-corrections`,
        token,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ document_type_id: targetType, reason: reason.trim() }),
        },
      );
      setReason('');
      setTargetType('');
      setNotice('Correction recorded. Processing is pending and must be run again for the selected type.');
      onCorrected();
      try {
        setHistory(await request<Correction[]>(
          `/api/applications/${applicationId}/documents/${documentId}/type-corrections`,
          token,
        ));
      } catch (cause) {
        setError(cause instanceof Error
          ? `Correction saved, but history could not be refreshed: ${cause.message}`
          : 'Correction saved, but history could not be refreshed.');
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record type correction.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="registry-correction" aria-label={`Document type review for document ${documentId}`}>
      <p><b>Selected type:</b> {currentType} · <b>Classifier suggestion:</b> {predictedType || 'Unavailable'}</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <form className="admin-create-form" onSubmit={submit}>
        <label>Corrected type<select required value={targetType} onChange={event => setTargetType(event.target.value)}>
          <option value="">Select an active type</option>
          {types.filter(type => type.status === 'active' && type.id !== currentType).map(type => (
            <option key={type.id} value={type.id}>{type.display_name}</option>
          ))}
        </select></label>
        <label>Reviewer reason<input required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
        <button className="button secondary" type="submit" disabled={saving || !targetType || !reason.trim()}>
          {saving ? 'Recording…' : 'Record type correction'}
        </button>
      </form>
      <p className="admin-note">The original prediction remains stored separately. A type correction invalidates the current extraction; reprocess the document to pin and apply its active schema.</p>
      <h4>Correction history</h4>
      {history.length ? history.map(item => (
        <p key={item.id}>
          {item.previous_document_type} → {item.corrected_document_type} · {new Date(item.created_at).toLocaleString()} · {item.reason}
          {item.original_prediction ? ` · Original classifier suggestion: ${item.original_prediction}` : ''}
        </p>
      )) : <p>No type corrections recorded.</p>}
    </section>
  );
}
