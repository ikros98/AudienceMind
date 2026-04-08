import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (
            id.includes("@react-three/drei") ||
            id.includes("/three-stdlib/") ||
            id.includes("/troika-") ||
            id.includes("/camera-controls/") ||
            id.includes("/meshline/")
          ) {
            return "drei-vendor";
          }
          if (
            id.includes("@react-three/fiber") ||
            id.includes("/react-use-measure/") ||
            id.includes("/zustand/") ||
            id.includes("/suspend-react/") ||
            id.includes("/its-fine/") ||
            id.includes("/use-sync-external-store/")
          ) {
            return "fiber-vendor";
          }
          if (id.includes("/maath/")) {
            return "maath-vendor";
          }
          if (id.includes("/three/")) {
            return "three-vendor";
          }
          if (id.includes("/d3")) {
            return "graph-vendor";
          }
          if (id.includes("/framer-motion/")) {
            return "motion-vendor";
          }
          if (id.includes("/react/") || id.includes("/react-dom/") || id.includes("/react-router-dom/")) {
            return "react-vendor";
          }
        },
      },
    },
  },
  server: {
    host: true,
    port: 3020,
  },
  preview: {
    host: true,
    port: 3020,
  },
  assetsInclude: ["**/*.glb"],
});
