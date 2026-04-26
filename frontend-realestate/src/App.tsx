import { BrowserRouter, Route, Routes } from "react-router-dom";
import MapScreen from "./screens/MapScreen";
import RegionDetailScreen from "./screens/RegionDetailScreen";
import ComplexDetailScreen from "./screens/ComplexDetailScreen";
import StdgDetailScreen from "./screens/StdgDetailScreen";
import ComplexCompareScreen from "./screens/ComplexCompareScreen";
import MobileLayout from "./components/MobileLayout";

// basename="/realestate" — 백엔드가 /realestate/* 로 서빙하므로 prefix 맞춤.
// 모든 라우트가 MobileLayout 안에서 렌더 → 하단 탭바가 경로 간 이동에도 유지.
export default function App() {
  return (
    <BrowserRouter basename="/realestate">
      <MobileLayout>
        <Routes>
          <Route path="/" element={<MapScreen />} />
          <Route path="/region/:sggCd" element={<RegionDetailScreen />} />
          <Route path="/stdg/:stdgCd" element={<StdgDetailScreen />} />
          <Route path="/compare" element={<ComplexCompareScreen />} />
          <Route path="/complex/:aptSeq" element={<ComplexDetailScreen />} />
          <Route path="/search" element={<Placeholder title="검색" />} />
          <Route path="/favorite" element={<Placeholder title="찜" />} />
          <Route path="/menu" element={<Placeholder title="메뉴" />} />
        </Routes>
      </MobileLayout>
    </BrowserRouter>
  );
}

// 탭만 만들어두고 내용은 추후. 빈 화면 대신 안내 문구.
function Placeholder({ title }: { title: string }) {
  return (
    <div className="h-full flex items-center justify-center text-gray-500 text-sm">
      {title} 화면은 준비 중입니다.
    </div>
  );
}
