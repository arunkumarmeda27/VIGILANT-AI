import path from 'node:path';
import { createApp } from './app.js';
const port = Number(process.env.PORT ?? 3000);
createApp(process.env.VIGILANT_DATA_FILE ?? path.resolve('.data/vigilant.json')).listen(port, () => console.log(`VIGILANT API listening on ${port}`));
