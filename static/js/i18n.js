// ── 다국어 지원 (i18n) ──
// localStorage의 'lang' 키로 언어 설정을 저장/복원

// ── 현재 언어 반환 ──
function getLang() {
  return localStorage.getItem('lang') || 'ko'; // 기본값: 한국어
}

// ── 번역 사전 ──
const I18N = {
  ko: {
    // ── 탭 ──
    'tab.market': '시장',                         // 시장 탭
    'tab.signal': '신호',                         // 신호 탭
    'tab.macro': '거시경제',                      // 거시경제 탭
    'tab.chart': '차트',                          // 차트 탭

    // ── 헤더 / 날짜 ──
    'lang.btn': 'EN',                             // 언어 전환 버튼 텍스트

    // ── Holdings 설정 ──
    'holdings.back': '← 뒤로',                   // 뒤로 버튼
    'holdings.title': '보유 종목 설정',           // 설정 제목
    'holdings.desc': '투자 중인 ETF를 선택해주세요', // 설정 설명
    'holdings.search': 'ETF 검색 (예: QQQ, SPY...)', // 검색 플레이스홀더
    'holdings.selectedLabel': '선택된 종목',      // 선택된 종목 라벨
    'holdings.confirm': '시작하기',               // 확인 버튼
    'holdings.selectPrompt': '종목을 선택해주세요', // 미선택 안내
    'holdings.setPrompt': '보유종목을 설정해주세요', // 미설정 안내
    'holdings.loading': '데이터 준비 중...',      // 로딩 안내
    'holdings.noData': '보유종목 가격 데이터가 없습니다', // 데이터 없음
    'holdings.loadError': '데이터를 불러올 수 없습니다', // 로드 에러

    // ── Noise vs Signal ──
    'nr.fundamental': '펀더멘털',                 // 갭바 좌측
    'nr.price': '주가',                           // 갭바 우측
    'nr.match': '일치',                           // 갭바 하단 좌측
    'nr.gap': '괴리',                             // 갭바 하단 우측

    // ── NR 국면명 (API 응답 한글 → 표시용) ──
    'nr.phase.fundamental': '펀더멘털 반영',      // 국면 1
    'nr.phase.weakFundamental': '펀더멘털 약반영', // 국면 2
    'nr.phase.weakSentiment': '센티멘트 약반영',  // 국면 3
    'nr.phase.sentiment': '센티멘트 지배',        // 국면 4

    // ── NR 국면 설명 ──
    'nr.sub.fundamental': '주가가 펀더멘털에 부합',         // 국면 1 설명
    'nr.sub.weakFundamental': '주가가 펀더멘털에 부합',     // 국면 2 설명
    'nr.sub.weakSentiment': '주가가 펀더멘털에 부합하지 않음', // 국면 3 설명
    'nr.sub.sentiment': '주가가 펀더멘털에 부합하지 않음',    // 국면 4 설명

    // ── NR 뱃지 ──
    'nr.badge.stable': '안정',                    // 안정 뱃지
    'nr.badge.caution': '주의',                   // 주의 뱃지
    'nr.badge.alert': '경계',                     // 경계 뱃지
    'nr.badge.danger': '위험',                    // 위험 뱃지

    // ── 섹션 라벨 ──
    'section.nrChart': '펀더멘털·주가 추이 (30일)', // NR 차트 라벨
    'section.myHoldings': 'My Holdings',           // 보유종목 섹션
    'section.csChart': '방향성 추이 (30일)',       // CS 차트 라벨

    // ── VIX 등급 ──
    'vix.low': '낮음',                            // VIX 낮음
    'vix.normal': '보통',                         // VIX 보통
    'vix.high': '높음',                           // VIX 높음
    'vix.danger': '위험',                         // VIX 위험

    // ── VOL 등급 ──
    'vol.surge': '거래 급증',                     // 거래량 급증
    'vol.above': '평균 이상',                     // 평균 이상
    'vol.avg': '평균',                            // 평균
    'vol.low': '거래 감소',                       // 거래 감소

    // ── P/C 라벨 ──
    'pc.bearish': '하방 옵션',                    // 풋 우세
    'pc.bullish': '상방 옵션',                    // 콜 우세
    'pc.neutral': '중립',                         // 중립

    // ── 시장 요약 ──
    'mo.title': '시장 요약',                      // 카드 제목
    'mo.fearGreed': '공포 · 탐욕 지수',           // 공포·탐욕
    'mo.marketReturn': '주요지수 수익률',          // 시장 수익률
    'mo.rsi': 'S&P500 RSI (14)',                   // RSI

    // ── RSI 라벨 ──
    'rsi.overbought': '과매수',                   // 과매수
    'rsi.oversold': '과매도',                     // 과매도
    'rsi.neutral': '중립',                        // 중립

    // ── Fear & Greed 등급 (API 응답 한글) ──
    'fg.extremeGreed': '극도 탐욕',               // Extreme Greed
    'fg.greed': '탐욕',                           // Greed
    'fg.neutral': '중립',                         // Neutral
    'fg.fear': '공포',                            // Fear
    'fg.extremeFear': '극도 공포',                // Extreme Fear

    // ── Crash/Surge ──
    'cs.crashRisk': '하락 위험도',                // 하락 위험도
    'cs.surgeExpect': '상승 기대도',              // 상승 기대도
    'cs.cardLabel': '하락/상승 가능성',           // 카드 라벨
    'cs.detailTitle': '하락/상승 가능성 분석',    // 상세 제목
    'cs.asOf': '기준',                            // 날짜 기준
    'cs.modelF1': '모델 F1:',                     // F1 라벨

    // ── CS 등급 (API 응답 한글) ──
    'grade.low': '낮음',                          // Low
    'grade.normal': '보통',                       // Normal
    'grade.caution': '주의',                      // Caution
    'grade.warning': '경고',                      // Warning
    'grade.danger': '위험',                       // Danger

    // ── 방향성 ──
    'dir.cardLabel': '향후 방향성',               // 카드 라벨
    'dir.bullish': '상승 우세',                   // 상승 우세
    'dir.bearish': '하락 우세',                   // 하락 우세
    'dir.unclear': '방향 불명',                   // 방향 불명
    'dir.noData': '데이터 부족',                  // 데이터 부족
    'dir.netScore': '순방향 점수 (상승 − 하락)',  // net score 라벨
    'dir.percentile': '과거 대비',                // 백분위 접두어
    'dir.top': '상위',                            // 상위 접두어
    'dir.similarPeriod': '과거 유사 구간(±{margin}) 기준 미래 수익률', // 유사 구간

    // ── 방향성 통계 테이블 ──
    'dir.period': '기간',                         // 기간 헤더
    'dir.avgReturn': '평균',                      // 평균 헤더
    'dir.upProb': '상승확률',                     // 상승확률 헤더
    'dir.sampleCount': '표본',                    // 표본 헤더
    'dir.5d': '5일 후',                           // 5일
    'dir.10d': '10일 후',                         // 10일
    'dir.20d': '20일 후',                         // 20일
    'dir.cases': '건',                            // 건 단위

    // ── CS 히스토리 테이블 ──
    'hist.date': '날짜',                          // 날짜
    'hist.crash': '하락',                         // 하락
    'hist.surge': '상승',                         // 상승
    'hist.direction': '방향',                     // 방향

    // ── 차트 / 공통 ──
    'chart.noData': '데이터 없음',                // 데이터 없음
    'chart.yTop': '불일치',                       // Y축 상단
    'chart.yBottom': '일치',                      // Y축 하단

    // ── 캔들스틱 차트 탭 ──
    'chart.daily': '일봉',
    'chart.weekly': '주봉',
    'chart.monthly': '월봉',
    'chart.volume': '거래량',
    'chart.lastClose': '종가',
    'chart.prevChg': '전일 대비',
    'chart.period6m': '6개월 수익률',
    'chart.period2y': '2년 수익률',
    'chart.period5y': '5년 수익률',
    'chart.high': '최고가',
    'chart.low': '최저가',
    'chart.range': '변동폭',
    'chart.predictBtn': '30일 예측',
    'chart.predictTitle': '30일 주가 예측 (Prophet)',
    'chart.predictActual': '실제 종가',
    'chart.predictForecast': '예측',
    'chart.predictConfidence': '80% 신뢰구간',
    'chart.predictLoading': '예측 모델 실행 중...',

    // ── 상세 페이지 ──
    'detail.back': '← 뒤로',                     // 뒤로
    'detail.mlLabel': '머신러닝 학습 지표',        // 상세페이지 서브타이틀
    'detail.noData': '데이터 없음',               // 데이터 없음
    'detail.currentPhase': '현재 국면',           // 현재 국면
    'detail.noiseScore': 'Noise Score:',          // 노이즈 점수
    'detail.noiseComposition': '노이즈 점수 구성', // 노이즈 구성
    'detail.currentIndicators': '현재 지표 수치',  // 현재 지표
    'detail.usedIndicators': '분석에 사용된 지표',  // 사용 지표
    'detail.shapTitle': 'SHAP 기여도',            // SHAP 제목
    'detail.shapCrash': '하락',                   // SHAP 하락 방향
    'detail.shapSurge': '상승',                   // SHAP 상승 방향
    'detail.shapDirection': '{type} 방향',        // SHAP 방향 텍스트
    'detail.noShap': 'SHAP 분석 데이터가 아직 없습니다.\n파이프라인을 다시 실행하면 표시됩니다.', // SHAP 없음
    'detail.noFeature': '지표 분석 데이터가 아직 없습니다.\n파이프라인을 다시 실행하면 표시됩니다.', // 피처 없음

    // ── 토스트 ──
    'toast.backExit': '한 번 더 누르면 종료됩니다', // 뒤로가기 토스트

    // ── 면책 ──
    'disclaimer.text': '본 정보는 투자 권유 목적이 아니며, 투자 판단의 책임은 이용자 본인에게 있습니다. 제공되는 데이터와 분석 결과는 참고용이며, 정확성이나 완전성을 보장하지 않습니다.', // 면책 문구

    // ── 방향성 에러/대기 ──
    'dir.loading': '백필 데이터 대기 중...',       // 대기 중
    'dir.loadError': '방향성 분석 로딩 실패',      // 로딩 실패

    // ── Ticker 라벨 ──
    'ticker.QQQ': '나스닥 100',                   // QQQ
    'ticker.SOXX': '필라델피아 반도체',            // SOXX
    'ticker.BND': '미국 채권',                    // BND
    'ticker.IWM': '러셀 2000',                    // IWM
    'ticker.DIA': '다우존스',                     // DIA

    // ── AVAILABLE_HOLDINGS 이름 ──
    'hold.SPY': 'S&P 500',                        // SPY
    'hold.QQQ': '나스닥 100',                     // QQQ
    'hold.DIA': '다우존스',                       // DIA
    'hold.IWM': '러셀 2000',                      // IWM
    'hold.VTI': '미국 전체',                      // VTI
    'hold.VOO': 'S&P 500 (V)',                     // VOO
    'hold.SOXX': '반도체',                        // SOXX
    'hold.SMH': '반도체 (VN)',                    // SMH
    'hold.XLK': '기술',                           // XLK
    'hold.XLF': '금융',                           // XLF
    'hold.XLE': '에너지',                         // XLE
    'hold.XLV': '헬스케어',                       // XLV
    'hold.XLB': '소재',                           // XLB
    'hold.XLP': '필수소비재',                     // XLP
    'hold.XLU': '유틸리티',                       // XLU
    'hold.XLI': '산업재',                         // XLI
    'hold.XLRE': '부동산',                        // XLRE
    'hold.ARKK': '혁신 기술',                     // ARKK
    'hold.GLD': '금',                             // GLD
    'hold.SLV': '은',                             // SLV
    'hold.TLT': '장기국채',                       // TLT
    'hold.BND': '미국 채권',                      // BND
    'hold.SCHD': '미국 배당',                     // SCHD
    'hold.VXUS': '미국 외 주식',                  // VXUS

    // ── 섹터 라벨 ──
    'sector.XLF': '금융',                         // XLF
    'sector.XLE': '에너지',                       // XLE
    'sector.XLK': '기술',                         // XLK
    'sector.XLV': '헬스케어',                     // XLV
    'sector.XLB': '소재',                         // XLB
    'sector.XLP': '필수소비재',                   // XLP
    'sector.XLU': '유틸리티',                     // XLU
    'sector.XLI': '산업재',                       // XLI
    'sector.XLRE': '부동산',                      // XLRE
    'sector.SOXX': '반도체',                      // SOXX

    // ── 경기 국면명 (API 응답 한글) ──
    'phase.recovery': '회복',                     // Recovery
    'phase.expansion': '확장',                    // Expansion
    'phase.slowdown': '둔화',                     // Slowdown
    'phase.contraction': '침체',                  // Contraction

    // ── 경기 국면 설명 ──
    'phase.sub.recovery': '경기 저점을 지나 반등이 시작되는 구간',    // Recovery 설명
    'phase.sub.expansion': '경기가 활발하게 성장하는 구간',            // Expansion 설명
    'phase.sub.slowdown': '성장 속도가 줄어들기 시작하는 구간',       // Slowdown 설명
    'phase.sub.contraction': '경기가 위축되고 수요가 감소하는 구간',  // Contraction 설명

    // ── 섹터 상세 ──
    'sector.detailTitle': '거시경제 상세',         // 상세 제목
    'sector.macroSnapshot': '매크로 스냅샷',       // 매크로 섹션
    'sector.macroDesc': '매크로 지표 설명',        // 매크로 설명 섹션
    'sector.phasePerf': '국면별 섹터 수익률',      // 국면별 수익률
    'sector.topSectors': '현재 국면 추천 섹터',    // 추천 섹터
    'sector.current': '현재',                      // 현재 라벨
    'sector.phase': '국면',                        // 국면 라벨
    'sector.holdNoSetup': '보유종목을 설정하면 현재 국면 성과를 확인할 수 있습니다', // 미설정
    'sector.holdNoData': '현재 국면의 보유종목 데이터가 없습니다',     // 데이터 없음
    'sector.phaseAvgReturn': '국면 평균 수익률',   // 평균 수익률

    // ── 매크로 라벨 ──
    'macro.pmi': 'PMI',                           // PMI
    'macro.yield_spread': '금리차 (10Y-3M)',      // 금리차
    'macro.anfci': '금융환경 (ANFCI)',             // ANFCI
    'macro.icsa_yoy': '실업급여 YoY',             // 실업급여
    'macro.permit_yoy': '건축허가 YoY',           // 건축허가
    'macro.real_retail_yoy': '실질소매판매 YoY',  // 소매판매
    'macro.capex_yoy': '자본재주문 YoY',          // 자본재
    'macro.real_income_yoy': '실질소득 YoY',      // 실질소득
    'macro.pmi_chg3m': 'PMI 3개월변화',           // PMI 변화
    'macro.capex_yoy_chg3m': '자본재 3개월변화',  // 자본재 변화

    // ── 매크로 설명 ──
    'macroDesc.pmi': '제조업 경기를 나타내는 구매관리자지수 (50 이상 확장)',
    'macroDesc.yield_spread': '장단기 금리차 (10년-3개월, 역전 시 침체 신호)',
    'macroDesc.anfci': '시카고 연준 금융환경지수 (음수=완화, 양수=긴축)',
    'macroDesc.icsa_yoy': '신규 실업급여 청구건수 전년비 변화율',
    'macroDesc.permit_yoy': '건축허가 전년비 변화율 (부동산 선행지표)',
    'macroDesc.real_retail_yoy': '실질 소매판매 전년비 변화율 (소비 지표)',
    'macroDesc.capex_yoy': '비국방 자본재 주문 전년비 변화율 (기업투자)',
    'macroDesc.real_income_yoy': '실질 개인소득 전년비 변화율',
    'macroDesc.pmi_chg3m': 'PMI 3개월 변화량 (모멘텀)',
    'macroDesc.capex_yoy_chg3m': '자본재 주문 YoY 3개월 변화량',

    // ── CS 피처 라벨 ──
    'feat.SP500_LOGRET_1D': '1일 수익률',
    'feat.SP500_LOGRET_5D': '5일 수익률',
    'feat.SP500_LOGRET_10D': '10일 수익률',
    'feat.SP500_LOGRET_20D': '20일 수익률',
    'feat.SP500_DRAWDOWN_60D': '60일 낙폭',
    'feat.SP500_MA_GAP_50': '50일선 괴리',
    'feat.SP500_MA_GAP_200': '200일선 괴리',
    'feat.SP500_INTRADAY_RANGE': '일중 변동폭',
    'feat.RV_5D': '5일 실현변동성',
    'feat.RV_21D': '21일 실현변동성',
    'feat.EWMA_VOL_L94': 'EWMA 변동성',
    'feat.VOL_OF_VOL_21D': '변동성의 변동성',
    'feat.HY_OAS': '하이일드 스프레드',
    'feat.BBB_OAS': 'BBB 스프레드',
    'feat.CCC_OAS': 'CCC 스프레드',
    'feat.DGS10_LEVEL': '10년 금리',
    'feat.T10Y3M_SLOPE': '수익률곡선',
    'feat.VIX_LEVEL': 'VIX',
    'feat.VIX_CHANGE_1D': 'VIX 1일변화',
    'feat.VIX_PCTL_252D': 'VIX 백분위',
    'feat.VXV_MINUS_VIX': 'VIX 기간구조',
    'feat.SKEW_LEVEL': 'SKEW',
    'feat.DTWEXBGS_RET_5D': '달러 5일수익',
    'feat.WTI_RET_5D': '원유 5일수익',
    'feat.VIX9D_MINUS_VIX': '9일-1개월 VIX',
    'feat.VVIX_LEVEL': 'VVIX',
    'feat.VARIANCE_RISK_PREMIUM': '분산 리스크 프리미엄',
    'feat.PARKINSON_VOL_21D': '파킨슨 변동성',
    'feat.SP500_AMIHUD_ILLIQ_20D': '비유동성',
    'feat.SP500_DOLLAR_VOLUME_Z_20D': '거래대금 Z',
    'feat.DFII10_REAL10Y': '실질금리',
    'feat.T10YIE_BREAKEVEN': '기대인플레',
    'feat.SOFR_MINUS_EFFR': 'SOFR-EFFR',
    'feat.NFCI_LEVEL': 'NFCI',
    'feat.CORR_EQ_DGS10_60D': '주식-금리 상관',
    'feat.HY_OAS_CHG_5D': 'HY 5일변화',
    'feat.HY_OAS_CHG_20D': 'HY 20일변화',
    'feat.BBB_OAS_CHG_5D': 'BBB 5일변화',
    'feat.BBB_OAS_CHG_20D': 'BBB 20일변화',
    'feat.CCC_OAS_CHG_5D': 'CCC 5일변화',
    'feat.CCC_OAS_CHG_20D': 'CCC 20일변화',
    'feat.VIX9D_VIX_RATIO': '9일/1개월 VIX비',
    'feat.VIX_VIX3M_RATIO': 'VIX/3개월 비율',
    'feat.VIX_CHG_5D': 'VIX 5일변화',

    // ── CS 피처 설명 ──
    'featDesc.SP500_LOGRET_1D': '전일 종가 대비 등락. 하루 -2% 이상 급락은 투매 시작, +2% 이상은 숏커버링 반등일 가능성',
    'featDesc.SP500_LOGRET_5D': '1주간 누적 수익률. 연속 하락 시 마진콜·펀드 환매 압력이 폭락을 가속',
    'featDesc.SP500_LOGRET_10D': '2주간 추세. 10일 연속 하락은 시장 심리가 항복 단계에 진입했다는 의미',
    'featDesc.SP500_LOGRET_20D': '한 달 모멘텀. 월간 -10% 이상이면 공식적 조정(correction) 영역',
    'featDesc.SP500_DRAWDOWN_60D': '분기 고점 대비 하락폭. -20% 이상이면 약세장(bear market) 진입 기준',
    'featDesc.SP500_MA_GAP_50': '50일 이평선은 기관 트레이더의 중기 추세 기준선. 이탈 시 추세추종 매도 발생',
    'featDesc.SP500_MA_GAP_200': '200일선은 강세/약세장 경계. 이탈 시 연기금·패시브 펀드의 리밸런싱 매도 촉발',
    'featDesc.SP500_INTRADAY_RANGE': '장중 고가-저가 차이. 평소 대비 2배 이상이면 대형 기관의 급박한 포지션 청산 진행 중',
    'featDesc.RV_5D': '최근 1주 실제 주가 변동. 갑자기 커지면 시장에 예상 못한 충격이 발생한 것',
    'featDesc.RV_21D': '한 달간 실제 변동. 장기 고변동은 불확실성이 해소되지 않고 있다는 의미',
    'featDesc.EWMA_VOL_L94': '최근 움직임에 가중치를 둔 변동성. 갑작스런 상승은 새로운 리스크 출현 신호',
    'featDesc.VOL_OF_VOL_21D': '변동성 자체가 요동치면 시장 참여자들이 리스크를 가늠하지 못하는 패닉 상태',
    'featDesc.HY_OAS': '정크본드와 국채의 금리 차. 확대 시 기업 부도 우려 → 주식에서도 자금 이탈',
    'featDesc.BBB_OAS': '투자등급 최하위. 이 스프레드가 뛰면 "투자부적격 강등" 도미노 우려 확산',
    'featDesc.CCC_OAS': '최저등급 채권 스프레드. 2008년, 2020년 폭락 직전 가장 먼저 급등한 지표',
    'featDesc.DGS10_LEVEL': '모든 자산 가격의 할인율. 급등하면 성장주 밸류에이션 하락, 급락하면 경기침체 공포',
    'featDesc.T10Y3M_SLOPE': '장단기 금리 차. 역전(음수)되면 은행 수익성 악화 + 경기침체 6~18개월 전 경고',
    'featDesc.VIX_LEVEL': 'S&P 500 옵션의 향후 30일 기대 변동성. 20 이하=평온, 30+=공포, 40+=패닉',
    'featDesc.VIX_CHANGE_1D': '하루 VIX 급등(+5pt 이상)은 대형 헤지펀드의 긴급 풋옵션 매수를 반영',
    'featDesc.VIX_PCTL_252D': '1년 중 현재 VIX의 상대 위치. 90% 이상이면 역사적으로 극단적 공포 수준',
    'featDesc.VXV_MINUS_VIX': '3개월 VIX - 1개월 VIX. 음수(역전)면 "지금 당장"의 위험이 더 크다는 시장 합의',
    'featDesc.SKEW_LEVEL': '풋옵션의 꼬리위험 프리미엄. 높으면 월가가 "블랙스완" 이벤트에 보험을 사는 중',
    'featDesc.DTWEXBGS_RET_5D': '달러 강세 시 글로벌 달러 부채 부담 증가 → EM 자금 이탈 → 미국 주식에도 전이',
    'featDesc.WTI_RET_5D': '원유 급락은 수요 둔화(경기침체), 급등은 공급 쇼크(인플레). 양쪽 다 주식에 악재',
    'featDesc.VIX9D_MINUS_VIX': '9일 VIX가 더 높으면 "며칠 내" 급변을 시장이 예상. 폭락 직전에 나타나는 패턴',
    'featDesc.VVIX_LEVEL': 'VIX 옵션의 변동성. 공포지수 자체가 요동치면 시장이 방향을 못 잡는 극단적 혼란',
    'featDesc.VARIANCE_RISK_PREMIUM': '옵션 내재 변동성 - 실현 변동성. 클수록 시장이 "앞으로 더 흔들릴 것"에 프리미엄 지불',
    'featDesc.PARKINSON_VOL_21D': '장중 고가-저가로 측정한 변동성. 종가만으로 놓치는 장중 급등락을 포착',
    'featDesc.SP500_AMIHUD_ILLIQ_20D': '거래량 대비 가격 변동. 높으면 시장에 매수자가 부족해 소량 매도에도 가격이 급락',
    'featDesc.SP500_DOLLAR_VOLUME_Z_20D': '20일 평균 대비 거래대금 이상치. 폭증은 투매 또는 바닥 매수세 유입',
    'featDesc.DFII10_REAL10Y': '인플레 차감 후 실제 자금조달 비용. 높으면 기업 이익 압박 → 주가 하방 압력',
    'featDesc.T10YIE_BREAKEVEN': '채권시장이 예상하는 10년 평균 물가상승률. 급등 시 연준 긴축 우려, 급락 시 디플레 공포',
    'featDesc.SOFR_MINUS_EFFR': '단기 자금시장 금리 스프레드. 확대되면 은행 간 신뢰 저하(2008년·2019년 레포 위기)',
    'featDesc.NFCI_LEVEL': '시카고연은 금융상황지수. 0 이상이면 대출·채권·주식 시장 전반이 긴축적',
    'featDesc.CORR_EQ_DGS10_60D': '양(+)이면 "금리↑=주가↓" 동조. 인플레 시대의 위험 체제를 나타냄',
    'featDesc.HY_OAS_CHG_5D': '1주간 하이일드 스프레드 변화. 급확대는 채권 시장의 패닉이 주식보다 먼저 시작된 것',
    'featDesc.HY_OAS_CHG_20D': '한 달간 추세적 확대는 일시적 충격이 아닌 구조적 신용경색 진행을 의미',
    'featDesc.BBB_OAS_CHG_5D': '투자등급 스프레드 급변은 대형 기관의 회사채 투매. 주식시장 폭락에 선행',
    'featDesc.BBB_OAS_CHG_20D': 'BBB 스프레드 추세적 확대 시 기업들의 차환(리파이낸싱) 비용 급증 → 실적 악화',
    'featDesc.CCC_OAS_CHG_5D': '최저등급 스프레드 급등은 부도 연쇄 우려. 리먼 사태 직전에 가장 먼저 반응한 지표',
    'featDesc.CCC_OAS_CHG_20D': '정크본드 시장의 추세적 악화. 장기 확대는 금융위기급 시스템 리스크',
    'featDesc.VIX9D_VIX_RATIO': '1 초과 시 "이번 주"의 공포가 "이번 달"보다 큼. 급락이 임박한 시장 구조',
    'featDesc.VIX_VIX3M_RATIO': '1 초과(기간구조 역전)면 시장이 단기 급변을 확신. 정상 복귀 시 최악은 지났다는 신호',
    'featDesc.VIX_CHG_5D': '1주간 VIX 추세. 한 번 튀고 바로 내려오면 일시 충격, 계속 오르면 위기 심화',

    // ── NR 피처 라벨 ──
    'feat.fundamental_gap': '펀더멘털 괴리',
    'feat.erp_zscore': 'ERP Z점수',
    'feat.residual_corr': '잔차 상관',
    'feat.dispersion': '분산도',
    'feat.amihud': '비유동성',
    'feat.vix_term': 'VIX 기간구조',
    'feat.hy_spread': '하이일드 스프레드',
    'feat.realized_vol': '실현 변동성',

    // ── NR 피처 설명 ──
    'featDesc.fundamental_gap': 'Shiller CAPE 기반 적정가 대비 괴리. 괴리가 크면 시장이 펀더멘털이 아닌 투자심리로 움직이는 구간',
    'featDesc.erp_zscore': '주식위험 프리미엄(기대수익-무위험수익)의 역사적 위치. 극단이면 시장 가격이 합리적 범위를 벗어남',
    'featDesc.residual_corr': '펀더멘털로 설명되지 않는 주가 움직임의 동조화. 높으면 "뉴스·심리"가 시장을 지배하는 구간',
    'featDesc.dispersion': '종목 간 수익률 차이. 낮으면 시장 전체가 한 방향으로 쏠리는 센티멘트 장세, 높으면 종목별 펀더멘털이 반영되는 선별 장세',
    'featDesc.amihud': '거래량 대비 가격 충격. 유동성이 마르면 소수 거래로 가격이 왜곡되어 펀더멘털에서 이탈하기 쉬움',
    'featDesc.vix_term': 'VIX 선물 원월물-근월물 차이. 역전되면 "지금 당장"의 공포가 극심해 심리 주도 장세',
    'featDesc.hy_spread': '정크본드 스프레드. 신용시장 공포가 주식까지 전이되면 펀더멘털과 무관하게 일괄 매도 발생',
    'featDesc.realized_vol': '실제 주가 변동 크기. 변동성이 높은 구간은 투자자들이 이성보다 감정으로 거래하는 전형적 노이즈 국면',
  },

  en: {
    // ── Tabs ──
    'tab.market': 'Market',
    'tab.signal': 'Signal',
    'tab.macro': 'Macro',
    'tab.chart': 'Chart',

    // ── Header / Date ──
    'lang.btn': 'KO',

    // ── Holdings Setup ──
    'holdings.back': '← Back',
    'holdings.title': 'Holdings Setup',
    'holdings.desc': 'Select the ETFs you are investing in',
    'holdings.search': 'Search ETF (e.g. QQQ, SPY...)',
    'holdings.selectedLabel': 'Selected',
    'holdings.confirm': 'Get Started',
    'holdings.selectPrompt': 'Please select holdings',
    'holdings.setPrompt': 'Set up your holdings',
    'holdings.loading': 'Loading data...',
    'holdings.noData': 'No price data for your holdings',
    'holdings.loadError': 'Failed to load data',

    // ── Noise vs Signal ──
    'nr.fundamental': 'Fundamental',
    'nr.price': 'Price',
    'nr.match': 'Aligned',
    'nr.gap': 'Diverged',

    // ── NR Phase Names ──
    'nr.phase.fundamental': 'Fundamental',
    'nr.phase.weakFundamental': 'Weak Fundamental',
    'nr.phase.weakSentiment': 'Weak Sentiment',
    'nr.phase.sentiment': 'Sentiment',

    // ── NR Phase Descriptions ──
    'nr.sub.fundamental': 'Price reflects fundamentals',
    'nr.sub.weakFundamental': 'Price reflects fundamentals',
    'nr.sub.weakSentiment': 'Price diverges from fundamentals',
    'nr.sub.sentiment': 'Price diverges from fundamentals',

    // ── NR Badges ──
    'nr.badge.stable': 'Stable',
    'nr.badge.caution': 'Caution',
    'nr.badge.alert': 'Alert',
    'nr.badge.danger': 'Danger',

    // ── Section Labels ──
    'section.nrChart': 'Fundamental·Price Trend (30d)',
    'section.myHoldings': 'My Holdings',
    'section.csChart': 'Direction Trend (30d)',

    // ── VIX Levels ──
    'vix.low': 'Low',
    'vix.normal': 'Normal',
    'vix.high': 'High',
    'vix.danger': 'Danger',

    // ── VOL Levels ──
    'vol.surge': 'Volume Surge',
    'vol.above': 'Above Avg',
    'vol.avg': 'Average',
    'vol.low': 'Low Volume',

    // ── P/C Labels ──
    'pc.bearish': 'Bearish',
    'pc.bullish': 'Bullish',
    'pc.neutral': 'Neutral',

    // ── Market Overview ──
    'mo.title': 'Market Summary',
    'mo.fearGreed': 'Fear & Greed Index',
    'mo.marketReturn': 'Major Index Return',
    'mo.rsi': 'S&P500 RSI (14)',

    // ── RSI Labels ──
    'rsi.overbought': 'Overbought',
    'rsi.oversold': 'Oversold',
    'rsi.neutral': 'Neutral',

    // ── Fear & Greed Ratings ──
    'fg.extremeGreed': 'Extreme Greed',
    'fg.greed': 'Greed',
    'fg.neutral': 'Neutral',
    'fg.fear': 'Fear',
    'fg.extremeFear': 'Extreme Fear',

    // ── Crash/Surge ──
    'cs.crashRisk': 'Crash Risk',
    'cs.surgeExpect': 'Surge Potential',
    'cs.cardLabel': 'Crash/Surge',
    'cs.detailTitle': 'Crash/Surge Analysis',
    'cs.asOf': 'as of',
    'cs.modelF1': 'Model F1:',

    // ── Grades ──
    'grade.low': 'Low',
    'grade.normal': 'Normal',
    'grade.caution': 'Caution',
    'grade.warning': 'Warning',
    'grade.danger': 'Danger',

    // ── Direction ──
    'dir.cardLabel': 'Future Direction',
    'dir.bullish': 'Bullish',
    'dir.bearish': 'Bearish',
    'dir.unclear': 'Unclear',
    'dir.noData': 'No Data',
    'dir.netScore': 'Net Score (Surge − Crash)',
    'dir.percentile': 'vs History',
    'dir.top': 'Top',
    'dir.similarPeriod': 'Future returns based on similar periods (±{margin})',

    // ── Direction Stats Table ──
    'dir.period': 'Period',
    'dir.avgReturn': 'Avg',
    'dir.upProb': 'Up Prob',
    'dir.sampleCount': 'Samples',
    'dir.5d': '5-Day',
    'dir.10d': '10-Day',
    'dir.20d': '20-Day',
    'dir.cases': '',

    // ── CS History Table ──
    'hist.date': 'Date',
    'hist.crash': 'Crash',
    'hist.surge': 'Surge',
    'hist.direction': 'Dir',

    // ── Chart / Common ──
    'chart.noData': 'No Data',
    'chart.yTop': 'Diverged',
    'chart.yBottom': 'Aligned',

    // ── Candlestick Chart Tab ──
    'chart.daily': 'Daily',
    'chart.weekly': 'Weekly',
    'chart.monthly': 'Monthly',
    'chart.volume': 'Volume',
    'chart.lastClose': 'Close',
    'chart.prevChg': 'Prev Chg',
    'chart.period6m': '6M Return',
    'chart.period2y': '2Y Return',
    'chart.period5y': '5Y Return',
    'chart.high': 'High',
    'chart.low': 'Low',
    'chart.range': 'Range',
    'chart.predictBtn': '30-Day Forecast',
    'chart.predictTitle': '30-Day Price Forecast (Prophet)',
    'chart.predictActual': 'Actual Close',
    'chart.predictForecast': 'Forecast',
    'chart.predictConfidence': '80% Confidence',
    'chart.predictLoading': 'Running forecast model...',

    // ── Detail Page ──
    'detail.back': '← Back',
    'detail.mlLabel': 'ML-Based Indicators',
    'detail.noData': 'No Data',
    'detail.currentPhase': 'Current Phase',
    'detail.noiseScore': 'Noise Score:',
    'detail.noiseComposition': 'Noise Score Breakdown',
    'detail.currentIndicators': 'Current Indicators',
    'detail.usedIndicators': 'Indicators Used',
    'detail.shapTitle': 'SHAP Contributions',
    'detail.shapCrash': 'Crash',
    'detail.shapSurge': 'Surge',
    'detail.shapDirection': '{type} direction',
    'detail.noShap': 'SHAP analysis data not yet available.\nRun the pipeline again to generate.',
    'detail.noFeature': 'Indicator analysis data not yet available.\nRun the pipeline again to generate.',

    // ── Toast ──
    'toast.backExit': 'Press back again to exit',

    // ── Disclaimer ──
    'disclaimer.text': 'This information is not intended as investment advice. Investment decisions are the sole responsibility of the user. Data and analysis are for reference only and accuracy is not guaranteed.', // 면책 문구

    // ── Direction Error/Loading ──
    'dir.loading': 'Waiting for backfill data...',
    'dir.loadError': 'Failed to load direction analysis',

    // ── Ticker Labels ──
    'ticker.QQQ': 'Nasdaq 100',
    'ticker.SOXX': 'PHLX Semiconductor',
    'ticker.BND': 'US Bond',
    'ticker.IWM': 'Russell 2000',
    'ticker.DIA': 'Dow Jones',

    // ── AVAILABLE_HOLDINGS Names ──
    'hold.SPY': 'S&P 500',
    'hold.QQQ': 'Nasdaq 100',
    'hold.DIA': 'Dow Jones',
    'hold.IWM': 'Russell 2000',
    'hold.VTI': 'Total US',
    'hold.VOO': 'S&P 500 (V)',
    'hold.SOXX': 'Semiconductor',
    'hold.SMH': 'Semiconductor (VN)',
    'hold.XLK': 'Technology',
    'hold.XLF': 'Financials',
    'hold.XLE': 'Energy',
    'hold.XLV': 'Healthcare',
    'hold.XLB': 'Materials',
    'hold.XLP': 'Consumer Staples',
    'hold.XLU': 'Utilities',
    'hold.XLI': 'Industrials',
    'hold.XLRE': 'Real Estate',
    'hold.ARKK': 'Innovation',
    'hold.GLD': 'Gold',
    'hold.SLV': 'Silver',
    'hold.TLT': 'Long-Term Treasury',
    'hold.BND': 'US Bond',
    'hold.SCHD': 'US Dividend',
    'hold.VXUS': 'Ex-US Equity',

    // ── Sector Labels ──
    'sector.XLF': 'Financials',
    'sector.XLE': 'Energy',
    'sector.XLK': 'Technology',
    'sector.XLV': 'Healthcare',
    'sector.XLB': 'Materials',
    'sector.XLP': 'Consumer Staples',
    'sector.XLU': 'Utilities',
    'sector.XLI': 'Industrials',
    'sector.XLRE': 'Real Estate',
    'sector.SOXX': 'Semiconductor',

    // ── Phase Names ──
    'phase.recovery': 'Recovery',
    'phase.expansion': 'Expansion',
    'phase.slowdown': 'Slowdown',
    'phase.contraction': 'Contraction',

    // ── Phase Descriptions ──
    'phase.sub.recovery': 'Economy rebounding from bottom',
    'phase.sub.expansion': 'Economy actively growing',
    'phase.sub.slowdown': 'Growth momentum fading',
    'phase.sub.contraction': 'Economy contracting, demand falling',

    // ── Sector Detail ──
    'sector.detailTitle': 'Macro Detail',
    'sector.macroSnapshot': 'Macro Snapshot',
    'sector.macroDesc': 'Macro Indicator Guide',
    'sector.phasePerf': 'Sector Performance by Phase',
    'sector.topSectors': 'Top Sectors for Current Phase',
    'sector.current': 'Current',
    'sector.phase': 'Phase',
    'sector.holdNoSetup': 'Set up holdings to see performance for this phase',
    'sector.holdNoData': 'No holding data for current phase',
    'sector.phaseAvgReturn': 'Phase Avg Return',

    // ── Macro Labels ──
    'macro.pmi': 'PMI',
    'macro.yield_spread': 'Yield Spread (10Y-3M)',
    'macro.anfci': 'Financial Conditions (ANFCI)',
    'macro.icsa_yoy': 'Jobless Claims YoY',
    'macro.permit_yoy': 'Building Permits YoY',
    'macro.real_retail_yoy': 'Real Retail Sales YoY',
    'macro.capex_yoy': 'CapEx Orders YoY',
    'macro.real_income_yoy': 'Real Income YoY',
    'macro.pmi_chg3m': 'PMI 3M Change',
    'macro.capex_yoy_chg3m': 'CapEx 3M Change',

    // ── Macro Descriptions ──
    'macroDesc.pmi': 'Purchasing Managers Index (above 50 = expansion)',
    'macroDesc.yield_spread': 'Long-short yield spread (10Y-3M, inversion = recession signal)',
    'macroDesc.anfci': 'Chicago Fed Financial Conditions Index (negative=loose, positive=tight)',
    'macroDesc.icsa_yoy': 'Initial jobless claims year-over-year change',
    'macroDesc.permit_yoy': 'Building permits YoY change (housing leading indicator)',
    'macroDesc.real_retail_yoy': 'Real retail sales YoY change (consumption indicator)',
    'macroDesc.capex_yoy': 'Nondefense capital goods orders YoY change (business investment)',
    'macroDesc.real_income_yoy': 'Real personal income YoY change',
    'macroDesc.pmi_chg3m': 'PMI 3-month change (momentum)',
    'macroDesc.capex_yoy_chg3m': 'Capital goods orders YoY 3-month change',

    // ── CS Feature Labels ──
    'feat.SP500_LOGRET_1D': '1D Return',
    'feat.SP500_LOGRET_5D': '5D Return',
    'feat.SP500_LOGRET_10D': '10D Return',
    'feat.SP500_LOGRET_20D': '20D Return',
    'feat.SP500_DRAWDOWN_60D': '60D Drawdown',
    'feat.SP500_MA_GAP_50': '50 MA Gap',
    'feat.SP500_MA_GAP_200': '200 MA Gap',
    'feat.SP500_INTRADAY_RANGE': 'Intraday Range',
    'feat.RV_5D': '5D Realized Vol',
    'feat.RV_21D': '21D Realized Vol',
    'feat.EWMA_VOL_L94': 'EWMA Volatility',
    'feat.VOL_OF_VOL_21D': 'Vol of Vol',
    'feat.HY_OAS': 'HY Spread',
    'feat.BBB_OAS': 'BBB Spread',
    'feat.CCC_OAS': 'CCC Spread',
    'feat.DGS10_LEVEL': '10Y Yield',
    'feat.T10Y3M_SLOPE': 'Yield Curve',
    'feat.VIX_LEVEL': 'VIX',
    'feat.VIX_CHANGE_1D': 'VIX 1D Change',
    'feat.VIX_PCTL_252D': 'VIX Percentile',
    'feat.VXV_MINUS_VIX': 'VIX Term Structure',
    'feat.SKEW_LEVEL': 'SKEW',
    'feat.DTWEXBGS_RET_5D': 'USD 5D Return',
    'feat.WTI_RET_5D': 'WTI 5D Return',
    'feat.VIX9D_MINUS_VIX': '9D-1M VIX',
    'feat.VVIX_LEVEL': 'VVIX',
    'feat.VARIANCE_RISK_PREMIUM': 'Variance Risk Premium',
    'feat.PARKINSON_VOL_21D': 'Parkinson Vol',
    'feat.SP500_AMIHUD_ILLIQ_20D': 'Illiquidity',
    'feat.SP500_DOLLAR_VOLUME_Z_20D': 'Dollar Volume Z',
    'feat.DFII10_REAL10Y': 'Real Yield',
    'feat.T10YIE_BREAKEVEN': 'Breakeven Inflation',
    'feat.SOFR_MINUS_EFFR': 'SOFR-EFFR',
    'feat.NFCI_LEVEL': 'NFCI',
    'feat.CORR_EQ_DGS10_60D': 'Equity-Rate Corr',
    'feat.HY_OAS_CHG_5D': 'HY 5D Change',
    'feat.HY_OAS_CHG_20D': 'HY 20D Change',
    'feat.BBB_OAS_CHG_5D': 'BBB 5D Change',
    'feat.BBB_OAS_CHG_20D': 'BBB 20D Change',
    'feat.CCC_OAS_CHG_5D': 'CCC 5D Change',
    'feat.CCC_OAS_CHG_20D': 'CCC 20D Change',
    'feat.VIX9D_VIX_RATIO': '9D/1M VIX Ratio',
    'feat.VIX_VIX3M_RATIO': 'VIX/3M Ratio',
    'feat.VIX_CHG_5D': 'VIX 5D Change',

    // ── CS Feature Descriptions ──
    'featDesc.SP500_LOGRET_1D': 'Daily return vs previous close. A -2%+ drop signals panic selling, +2%+ may be a short-covering bounce',
    'featDesc.SP500_LOGRET_5D': 'Weekly cumulative return. Consecutive drops accelerate crashes via margin calls and fund redemptions',
    'featDesc.SP500_LOGRET_10D': 'Two-week trend. Ten consecutive down days suggest market psychology has entered capitulation',
    'featDesc.SP500_LOGRET_20D': 'Monthly momentum. A -10%+ monthly decline is officially correction territory',
    'featDesc.SP500_DRAWDOWN_60D': 'Drop from quarterly high. -20%+ is the bear market threshold',
    'featDesc.SP500_MA_GAP_50': '50-day MA is the institutional medium-term trend line. Breaks trigger trend-following sells',
    'featDesc.SP500_MA_GAP_200': '200-day MA separates bull/bear markets. Breaks trigger pension and passive fund rebalancing',
    'featDesc.SP500_INTRADAY_RANGE': 'Intraday high-low range. 2x normal suggests urgent institutional position unwinding',
    'featDesc.RV_5D': 'Actual price movements over 1 week. Sudden spikes indicate unexpected market shocks',
    'featDesc.RV_21D': 'Monthly actual volatility. Sustained high volatility means uncertainty persists',
    'featDesc.EWMA_VOL_L94': 'Exponentially weighted volatility. Sudden rises signal emerging new risks',
    'featDesc.VOL_OF_VOL_21D': 'When volatility itself fluctuates wildly, participants cannot gauge risk — a panic state',
    'featDesc.HY_OAS': 'Junk bond vs Treasury spread. Widening indicates corporate default fears and equity outflows',
    'featDesc.BBB_OAS': 'Lowest investment-grade spread. Jumps signal "fallen angel" downgrade contagion fears',
    'featDesc.CCC_OAS': 'Lowest-grade bond spread. First to spike before 2008 and 2020 crashes',
    'featDesc.DGS10_LEVEL': 'Discount rate for all assets. Rising hurts growth valuations, falling signals recession fear',
    'featDesc.T10Y3M_SLOPE': 'Long-short yield spread. Inversion = bank profitability decline + recession warning 6-18 months ahead',
    'featDesc.VIX_LEVEL': 'S&P 500 30-day implied volatility. Below 20=calm, 30+=fear, 40+=panic',
    'featDesc.VIX_CHANGE_1D': 'A +5pt daily VIX spike reflects large hedge fund emergency put buying',
    'featDesc.VIX_PCTL_252D': 'Current VIX percentile over 1 year. Above 90% = historically extreme fear',
    'featDesc.VXV_MINUS_VIX': '3-month minus 1-month VIX. Negative (inversion) = "immediate" risk exceeds medium-term',
    'featDesc.SKEW_LEVEL': 'Tail-risk premium on puts. High values mean Wall Street is buying "black swan" insurance',
    'featDesc.DTWEXBGS_RET_5D': 'Strong dollar increases global USD debt burden → EM capital outflows → US equity contagion',
    'featDesc.WTI_RET_5D': 'Oil crash = demand slowdown (recession), oil spike = supply shock (inflation). Both bearish for stocks',
    'featDesc.VIX9D_MINUS_VIX': 'When 9-day VIX exceeds 1-month, market expects "within days" turbulence. Pre-crash pattern',
    'featDesc.VVIX_LEVEL': 'Volatility of VIX. When the fear gauge itself swings wildly, extreme confusion reigns',
    'featDesc.VARIANCE_RISK_PREMIUM': 'Implied minus realized vol. Higher means market pays premium for "more turbulence ahead"',
    'featDesc.PARKINSON_VOL_21D': 'Volatility from intraday high-low. Captures intraday swings missed by close-to-close',
    'featDesc.SP500_AMIHUD_ILLIQ_20D': 'Price impact per volume. High = few buyers, even small sells crash prices',
    'featDesc.SP500_DOLLAR_VOLUME_Z_20D': 'Dollar volume z-score vs 20-day avg. Spike = panic selling or bottom-fishing',
    'featDesc.DFII10_REAL10Y': 'After-inflation borrowing cost. High = corporate earnings pressure → stock downside',
    'featDesc.T10YIE_BREAKEVEN': 'Bond market\'s 10-year inflation forecast. Surge = Fed tightening fear, plunge = deflation fear',
    'featDesc.SOFR_MINUS_EFFR': 'Short-term funding spread. Widening = interbank trust decline (2008, 2019 repo crises)',
    'featDesc.NFCI_LEVEL': 'Chicago Fed Financial Conditions. Above 0 = tightening across lending, bonds, and equities',
    'featDesc.CORR_EQ_DGS10_60D': 'Positive = "rates up = stocks down" co-movement. Indicates inflation-era risk regime',
    'featDesc.HY_OAS_CHG_5D': 'Weekly HY spread change. Rapid widening = bond market panic ahead of equities',
    'featDesc.HY_OAS_CHG_20D': 'Monthly trend widening = structural credit crunch, not just a temporary shock',
    'featDesc.BBB_OAS_CHG_5D': 'IG spread spike = institutional corporate bond dumping. Leads equity crashes',
    'featDesc.BBB_OAS_CHG_20D': 'Sustained BBB widening = surging refinancing costs → earnings deterioration',
    'featDesc.CCC_OAS_CHG_5D': 'Junk spread spike = cascading default fears. First indicator to react before Lehman',
    'featDesc.CCC_OAS_CHG_20D': 'Junk market trending worse. Sustained widening = financial crisis-level systemic risk',
    'featDesc.VIX9D_VIX_RATIO': 'Above 1 = "this week" fear > "this month". Market structure primed for crash',
    'featDesc.VIX_VIX3M_RATIO': 'Above 1 (term inversion) = market expects short-term shock. Normalization = worst is over',
    'featDesc.VIX_CHG_5D': 'Weekly VIX trend. One spike then down = temporary shock; sustained rise = deepening crisis',

    // ── NR Feature Labels ──
    'feat.fundamental_gap': 'Fundamental Gap',
    'feat.erp_zscore': 'ERP Z-Score',
    'feat.residual_corr': 'Residual Correlation',
    'feat.dispersion': 'Dispersion',
    'feat.amihud': 'Illiquidity',
    'feat.vix_term': 'VIX Term Structure',
    'feat.hy_spread': 'HY Spread',
    'feat.realized_vol': 'Realized Volatility',

    // ── NR Feature Descriptions ──
    'featDesc.fundamental_gap': 'Divergence from Shiller CAPE fair value. Large gaps mean sentiment, not fundamentals, drives prices',
    'featDesc.erp_zscore': 'Equity risk premium z-score. Extreme values mean pricing is outside rational bounds',
    'featDesc.residual_corr': 'Co-movement unexplained by fundamentals. High = "news and sentiment" dominate the market',
    'featDesc.dispersion': 'Return dispersion across stocks. Low = entire market moves in one direction (sentiment market)',
    'featDesc.amihud': 'Price impact per volume. Dried-up liquidity causes price distortion away from fundamentals',
    'featDesc.vix_term': 'VIX futures front-back spread. Inversion = extreme immediate fear, sentiment-driven market',
    'featDesc.hy_spread': 'Junk bond spread. When credit fear spills to equities, indiscriminate selling regardless of fundamentals',
    'featDesc.realized_vol': 'Actual price fluctuation. High-volatility periods indicate emotion-driven trading, a classic noise regime',
  }
};

