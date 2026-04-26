import { create } from "zustand";

interface MapState {
  selectedSggCd: string | null;
  zoomLevel: number;
  bottomSheetSnap: "hidden" | "half" | "full";
  setSelectedSggCd: (sggCd: string | null) => void;
  setZoomLevel: (level: number) => void;
  setBottomSheetSnap: (snap: "hidden" | "half" | "full") => void;
}

// 지도 선택 상태·바텀시트 스냅 레벨을 전역으로 공유.
// Redux 대신 Zustand — 보일러플레이트가 적고 이 규모의 상태엔 충분.
export const useMapStore = create<MapState>((set) => ({
  selectedSggCd: null,
  zoomLevel: 10,
  bottomSheetSnap: "hidden",
  setSelectedSggCd: (sggCd) => set({ selectedSggCd: sggCd }),
  setZoomLevel: (level) => set({ zoomLevel: level }),
  setBottomSheetSnap: (snap) => set({ bottomSheetSnap: snap }),
}));
