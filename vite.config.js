import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// A tunnel hostname is only accepted when explicitly supplied at runtime.
// Never hard-code an ngrok URL or an auth token in source control.
const ngrokDomain = process.env.NGROK_DOMAIN;
export default defineConfig({
    plugins: [react()],
    server: {
        host: '0.0.0.0',
        port: 5173,
        strictPort: true,
        allowedHosts: ngrokDomain ? [ngrokDomain] : [],
    },
    preview: {
        host: '0.0.0.0',
        port: 4173,
        strictPort: true,
        allowedHosts: ngrokDomain ? [ngrokDomain] : [],
    },
});
