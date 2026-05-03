import type { Config } from "tailwindcss";

// Bloomberg Terminal 스타일 — 검정 배경 + JetBrains Mono + 오렌지 헤더 + KR 증시 관례 색
// (상승=빨강, 하락=파랑). lib/color.ts 의 hex 와 동기 (term.up=#ff4444, term.down=#4488ff).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        term: {
          bg: "#0a0a0a",       // 본문 배경
          panel: "#111111",    // 카드/패널
          border: "#222222",   // 패널 외곽선
          orange: "#ff8800",   // 섹션 헤더 (BLOOMBERG ORANGE)
          amber: "#ffaa00",    // 보조 강조
          up: "#ff4444",       // 상승 (KR 관례)
          down: "#4488ff",     // 하락
          dim: "#666666",      // 보조 텍스트
          text: "#e8e8e8",     // 본문
          green: "#00cc66",    // BUY 라벨용
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Noto Sans KR"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
