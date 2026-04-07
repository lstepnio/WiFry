# WiFry Frontend

The frontend is a React + TypeScript + Vite application that provides the WiFry operator UI.

## Runtime Model

- Local development uses the Vite dev server on port `3000`
- Production does not run a separate frontend service
- On the Pi, FastAPI serves the built frontend from `frontend/dist` on port `8080`

That means:

- local UI work often uses `http://localhost:3000`
- production UI and API share the same origin at `http://<wifry-host>:8080`

## Commands

```bash
npm install
npm run dev
npm run lint
npm test
npx tsc --noEmit
npm run build
```

## Development Notes

- Prefer the typed client in `src/api/client.ts` over ad hoc fetch usage
- Keep supported workflows prominent: Network Config, Sessions, and session bundle sharing
- Treat live remote access and collaboration as experimental surfaces
- Session bundles are for STB/test evidence, not for WiFry appliance diagnostics

## Build Output

`npm run build` writes the production app to `frontend/dist`. The backend serves that directory when present.
