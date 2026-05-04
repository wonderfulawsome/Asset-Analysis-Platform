### HMM 경기국면 분류 + 국면별 섹터 성과 분석 (US/KR region 공용)

import warnings
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

PHASE_NAMES  = {0: '회복', 1: '확장', 2: '둔화', 3: '침체'}
PHASE_EMOJIS = {0: '🌱', 1: '☀️', 2: '🍂', 3: '❄️'}

# ── 거시 피처 정의 (region 별) ────────────────────────────────────────
FEATURE_COLS_US = [
    'pmi', 'yield_spread', 'anfci', 'icsa_yoy',
    'permit_yoy', 'real_retail_yoy', 'capex_yoy',
    'real_income_yoy', 'pmi_chg3m', 'capex_yoy_chg3m',
]
# KR 12종 + derived 2종 (총 14컬럼) — 4-state HMM 학습용
FEATURE_COLS_KR = [
    'kr_indpro_yoy', 'kr_yield_spread', 'kr_credit_spread',
    'kr_unemp_yoy', 'kr_unemp_rate',
    'kr_permit_yoy', 'kr_retail_yoy', 'kr_capex_yoy', 'kr_income_yoy',
    'kr_cpi_yoy', 'kr_gdp_yoy', 'kr_m2_yoy',
    'kr_indpro_chg3m', 'kr_capex_yoy_chg3m',
]

# state→phase 점수 산출용 컬럼 — region 별 "PMI 등 수준 지표" + "모멘텀 지표"
# (모멘텀이 클수록 회복/확장 방향)
PHASE_SCORE_COLS = {
    'us': ('pmi', 'pmi_chg3m'),
    'kr': ('kr_indpro_yoy', 'kr_indpro_chg3m'),
}

# HMM 상태 정렬 후 국면 매핑: rank 0(최저)→침체, 1→둔화, 2→회복, 3→확장
RANK_TO_PHASE = [3, 2, 0, 1]


def _map_states_to_phases(model: GaussianHMM, feature_cols: list[str],
                          region: str = 'us') -> dict[int, int]:
    """HMM hidden states → 경기국면 매핑.

    score = mean(level_col) + 0.5 * mean(momentum_col), level ↑ + momentum ↑ → 확장.
    region 별 level/momentum 컬럼 인덱스를 동적 조회 — KR 일부 ECOS/KOSIS 시리즈 부재 시
    fallback 으로 가용 컬럼 첫 번째 사용 (스코어는 level only).
    """
    level_col, mom_col = PHASE_SCORE_COLS.get(region, PHASE_SCORE_COLS['us'])
    i_level = feature_cols.index(level_col) if level_col in feature_cols else 0
    if mom_col in feature_cols:
        i_mom = feature_cols.index(mom_col)
        scores = model.means_[:, i_level] + 0.5 * model.means_[:, i_mom]
    else:
        # momentum 컬럼 없음 → level only 점수 (fallback)
        print(f'  [SectorCycle warn] momentum col {mom_col} 부재 — level only 점수 사용')
        scores = model.means_[:, i_level]
    sorted_states = np.argsort(scores)
    return {int(sid): RANK_TO_PHASE[rank] for rank, sid in enumerate(sorted_states)}


