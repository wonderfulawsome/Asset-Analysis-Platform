import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // /static/realestate/ 기준으로 asset URL 생성 — FastAPI /static 마운트와 맞춤.
  // base가 없으면 빌드된 index.html이 /assets/... 로 참조해서 404 발생.
  base: "/static/realestate/",
  build: {
    outDir: "../static/realestate",
    emptyOutDir: true,
  },
});
