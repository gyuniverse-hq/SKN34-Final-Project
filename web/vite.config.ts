import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const root = path.dirname(fileURLToPath(import.meta.url));
const adminSrc = path.resolve(root, "../admin/src");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@admin": adminSrc,
    },
  },
  server: {
    port: 5174,
    host: "127.0.0.1",
    fs: { allow: [root, path.resolve(root, "../admin")] },
  },
});
