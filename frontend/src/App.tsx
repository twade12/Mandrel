import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { StageRail } from "./components/StageRail";
import { ChatPanel } from "./components/ChatPanel";
import { Dock } from "./components/Dock";
import { useStore } from "./state";

export function App() {
  const { chatOpen, toggleChat, checkpoint, resolveCheckpoint } = useStore();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  return (
    <div className="app">
      <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((c) => !c)} />
      <div className="main">
        <div className="topbar">
          <StageRail />
          {checkpoint && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="badge warning">checkpoint: {checkpoint.label}</span>
              <button className="btn" onClick={() => resolveCheckpoint("approve")}>Approve</button>
              <button className="btn btn-ghost" onClick={() => resolveCheckpoint("reject")}>Reject</button>
            </div>
          )}
          <button className="btn btn-ghost" onClick={toggleChat}>
            {chatOpen ? "Hide Chat" : "Chat"}
          </button>
        </div>
        <div className="body-row">
          <div className="dock-wrap">
            <Dock />
          </div>
          {chatOpen && <ChatPanel />}
        </div>
      </div>
    </div>
  );
}