// ── API 응답 한글 → i18n 키 역매핑 테이블 ──

// NR 국면명 → 내부 키
const NR_NAME_TO_KEY = {                          // API 한글 국면명 → i18n 키 접미사
  '펀더멘털 반영': 'fundamental',
  '펀더멘털 약반영': 'weakFundamental',
  '센티멘트 약반영': 'weakSentiment',
  '센티멘트 지배': 'sentiment',
};

// 경기 국면명 → 내부 키
const PHASE_NAME_TO_KEY = {                       // API 한글 국면명 → i18n 키 접미사
  '회복': 'recovery',
  '확장': 'expansion',
  '둔화': 'slowdown',
  '침체': 'contraction',
};

// 등급명 → 내부 키
const GRADE_NAME_TO_KEY = {                       // API 한글 등급 → i18n 키 접미사
  '낮음': 'low',
  '보통': 'normal',
  '주의': 'caution',
  '경고': 'warning',
  '위험': 'danger',
};

// 방향명 → 내부 키
const DIR_NAME_TO_KEY = {                         // API 한글 방향 → i18n 키 접미사
  '상승 우세': 'bullish',
  '하락 우세': 'bearish',
  '방향 불명': 'unclear',
  '데이터 부족': 'noData',
};

// Fear & Greed 등급 → 내부 키
const FG_RATING_TO_KEY = {                        // API 한글 등급 → i18n 키 접미사
  '극도 탐욕': 'extremeGreed',
  '탐욕': 'greed',
  '중립': 'neutral',
  '공포': 'fear',
  '극도 공포': 'extremeFear',
};

