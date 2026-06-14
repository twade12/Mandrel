import React from "react";
import ReactDOM from "react-dom/client";
import "dockview-react/dist/styles/dockview.css";
import "./styles.css";
import { App } from "./App";
import { StoreProvider } from "./state";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </React.StrictMode>,
);
