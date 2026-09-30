import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En dev, Vite sert le front et relaie /api vers l'API FastAPI (uvicorn, port 8000).
// En prod, c'est FastAPI qui sert le build (`dist/`) : même origine, pas de CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
