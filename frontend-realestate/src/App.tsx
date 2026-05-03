import { BrowserRouter, Route, Routes } from "react-router-dom";
import MapScreen from "./screens/MapScreen";
import RegionDetailScreen from "./screens/RegionDetailScreen";
import ComplexDetailScreen from "./screens/ComplexDetailScreen";
import StdgDetailScreen from "./screens/StdgDetailScreen";
import ComplexCompareScreen from "./screens/ComplexCompareScreen";
import RankingScreen from "./screens/RankingScreen";
import SearchScreen from "./screens/SearchScreen";
import FavoriteScreen from "./screens/FavoriteScreen";
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
          <Route path="/search" element={<SearchScreen />} />
          <Route path="/favorite" element={<FavoriteScreen />} />
          <Route path="/ranking" element={<RankingScreen />} />
        </Routes>
      </MobileLayout>
    </BrowserRouter>
  );
}