// ── 번역 함수 ──
function t(key) {
  const lang = getLang();                          // 현재 언어 가져오기
  return I18N[lang][key] || I18N['ko'][key] || key; // 번역 → 한글 폴백 → 키 반환
}

// ── 등급 번역 (API 한글 등급 → 현재 언어) ──
function tGrade(koreanGrade) {
  const k = GRADE_NAME_TO_KEY[koreanGrade];       // 한글 → 키 변환
  return k ? t('grade.' + k) : koreanGrade;       // 키 → 현재 언어 번역
}

// ── NR 국면명 번역 ──
function tNrPhase(koreanName) {
  const k = NR_NAME_TO_KEY[koreanName];           // 한글 → 키 변환
  return k ? t('nr.phase.' + k) : koreanName;     // 키 → 현재 언어 번역
}

// ── NR 국면 설명 번역 ──
function tNrSub(koreanName) {
  const k = NR_NAME_TO_KEY[koreanName];           // 한글 → 키 변환
  return k ? t('nr.sub.' + k) : '';               // 키 → 현재 언어 번역
}

// ── NR 뱃지 텍스트 번역 ──
function tNrBadge(koreanName) {
  const badgeMap = {                              // 한글 국면 → 뱃지 키 매핑
    '펀더멘털 반영': 'stable',
    '펀더멘털 약반영': 'caution',
    '센티멘트 약반영': 'alert',
    '센티멘트 지배': 'danger',
  };
  const k = badgeMap[koreanName];                 // 한글 → 키 변환
  return k ? t('nr.badge.' + k) : '';             // 키 → 현재 언어 번역
}