def run_sector_cycle(macro: pd.DataFrame, sector_ret: pd.DataFrame,
                     holding_ret: pd.DataFrame, region: str = 'us') -> dict:
    """매크로 + 섹터수익률로 HMM 학습 → 현재 국면 예측 + 국면별 섹터 성과.

    Args:
        macro: MS 인덱스 매크로 wide DataFrame (FEATURE_COLS 모두 보유)
        sector_ret: MS 인덱스 sector ETF 월별 수익률 (NaN 허용 — 일부 ETF 상장 후 짧으면 OK)
        holding_ret: MS 인덱스 holding ETF 월별 수익률 (NaN 허용)
        region: 'us' | 'kr'

    Returns:
        {date, current_phase, phase_name, phase_emoji, probabilities,
         phase_sector_perf, phase_holding_perf, top3_sectors,
         macro_snapshot, train_acc, test_acc}
    """
    # region 별 ticker / feature 분기
    if region == 'kr':
        from collector.sector_etf_kr import SECTOR_ETF_KR, ALL_HOLDINGS_KR
        SECTORS = list(SECTOR_ETF_KR.keys())
        HOLDINGS = list(ALL_HOLDINGS_KR)
        feature_cols = FEATURE_COLS_KR
    else:
        from collector.sector_etf import SECTOR_ETFS, ALL_HOLDINGS
        SECTORS = list(SECTOR_ETFS)
        HOLDINGS = list(ALL_HOLDINGS)
        feature_cols = FEATURE_COLS_US

    # ── ① 매크로는 "데이터가 한 행이라도 있는 컬럼" 만 사용 후 dropna ──
    # KR 환경에서 ECOS/KOSIS 일부 코드 무효일 때도 graceful 동작 (있는 컬럼만으로 학습).
    available_features = [c for c in feature_cols if c in macro.columns]
    if len(available_features) < len(feature_cols):
        missing = set(feature_cols) - set(available_features)
        print(f'  [SectorCycle warn] 매크로 컬럼 부재 {len(missing)}: {sorted(missing)}')

    # 비-NaN 행이 한 개라도 있는 컬럼만 골라냄 — 통째 빈 컬럼은 학습에 의미 무
    non_empty = [c for c in available_features if macro[c].notna().any()]
    if len(non_empty) < 3:
        raise ValueError(
            f'학습 가능 매크로 컬럼 부족 ({len(non_empty)} < 3) — '
            f'ECOS/KOSIS 통계표 코드 검증 필요. 현재 가용: {non_empty}'
        )
    if len(non_empty) < len(available_features):
        empty_cols = sorted(set(available_features) - set(non_empty))
        print(f'  [SectorCycle warn] 데이터 0행 컬럼 {len(empty_cols)}/{len(available_features)} 제외: {empty_cols}')

    df_macro = macro[non_empty].dropna()
    if df_macro.empty:
        raise ValueError(
            f'매크로 dropna 후 0행 — 가용 {len(non_empty)}컬럼 시기 정렬 실패. '
            f'각 컬럼별 데이터 시점이 너무 달라 공통 구간 없음.'
        )
    # 다음 단계는 non_empty 사용 — feature_cols 변수 갱신
    feature_cols_used = non_empty

    # ── ② sector_ret / holding_ret 은 available cols 만 left join (NaN 허용) ──
    available_sectors = [c for c in SECTORS if c in sector_ret.columns]
    available_holdings = [c for c in HOLDINGS if c in holding_ret.columns]
    df = df_macro.join(sector_ret[available_sectors], how='left') if available_sectors else df_macro.copy()
    if available_holdings:
        df = df.join(holding_ret[available_holdings], how='left')

    # ── ③ HMM 학습은 가용 매크로 컬럼만 dropna (sector NaN 무관) ──
    X_df = df[feature_cols_used].dropna()
    if len(X_df) < 24:
        raise ValueError(f'HMM 학습 데이터 부족 ({len(X_df)} < 24개월)')

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_df.values)

    # GaussianHMM 학습 (full → diag 폴백)
    for cov_type in ('full', 'diag'):
        try:
            model = GaussianHMM(
                n_components=4,
                covariance_type=cov_type,
                n_iter=200,
                random_state=42,
            )
            model.fit(X_scaled)
            break
        except (ValueError, np.linalg.LinAlgError):
            if cov_type == 'diag':
                raise

    # 상태 예측 + 국면 매핑 (X_df 행 기준)
    states = model.predict(X_scaled)
    state_to_phase = _map_states_to_phases(model, feature_cols_used, region=region)
    df_with_phase = df.loc[X_df.index].copy()
    df_with_phase['phase'] = [state_to_phase[s] for s in states]

    # 최신 시점 확률
    all_proba = model.predict_proba(X_scaled)
    latest_proba_raw = all_proba[-1]
    proba_by_phase = {state_to_phase[i]: float(p) for i, p in enumerate(latest_proba_raw)}
    pred_phase = max(proba_by_phase, key=proba_by_phase.get)
    proba_dict = {PHASE_NAMES[ph]: round(proba_by_phase.get(ph, 0.0), 4) for ph in range(4)}

    # 평가 메트릭 (per-sample log-likelihood)
    avg_ll = float(model.score(X_scaled)) / len(X_scaled)
    train_acc = round(avg_ll, 4)
    test_acc = round(avg_ll, 4)

    # ── ④ 국면별 섹터/보유 평균 월수익률 (%) — 컬럼별 NaN skip mean ──
    phase_sector_perf: dict = {}
    phase_holding_perf: dict = {}
    for ph in range(4):
        mask = df_with_phase['phase'] == ph
        if mask.sum() == 0:
            continue
        # 섹터: 컬럼별 NaN skip + 모두 NaN 인 컬럼은 결과에서 제외
        phase_sector_perf[PHASE_NAMES[ph]] = {}
        for col in available_sectors:
            if df_with_phase.loc[mask, col].notna().any():
                m = df_with_phase.loc[mask, col].mean(skipna=True)
                if pd.notna(m):
                    phase_sector_perf[PHASE_NAMES[ph]][col] = round(float(m * 100), 2)
        # 보유 ETF: 같은 처리
        phase_holding_perf[PHASE_NAMES[ph]] = {}
        for col in available_holdings:
            if df_with_phase.loc[mask, col].notna().any():
                m = df_with_phase.loc[mask, col].mean(skipna=True)
                if pd.notna(m):
                    phase_holding_perf[PHASE_NAMES[ph]][col] = round(float(m * 100), 2)

    # 현재 국면 top3 섹터
    current_perf = phase_sector_perf.get(PHASE_NAMES[pred_phase], {})
    top3 = sorted(current_perf, key=current_perf.get, reverse=True)[:3]

    # 매크로 스냅샷 (최신 행)
    latest_vals = X_df.iloc[-1]
    macro_snapshot = {col: round(float(latest_vals[col]), 4) for col in feature_cols_used
                      if pd.notna(latest_vals[col])}

    today_date = str(X_df.index[-1].date())

    print(f'[SectorCycle/{region}] {today_date} → {PHASE_EMOJIS[pred_phase]} {PHASE_NAMES[pred_phase]} '
          f'({proba_dict[PHASE_NAMES[pred_phase]]*100:.1f}%) | LL/sample {avg_ll:.2f}')

    return {
        'date':               today_date,
        'current_phase':      pred_phase,
        'phase_name':         PHASE_NAMES[pred_phase],
        'phase_emoji':        PHASE_EMOJIS[pred_phase],
        'probabilities':      proba_dict,
        'phase_sector_perf':  phase_sector_perf,
        'phase_holding_perf': phase_holding_perf,
        'top3_sectors':       top3,
        'macro_snapshot':     macro_snapshot,
        'train_acc':          train_acc,
        'test_acc':           test_acc,
    }
