import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const root = path.dirname(fileURLToPath(import.meta.url));
const adminSrc = path.resolve(root, "../admin/src");

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, root, ["VISHUE_DEV_", "VITE_API_BASE_URL"]);
  const apiUrl = env.VITE_API_BASE_URL;
  const localApi = apiUrl && URL.canParse(apiUrl) &&
    ["127.0.0.1", "localhost", "[::1]"].includes(new URL(apiUrl).hostname);
  const target = command === "serve"
    ? env.VISHUE_DEV_API_PROXY_URL || (localApi ? apiUrl : undefined)
    : undefined;

  return {
    plugins: [react()],
    define: {
      "import.meta.env.VITE_DEV_API_PROXY_ACTIVE": JSON.stringify(Boolean(target)),
    },
    resolve: {
      dedupe: ["react", "react-dom", "react-router", "@tanstack/react-query"],
      alias: {
        "@admin": adminSrc,
      },
    },
    server: {
      port: 5174,
      host: "127.0.0.1",
      fs: { allow: [root, path.resolve(root, "../admin")] },
      proxy: target ? {
        "/api": { target, changeOrigin: true },
        "/pay": { target, changeOrigin: true },
      } : undefined,
    },
  };
});
