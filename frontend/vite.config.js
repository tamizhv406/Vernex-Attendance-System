import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

function dashboardLinks() {
  return {
    name: "dashboard-links",
    configureServer(server) {
      server.httpServer?.once("listening", () => {
        const address = server.httpServer.address();
        const port = typeof address === "object" && address ? address.port : 5173;
        const protocol = server.config.server.https ? "https" : "http";
        const local = `${protocol}://localhost:${port}`;
        // A PC can have several adapters (Wi-Fi, VirtualBox...); the phone needs the one on its own Wi-Fi.
        const networks = (server.resolvedUrls?.network || []).map(url => url.replace(/\/$/, ""));

        console.log("");
        console.log("  Dashboards:");
        console.log(`  Admin local:    ${local}/`);
        console.log(`  Mobile local:   ${local}/mobile`);

        for (const network of networks) {
          console.log(`  Admin network:  ${network}/`);
          console.log(`  Mobile network: ${network}/mobile`);
          console.log(`  Phone scanner:  ${network}/attendance-scanner`);
        }

        console.log("");
      });
    }
  };
}

// The phone has no route to FastAPI on its own "localhost", so the browser calls /api and Vite forwards it.
const backendProxy = {
  "/api": {
    target: process.env.BACKEND_URL || "http://127.0.0.1:8000",
    changeOrigin: true,
    rewrite: path => path.replace(/^\/api/, "")
  }
};

// Browsers only allow camera access on https:// (or localhost). `npm run dev:https` serves a
// self-signed certificate so a phone on the same Wi-Fi can use its camera.
export default defineConfig(({ mode }) => ({
  plugins: [react(), dashboardLinks(), ...(mode === "https" ? [basicSsl()] : [])],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: backendProxy
  },
  preview: {
    proxy: backendProxy
  }
}));
