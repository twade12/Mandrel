import React, { createContext, useContext, useReducer, useRef, useCallback, useEffect } from "react";
import {
  PipelineEvent,
  DesignState,
  Violation,
  startRun as apiStartRun,
  connectRun,
  resolveCheckpoint as apiResolve,
  StartRunRequest,
} from "./api";

export const STAGES = [
  { name: "s1_intent", label: "Spec" },
  { name: "s2_architecture", label: "Architecture" },
  { name: "s3_schematic", label: "Schematic" },
  { name: "s4_layout", label: "PCB" },
  { name: "s5_enclosure", label: "Enclosure" },
  { name: "s6_bom", label: "BOM" },
] as const;

export type StageStatus = "idle" | "running" | "passed" | "failed" | "waiting";

export interface Project {
  runId: string;
  title: string;
  brief: string;
  status: "running" | "completed" | "failed" | "waiting_checkpoint";
  createdAt: number;
}

interface ChatMsg { role: "user" | "assistant"; text: string; }

interface State {
  projects: Project[];
  activeRunId: string | null;
  stageStatus: Record<string, StageStatus>;
  activity: { message: string | null; detail: string | null };
  design: DesignState | null;
  events: PipelineEvent[];
  checkpoint: { stage: string; label: string } | null;
  chat: ChatMsg[];
  chatOpen: boolean;
  theme: "dark" | "light";
}

type Action =
  | { type: "new_project"; project: Project }
  | { type: "select"; runId: string }
  | { type: "event"; runId: string; ev: PipelineEvent }
  | { type: "toggle_chat" }
  | { type: "toggle_theme" }
  | { type: "chat_msg"; msg: ChatMsg };

function initialTheme(): "dark" | "light" {
  const saved = typeof localStorage !== "undefined" ? localStorage.getItem("mandrel-theme") : null;
  return saved === "light" ? "light" : "dark";
}

const initial: State = {
  projects: [],
  activeRunId: null,
  stageStatus: {},
  activity: { message: null, detail: null },
  design: null,
  events: [],
  checkpoint: null,
  chat: [{ role: "assistant", text: "Describe a device to build, or ask for an adjustment once a design exists." }],
  chatOpen: true,
  theme: initialTheme(),
};

function freshStages(): Record<string, StageStatus> {
  return Object.fromEntries(STAGES.map((s) => [s.name, "idle"]));
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "new_project":
      return {
        ...state,
        projects: [action.project, ...state.projects],
        activeRunId: action.project.runId,
        stageStatus: freshStages(),
        activity: { message: null, detail: null },
        design: null,
        events: [],
        checkpoint: null,
      };
    case "select": {
      return { ...state, activeRunId: action.runId };
    }
    case "toggle_chat":
      return { ...state, chatOpen: !state.chatOpen };
    case "toggle_theme":
      return { ...state, theme: state.theme === "dark" ? "light" : "dark" };
    case "chat_msg":
      return { ...state, chat: [...state.chat, action.msg] };
    case "event": {
      if (action.runId !== state.activeRunId) return state; // ignore background runs for now
      const ev = action.ev;
      const stageStatus = { ...state.stageStatus };
      let { activity, design, checkpoint } = state;
      const projects = [...state.projects];
      const proj = projects.find((p) => p.runId === action.runId);

      if (ev.type === "stage_started" && ev.stage) {
        stageStatus[ev.stage] = "running";
        activity = { message: `${ev.label ?? ev.stage} starting…`, detail: null };
      } else if (ev.type === "stage_progress") {
        activity = { message: ev.message ?? null, detail: ev.detail ?? activity.detail };
      } else if (ev.type === "stage_completed" && ev.stage) {
        stageStatus[ev.stage] = ev.passed ? "passed" : "failed";
        activity = { message: null, detail: null };
        if (ev.state) design = ev.state;
      } else if (ev.type === "stage_failed" && ev.stage) {
        stageStatus[ev.stage] = "failed";
        activity = { message: null, detail: null };
      } else if (ev.type === "checkpoint_needed" && ev.stage) {
        stageStatus[ev.stage] = "waiting";
        checkpoint = { stage: ev.stage, label: ev.label ?? ev.stage };
        if (proj) proj.status = "waiting_checkpoint";
        if (ev.state) design = ev.state;
      } else if (ev.type === "checkpoint_resolved" && ev.stage) {
        if (stageStatus[ev.stage] === "waiting") stageStatus[ev.stage] = "passed";
        checkpoint = null;
        if (proj) proj.status = "running";
      } else if (ev.type === "run_completed") {
        if (ev.state) design = ev.state;
        if (proj) proj.status = "completed";
      } else if (ev.type === "run_failed") {
        if (proj) proj.status = "failed";
      }

      const events = ev.type === "ping" ? state.events : [...state.events, ev].slice(-400);
      return { ...state, stageStatus, activity, design, checkpoint, projects, events };
    }
    default:
      return state;
  }
}

interface Store extends State {
  startRun: (req: StartRunRequest) => Promise<void>;
  selectProject: (runId: string) => void;
  resolveCheckpoint: (d: "approve" | "reject") => void;
  toggleChat: () => void;
  toggleTheme: () => void;
  sendChat: (text: string) => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const sockets = useRef<Record<string, WebSocket>>({});

  const startRun = useCallback(async (req: StartRunRequest) => {
    const runId = await apiStartRun(req);
    const title = req.brief.length > 42 ? req.brief.slice(0, 42) + "…" : req.brief;
    dispatch({
      type: "new_project",
      project: { runId, title, brief: req.brief, status: "running", createdAt: Date.now() },
    });
    sockets.current[runId] = connectRun(runId, (ev) => dispatch({ type: "event", runId, ev }));
  }, []);

  const selectProject = useCallback((runId: string) => dispatch({ type: "select", runId }), []);
  const resolveCheckpoint = useCallback(
    (d: "approve" | "reject") => {
      if (state.activeRunId) apiResolve(state.activeRunId, d);
    },
    [state.activeRunId],
  );
  const toggleChat = useCallback(() => dispatch({ type: "toggle_chat" }), []);
  const toggleTheme = useCallback(() => dispatch({ type: "toggle_theme" }), []);

  // Apply the theme to the document root + persist whenever it changes.
  useEffect(() => {
    document.documentElement.dataset.theme = state.theme;
    localStorage.setItem("mandrel-theme", state.theme);
  }, [state.theme]);
  const sendChat = useCallback((text: string) => {
    dispatch({ type: "chat_msg", msg: { role: "user", text } });
    // Chat-driven edits land in a later workstream; acknowledge for now.
    dispatch({
      type: "chat_msg",
      msg: {
        role: "assistant",
        text: "Plain-English design edits are coming in the interactivity workstream — this will re-run the affected stages and refresh every tab.",
      },
    });
  }, []);

  return (
    <Ctx.Provider value={{ ...state, startRun, selectProject, resolveCheckpoint, toggleChat, toggleTheme, sendChat }}>
      {children}
    </Ctx.Provider>
  );
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore must be used within StoreProvider");
  return s;
}

export type { Violation };
