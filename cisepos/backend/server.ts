import { app } from "./index";

const port = Number(process.env.PORT ?? Bun.env.PORT ?? 3000);
Bun.serve({ port, fetch: app.fetch });
console.log(`CISePOS API listening on :${port}`);
