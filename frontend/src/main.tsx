import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";

// Local font files (bundled, no CDN): regular/medium/semibold/bold.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";

import App from "./App";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