// ── 경기 국면명 번역 ──
function tPhase(koreanName) {
  const k = PHASE_NAME_TO_KEY[koreanName];        // 한글 → 키 변환
  return k ? t('phase.' + k) : koreanName;        // 키 → 현재 언어 번역
}

// ── 경기 국면 설명 번역 ──
function tPhaseSub(koreanName) {
  const k = PHASE_NAME_TO_KEY[koreanName];        // 한글 → 키 변환
  return k ? t('phase.sub.' + k) : '';            // 키 → 현재 언어 번역
}

// ── 방향명 번역 ──
function tDirection(koreanDir) {
  const k = DIR_NAME_TO_KEY[koreanDir];           // 한글 → 키 변환
  return k ? t('dir.' + k) : koreanDir;           // 키 → 현재 언어 번역
}

// ── Fear & Greed 등급 번역 ──
function tFgRating(koreanRating) {
  const k = FG_RATING_TO_KEY[koreanRating];       // 한글 → 키 변환
  return k ? t('fg.' + k) : koreanRating;         // 키 → 현재 언어 번역
}

// ── 피처 라벨 번역 ──
function tFeatLabel(featureName) {
  return t('feat.' + featureName) || featureName; // 피처명으로 번역 조회
}

// ── 피처 설명 번역 ──
function tFeatDesc(featureName) {
  return t('featDesc.' + featureName) || '';       // 피처명으로 설명 조회
}

