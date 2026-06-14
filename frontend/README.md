# Mandrel Frontend

React + dockview + three.js UI for the Mandrel orchestration pipeline.

A project sidebar on the left, a dockable multi-tab workspace in the center
(Device Specs · Schematic · ERC · PCB Layout · DRC · 3D Model · BOM + Sourcing),
and a toggleable chat panel on the right. Tabs update live as a run streams over
the WebSocket; render tabs (PCB/schematic SVG, 3D GLB) pull artifacts generated
on demand by the backend from the KiCad/build123d outputs.

## Develop

The FastAPI backend must be running on :8002 (`mandrel serve` from the repo
root). Then:

```bash
cd frontend
npm install
npm run dev        # Vite dev server on http://localhost:5173
```

Vite proxies `/api` (REST + WebSocket) to the backend, so the two share an
origin during development. Open http://localhost:5173, enter a brief in the
sidebar, and Run Pipeline.

## Build

```bash
npm run build      # type-check + bundle to dist/
```

## Layout

- `src/state.tsx` — central store (reducer + WebSocket wiring), stage status,
  live DesignState.
- `src/api.ts` — REST/WS client and artifact URLs.
- `src/components/` — Sidebar, StageRail, ChatPanel, Dock (dockview).
- `src/components/tabs/` — the seven workspace tabs.

## Status (scaffold)

Working: live stage progression, data tabs (Specs, ERC, DRC, BOM) from the
streamed DesignState, PCB/schematic SVG render tabs, 3D GLB viewer (board +
enclosure), dockable/splittable panels, chat toggle.

Pending: chat-driven plain-English edits (re-run affected stages), persisted
project list across reloads, direct manipulation in the PCB/3D views.
