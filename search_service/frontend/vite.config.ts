import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const localApiProxy = {
  "/api": {
    target: "http://127.0.0.1:8000",
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ""),
  },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: localApiProxy,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: localApiProxy,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
})
