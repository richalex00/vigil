import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/vigil-demo/",
  plugins: [react()],
  test: { environment: "node" },
});