// ── 날짜 포맷 (언어별) ──
function formatDate(date) {
  if (getLang() === 'en') {                        // 영어: "Mar 16"
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${months[date.getMonth()]} ${date.getDate()}`;
  }
  return `${date.getMonth() + 1}월 ${date.getDate()}일`; // 한국어: "3월 16일"
}

// ── HTML data-i18n 속성 기반 정적 텍스트 번역 ──
function applyI18n() {
  // data-i18n 속성이 있는 요소의 textContent를 번역
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);          // 키로 번역 적용
  });
  // data-i18n-placeholder 속성이 있는 input의 placeholder를 번역
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder); // 플레이스홀더 번역
  });
  // html lang 속성 업데이트
  document.documentElement.lang = getLang();       // <html lang="ko|en">
}

// ── 언어 전환 버튼 텍스트 업데이트 ──
function updateLangButton() {
  const txt = t('lang.btn');
  ['btn-lang', 'setup-lang'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.textContent = txt;
  });
}

// ── 언어 전환 (메인 함수) ──
function switchLang() {
  const next = getLang() === 'ko' ? 'en' : 'ko';  // 현재와 반대 언어
  localStorage.setItem('lang', next);              // localStorage에 저장
  applyI18n();                                     // 정적 텍스트 번역
  updateLangButton();                              // 버튼 텍스트 갱신

  // 날짜 갱신
  const dateEl = document.getElementById('app-date'); // 날짜 요소
  if (dateEl) dateEl.textContent = formatDate(new Date()); // 날짜 포맷 적용

  // 동적 콘텐츠 재렌더링 (현재 활성 탭 기준)
  reRenderDynamic();                               // 동적 콘텐츠 다시 그리기
}

// ── 동적 콘텐츠 재렌더링 ──
function reRenderDynamic() {
  // 시장 탭 데이터 재로드
  if (typeof loadRegime === 'function') loadRegime();           // Noise vs Signal
  if (typeof loadMacro === 'function') loadMacro();             // VIX/VOL/PC
  if (typeof loadMarketOverview === 'function') loadMarketOverview(); // 시장 요약
  if (typeof loadNoiseChart === 'function') loadNoiseChart();   // 노이즈 차트
  if (typeof loadHoldingsSummary === 'function') loadHoldingsSummary(); // 보유종목

  // 신호 탭 (이미 로드된 경우만)
  if (window._signalLoaded) {
    if (typeof loadCrashSurge === 'function') loadCrashSurge(); // CS 카드
    if (typeof loadDirection === 'function') loadDirection();   // 방향성
    if (typeof loadCrashSurgeChart === 'function') loadCrashSurgeChart(); // CS 차트
  }

  // 거시경제 탭 (이미 로드된 경우만)
  if (window._sectorLoaded) {
    if (typeof loadSectorCycle === 'function') loadSectorCycle(); // 섹터 경기국면
  }

  // 차트 탭 (이미 로드된 경우만) - 요약 텍스트 재렌더
  if (window._chartLoaded && typeof loadCandleChart === 'function') {
    loadCandleChart();
  }

  // 보유종목 설정 화면 칩 재렌더 (열려있을 때)
  if (typeof window._rerenderSetupChips === 'function') window._rerenderSetupChips();
}
