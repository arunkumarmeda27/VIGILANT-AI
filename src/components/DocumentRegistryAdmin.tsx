import { useCallback, useEffect, useState } from 'react';

type SchemaVersion = {
  id: number;
  schema_version: string;
  definition: { fields: { id: string; label: string; data_type: string; required: boolean }[] };
  status: string;
  created_at?: string;
  activated_at?: string | null;
};

type RegistryDocumentType = {
  id: string;
  display_name: string;
  category: string;
  family: string | null;
  description: string;
  aliases: string[];
  supported_file_formats: string[];
  supported_languages: string[];
  application_categories: string[];
  regulatory_rule_references: string[];
  issuing_authority: { name: string; aliases: string[]; jurisdiction?: string } | null;
  verification_config: { method: string; description?: string } | null;
  expiry_config: { field_id: string; manual_review_required: boolean } | null;
  status: string;
  schema_versions: SchemaVersion[];
};

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
const DEFAULT_SCHEMA = JSON.stringify({
  fields: [
    { id: 'institution_name', label: 'Institution name', data_type: 'string', required: false },
  ],
}, null, 2);

async function registryRequest<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
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
      // Use the status message when the server does not return JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function DocumentRegistryAdmin({ token }: { token: string }) {
  const [types, setTypes] = useState<RegistryDocumentType[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [documentTypeId, setDocumentTypeId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [category, setCategory] = useState('');
  const [description, setDescription] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [schemaText, setSchemaText] = useState(DEFAULT_SCHEMA);
  const [newVersionType, setNewVersionType] = useState('');
  const [newVersion, setNewVersion] = useState('1.1.0');
  const [selectedDraft, setSelectedDraft] = useState('');
  const [editingTypeId, setEditingTypeId] = useState('');
  const [editDisplayName, setEditDisplayName] = useState('');
  const [editCategory, setEditCategory] = useState('');
  const [editDescription, setEditDescription] = useState('');

  const loadTypes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTypes(await registryRequest<RegistryDocumentType[]>('/api/document-types/', token));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load document types.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { void loadTypes(); }, [loadTypes, reloadKey]);

  async function createType(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      const schema_definition = JSON.parse(schemaText) as SchemaVersion['definition'];
      await registryRequest<RegistryDocumentType>('/api/document-types/', token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: documentTypeId.trim(),
          display_name: displayName.trim(),
          category: category.trim(),
          description: description.trim(),
          aliases: [],
          supported_file_formats: ['pdf'],
          supported_languages: ['en'],
          application_categories: [],
          regulatory_rule_references: [],
          verification_config: { method: 'not_configured' },
          schema_version: version.trim(),
          schema_definition,
        }),
      });
      setDocumentTypeId('');
      setDisplayName('');
      setCategory('');
      setDescription('');
      setNotice('Document type created as a draft. It is not available for processing until its schema is deliberately activated.');
      setReloadKey(value => value + 1);
    } catch (cause) {
      setError(cause instanceof SyntaxError
        ? 'Schema JSON is invalid.'
        : cause instanceof Error ? cause.message : 'Could not create document type.');
    } finally {
      setSaving(false);
    }
  }

  async function createSchemaVersion(event: React.FormEvent) {
    event.preventDefault();
    if (!newVersionType) return;
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      const definition = JSON.parse(schemaText) as SchemaVersion['definition'];
      await registryRequest(`/api/document-types/${encodeURIComponent(newVersionType)}/schema-versions`, token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema_version: newVersion.trim(), definition }),
      });
      setNotice(`Draft schema ${newVersion} created.`);
      setReloadKey(value => value + 1);
    } catch (cause) {
      setError(cause instanceof SyntaxError
        ? 'Schema JSON is invalid.'
        : cause instanceof Error ? cause.message : 'Could not create schema version.');
    } finally {
      setSaving(false);
    }
  }

  async function updateDraftSchema(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedDraft) return;
    const [typeId, versionId] = selectedDraft.split('/');
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      const definition = JSON.parse(schemaText) as SchemaVersion['definition'];
      await registryRequest(`/api/document-types/${encodeURIComponent(typeId)}/schema-versions/${versionId}`, token, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition),
      });
      setNotice('Draft schema updated. Activated or deprecated versions remain immutable.');
      setReloadKey(value => value + 1);
    } catch (cause) {
      setError(cause instanceof SyntaxError
        ? 'Schema JSON is invalid.'
        : cause instanceof Error ? cause.message : 'Could not update draft schema.');
    } finally {
      setSaving(false);
    }
  }

  async function validateSchema() {
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      const definition = JSON.parse(schemaText) as SchemaVersion['definition'];
      const result = await registryRequest<{ status: string; fields: unknown[] }>(
        '/api/document-types/validate-schema',
        token,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(definition),
        },
      );
      setNotice(`Schema definition is ${result.status}; ${result.fields.length} field(s) passed structural validation.`);
    } catch (cause) {
      setError(cause instanceof SyntaxError
        ? 'Schema JSON is invalid.'
        : cause instanceof Error ? cause.message : 'Schema validation failed.');
    } finally {
      setSaving(false);
    }
  }

  async function registryAction(path: string, action: string) {
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      await registryRequest(path, token, { method: 'POST' });
      setNotice(action);
      setReloadKey(value => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Registry action failed.');
    } finally {
      setSaving(false);
    }
  }

  async function updateTypeMetadata(event: React.FormEvent) {
    event.preventDefault();
    if (!editingTypeId) return;
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      await registryRequest<RegistryDocumentType>(
        `/api/document-types/${encodeURIComponent(editingTypeId)}`,
        token,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            display_name: editDisplayName.trim(),
            category: editCategory.trim(),
            description: editDescription.trim(),
          }),
        },
      );
      setEditingTypeId('');
      setNotice('Draft document type metadata updated.');
      setReloadKey(value => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update document type metadata.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="content-section" aria-labelledby="document-registry-heading">
      <h2 id="document-registry-heading">Document type registry</h2>
      <p>Registry definitions and schemas are versioned. New definitions start as drafts; activating a schema only enables data-shape validation and does not establish authenticity or regulatory compliance.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="admin-success" role="status">{notice}</p>}

      <form className="admin-create-form" onSubmit={createType} aria-label="Create document type">
        <label>Type ID<input required pattern="[a-z][a-z0-9_]{0,99}" value={documentTypeId} onChange={event => setDocumentTypeId(event.target.value)} /></label>
        <label>Display name<input required maxLength={255} value={displayName} onChange={event => setDisplayName(event.target.value)} /></label>
        <label>Category<input required maxLength={100} value={category} onChange={event => setCategory(event.target.value)} /></label>
        <label>Description<input required maxLength={4000} value={description} onChange={event => setDescription(event.target.value)} /></label>
        <label>Initial schema version<input required pattern="(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)" value={version} onChange={event => setVersion(event.target.value)} /></label>
        <label className="registry-schema-editor">Schema JSON<textarea required rows={10} value={schemaText} onChange={event => setSchemaText(event.target.value)} /></label>
        <button className="button primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Create draft type'}</button>
        <button className="button secondary" type="button" disabled={saving} onClick={() => void validateSchema()}>Validate schema</button>
      </form>

      {types.length > 0 && <form className="admin-create-form" onSubmit={createSchemaVersion} aria-label="Create schema version">
        <label>Document type<select required value={newVersionType} onChange={event => {
          setNewVersionType(event.target.value);
          const item = types.find(type => type.id === event.target.value);
          if (item?.schema_versions.length) {
            const latest = item.schema_versions[item.schema_versions.length - 1].schema_version.split('.').map(Number);
            setNewVersion(`${latest[0]}.${latest[1] + 1}.0`);
          }
        }}><option value="">Select type</option>{types.filter(type => type.status !== 'deprecated').map(type => <option key={type.id} value={type.id}>{type.display_name}</option>)}</select></label>
        <label>New schema version<input required pattern="(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)" value={newVersion} onChange={event => setNewVersion(event.target.value)} /></label>
        <button className="button secondary" type="submit" disabled={saving || !newVersionType}>Create draft schema</button>
      </form>}
      {types.some(type => type.schema_versions.some(schema => schema.status === 'draft')) && (
        <form className="admin-create-form" onSubmit={updateDraftSchema} aria-label="Update draft schema">
          <label>Draft schema<select required value={selectedDraft} onChange={event => {
            const value = event.target.value;
            setSelectedDraft(value);
            const [typeId, schemaId] = value.split('/');
            const schema = types.find(type => type.id === typeId)?.schema_versions.find(item => String(item.id) === schemaId);
            if (schema) setSchemaText(JSON.stringify(schema.definition, null, 2));
          }}>
            <option value="">Select a draft version</option>
            {types.flatMap(type => type.schema_versions.filter(schema => schema.status === 'draft').map(schema => (
              <option key={`${type.id}/${schema.id}`} value={`${type.id}/${schema.id}`}>{type.display_name} · {schema.schema_version}</option>
            )))}
          </select></label>
          <label className="registry-schema-editor">Edit definition<textarea required rows={8} value={schemaText} onChange={event => setSchemaText(event.target.value)} /></label>
          <button className="button secondary" type="submit" disabled={saving || !selectedDraft}>Save draft version</button>
        </form>
      )}

      {loading ? <p role="status">Loading registry…</p> : types.length ? <div className="table-wrap">
        <table className="admin-user-table"><thead><tr><th>Type</th><th>Status</th><th>Schema versions</th><th>Actions</th></tr></thead>
          <tbody>{types.map(type => <tr key={type.id}>
            <td><strong>{type.display_name}</strong><br /><code>{type.id}</code><br /><small>{type.category} · {type.supported_file_formats.join(', ')}</small></td>
            <td>{type.status}</td>
            <td>{type.schema_versions.map(schema => <div key={schema.id} className="registry-version">
              <span>{schema.schema_version} · {schema.status} · {schema.definition.fields.length} fields</span>
              {schema.status === 'draft' && <button type="button" className="button secondary" disabled={saving} onClick={() => void registryAction(`/api/document-types/${encodeURIComponent(type.id)}/schema-versions/${schema.id}/activate`, `Activated schema ${schema.schema_version} for ${type.display_name}.`)}>Activate draft</button>}
            </div>)}</td>
            <td>
              {type.status === 'draft' && <button type="button" className="button secondary" disabled={saving} onClick={() => {
                setEditingTypeId(type.id);
                setEditDisplayName(type.display_name);
                setEditCategory(type.category);
                setEditDescription(type.description);
              }}>Edit draft metadata</button>}
              {type.status === 'active' && <button type="button" className="button secondary" disabled={saving} onClick={() => void registryAction(`/api/document-types/${encodeURIComponent(type.id)}/deactivate`, `Deactivated ${type.display_name}; its active schema version was preserved.`)}>Deactivate</button>}
              {type.status === 'inactive' && <button type="button" className="button secondary" disabled={saving} onClick={() => void registryAction(`/api/document-types/${encodeURIComponent(type.id)}/activate`, `Reactivated ${type.display_name} with its existing active schema.`)}>Reactivate</button>}
              {type.status !== 'deprecated' && <button type="button" className="button secondary" disabled={saving} onClick={() => void registryAction(`/api/document-types/${encodeURIComponent(type.id)}/deprecate`, `Deprecated ${type.display_name}.`)}>Deprecate</button>}
            </td>
          </tr>)}</tbody>
        </table>
      </div> : !error && <p>No document types are registered.</p>}
      {editingTypeId && <form className="admin-create-form" onSubmit={updateTypeMetadata} aria-label="Edit draft document type metadata">
        <h3>Edit draft document type</h3>
        <label>Display name<input required maxLength={255} value={editDisplayName} onChange={event => setEditDisplayName(event.target.value)} /></label>
        <label>Category<input required maxLength={100} value={editCategory} onChange={event => setEditCategory(event.target.value)} /></label>
        <label>Description<input required maxLength={4000} value={editDescription} onChange={event => setEditDescription(event.target.value)} /></label>
        <button className="button primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save draft metadata'}</button>
        <button className="button secondary" type="button" disabled={saving} onClick={() => setEditingTypeId('')}>Cancel</button>
      </form>}
      <p className="admin-note">Legacy category imports are draft-only preview data. No regulatory references or issuer verification mechanisms are enabled by this interface.</p>
    </section>
  );
}
