# VisRAG Frontend

React + Vite + Tailwind UI for VisRAG. See the [root README](../README.md) for the full setup.

```bash
npm install
npm run dev        # http://localhost:8080
```

| Script | |
| --- | --- |
| `npm run dev` | dev server on port 8080 |
| `npm run build` | production build to `dist/` |
| `npm test` | unit/component tests (Vitest + Testing Library) |
| `npm run lint` | ESLint |

## Configuration

Copy `.env.example` to `.env.local`.

- `VITE_API_URL` — backend origin (default `http://127.0.0.1:8000`). The backend's
  `ALLOWED_ORIGINS` must include the origin this app is served from.
- `VITE_API_KEY` — only if the backend sets `API_KEY`. It is bundled into the
  browser code, so it is not a secret.

## Layout

- `src/lib/api.ts` — API client (upload with real progress, status polling, ask)
- `src/components/UploadBox.tsx` — upload + ingestion progress
- `src/components/ChatWindow.tsx`, `MessageBubble.tsx` — chat, Markdown answers
- `src/components/VisualPanel.tsx` — supporting tables and figures
- `src/components/ui/` — the shadcn/ui primitives actually in use
