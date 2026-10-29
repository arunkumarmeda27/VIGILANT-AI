import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import express, { type NextFunction, type Request, type Response } from 'express';
import { z } from 'zod';
import { canAccessApplication, validateApplication, type ValidationDocument } from '../src/domain/validation.js';

type Actor = { id: string; institutionId: string; roles: string[] };
type StoredApplication = { id: string; institutionId: string; documents: ValidationDocument[]; runs: ReturnType<typeof validateApplication>[] };
type Store = { applications: StoredApplication[] };
const allowedTypes = new Set(['application/pdf', 'image/png', 'image/jpeg']); const maxUploadBytes = 10 * 1024 * 1024;
const actorSchema = z.object({ id: z.string().min(1), institutionId: z.string().min(1), roles: z.array(z.enum(['ADMIN', 'REVIEWER', 'OBSERVER'])).min(1) });
const uploadSchema = z.object({ id: z.string().min(1), schemaId: z.string().optional(), fileName: z.string().min(1).max(255).refine((name) => !/[\\/]/.test(name), 'fileName must not contain a path'), mimeType: z.string(), sizeBytes: z.number().int().positive().max(maxUploadBytes), values: z.record(z.string(), z.string().max(1000).optional()).default({}), checksum: z.string().regex(/^[a-f0-9]{64}$/).optional() });
function loadStore(file: string): Store { return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) as Store : { applications: [] }; }
function saveStore(file: string, store: Store) { fs.mkdirSync(path.dirname(file), { recursive: true }); const temp = `${file}.${crypto.randomUUID()}.tmp`; fs.writeFileSync(temp, JSON.stringify(store, null, 2), { encoding: 'utf8', mode: 0o600 }); fs.renameSync(temp, file); }
class AuthenticationError extends Error {}
function actor(request: Request): Actor { const raw = request.header('x-vigilant-actor'); if (!raw) throw new AuthenticationError('Missing identity.'); return actorSchema.parse(JSON.parse(raw)); }

/** Development API: an upstream identity gateway must replace x-vigilant-actor before deployment. */
export function createApp(dataFile = path.resolve('.data/vigilant.json')) {
  const app = express(); app.disable('x-powered-by'); app.use(express.json({ limit: '64kb' }));
  app.get('/healthz', (_request, response) => response.json({ status: 'ok' }));
  app.post('/api/applications', (request, response, next) => { try {
    const current = actor(request); const body = z.object({ id: z.string().regex(/^APP-[A-Z0-9-]+$/), institutionId: z.string().min(1) }).parse(request.body);
    if (!current.roles.includes('ADMIN') && current.institutionId !== body.institutionId) return response.status(403).json({ error: 'Cross-institution creation is forbidden.' });
    const store = loadStore(dataFile); if (store.applications.some((item) => item.id === body.id)) return response.status(409).json({ error: 'Application already exists.' });
    store.applications.push({ ...body, documents: [], runs: [] }); saveStore(dataFile, store); return response.status(201).json(body);
  } catch (error) { return next(error); } });
  app.post('/api/applications/:id/documents', (request, response, next) => { try {
    const current = actor(request); const body = uploadSchema.parse(request.body); const store = loadStore(dataFile); const application = store.applications.find((item) => item.id === request.params.id);
    if (!application) return response.status(404).json({ error: 'Application not found.' }); if (!canAccessApplication(current, application.institutionId)) return response.status(403).json({ error: 'Application access is forbidden.' });
    if (!allowedTypes.has(body.mimeType)) return response.status(415).json({ error: 'Unsupported media type.' }); if (application.documents.some((item) => item.id === body.id)) return response.status(409).json({ error: 'Document already exists.' });
    application.documents.push({ id: body.id, schemaId: body.schemaId, mimeType: body.mimeType, values: body.values, checksum: body.checksum }); saveStore(dataFile, store); return response.status(201).json({ id: body.id, status: 'RECEIVED', sizeBytes: body.sizeBytes });
  } catch (error) { return next(error); } });
  app.post('/api/applications/:id/validation-runs', (request, response, next) => { try {
    const current = actor(request); const store = loadStore(dataFile); const application = store.applications.find((item) => item.id === request.params.id);
    if (!application) return response.status(404).json({ error: 'Application not found.' }); if (!canAccessApplication(current, application.institutionId)) return response.status(403).json({ error: 'Application access is forbidden.' });
    const run = validateApplication(application.id, application.documents); application.runs.push(run); saveStore(dataFile, store); return response.status(201).json(run);
  } catch (error) { return next(error); } });
  app.get('/api/applications/:id/validation-runs', (request, response, next) => { try {
    const current = actor(request); const application = loadStore(dataFile).applications.find((item) => item.id === request.params.id);
    if (!application) return response.status(404).json({ error: 'Application not found.' }); if (!canAccessApplication(current, application.institutionId)) return response.status(403).json({ error: 'Application access is forbidden.' }); return response.json(application.runs);
  } catch (error) { return next(error); } });
  app.use((error: unknown, _request: Request, response: Response, _next: NextFunction) => {
    if (error instanceof AuthenticationError) return response.status(401).json({ error: 'Authentication is required.' });
    if (error instanceof z.ZodError || error instanceof SyntaxError) return response.status(400).json({ error: 'Invalid request.' });
    return response.status(500).json({ error: 'Internal server error.' });
  });
  return app;
}
