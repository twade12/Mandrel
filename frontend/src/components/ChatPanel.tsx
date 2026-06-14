import { useState } from "react";
import { useStore } from "../state";

export function ChatPanel() {
  const { chat, sendChat, activity } = useStore();
  const [text, setText] = useState("");

  function submit() {
    if (!text.trim()) return;
    sendChat(text.trim());
    setText("");
  }

  return (
    <div className="chat">
      <div className="chat-header">
        <span className="section-label" style={{ padding: 0 }}>Assistant</span>
        {activity.message && <span className="spinner" />}
      </div>
      <div className="chat-log">
        {chat.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>{m.text}</div>
        ))}
        {activity.detail && (
          <div className="chat-msg assistant" style={{ fontSize: 11, opacity: 0.8 }}>
            <div className="muted" style={{ marginBottom: 4 }}>live model output</div>
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{activity.detail.slice(-600)}</pre>
          </div>
        )}
      </div>
      <div className="chat-input">
        <textarea
          rows={2}
          placeholder="Ask for an adjustment…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        />
        <button className="btn" onClick={submit}>Send</button>
      </div>
    </div>
  );
}
