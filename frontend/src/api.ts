// REST + WebSocket client for the Mandrel backend (proxied via Vite to :8002).

export interface StartRunRequest {
  brief: string;
  form_factor: string;
  auto_approve: boolean;
  llm_model?: string | null;
}

export interface PipelineEvent {
  type: string;
  stage?: string;
  label?: string;
  message?: string;
  detail?: string;
  passed?: boolean;
  score?: number;
  violations?: Violation[];
  state?: DesignState;
  summary?: string;
  decision?: string;
  error?: string;
}

export interface Violation {
  code: string;
  message: string;
  severity: "error" | "warning" | "info";
  location?: string | null;
}

export interface DesignState {
  project_id?: string;
  spec?: any;
  architecture?: any;
  schematic?: any;
  pcb?: any;
  enclosure?: any;
  bom?: any;
  [k: string]: any;
}

export async function startRun(req: StartRunRequest): Promise<string> {
  const res = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  const { run_id } = await res.json();
  return run_id;
}

export async function resolveCheckpoint(runId: string, decision: "approve" | "reject") {
  await fetch(`/api/runs/${runId}/checkpoint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
}

export function connectRun(runId: string, onEvent: (e: PipelineEvent) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/runs/${runId}/ws`);
  ws.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data));
    } catch {
      /* ignore malformed frame */
    }
  };
  return ws;
}

// Artifact URLs (backend generates SVG/GLB on demand from the project workspace).
export const artifactUrl = (runId: string, name: string) =>
  `/api/runs/${runId}/artifact/${name}`;
