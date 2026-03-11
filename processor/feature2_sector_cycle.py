### HMM 경기국면 분류 + 국면별 섹터 성과 분석

import warnings
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

PHASE_NAMES  = {0: '회복', 1: '확장', 2: '둔화', 3: '침체'}
PHASE_EMOJIS = {0: '🌱', 1: '☀️', 2: '🍂', 3: '❄️'}

FEATURE_COLS = [
    'pmi', 'yield_spread', 'anfci', 'icsa_yoy',
    'permit_yoy', 'real_retail_yoy', 'capex_yoy',
    'real_income_yoy', 'pmi_chg3m', 'capex_yoy_chg3m',
]

# HMM 상태 정렬 후 국면 매핑: rank 0(최저)→침체, 1→둔화, 2→회복, 3→확장
RANK_TO_PHASE = [3, 2, 0, 1]


def _map_states_to_phases(model: GaussianHMM) -> dict[int, int]:
    """HMM hidden states → 경기국면 매핑 (PMI 수준 + 모멘텀 복합점수 기준)."""
    scores = model.means_[:, 0] + 0.5 * model.means_[:, 8]  # pmi + 0.5*pmi_chg3m
    sorted_states = np.argsort(scores)
    return {int(sid): RANK_TO_PHASE[rank] for rank, sid in enumerate(sorted_states)}


def run_sector_cycle(macro: pd.DataFrame, sector_ret: pd.DataFrame,
                     holding_ret: pd.DataFrame) -> dict:
    """매크로 + 섹터수익률로 HMM 학습 → 현재 국면 예측 + 국면별 섹터 성과 반환.

    Returns:
        {
            'date': '2025-12-01',
            'current_phase': 2,
            'phase_name': '둔화',
            'phase_emoji': '🍂',
            'probabilities': {'회복': 0.003, '확장': 0.005, '둔화': 0.986, '침체': 0.007},
            'phase_sector_perf': {'회복': {'XLF': 0.04, ...}, ...},
            'phase_holding_perf': {'회복': {'QQQ': 1.23, ...}, ...},
            'top3_sectors': ['XLE', 'XLF', 'XLI'],
            'macro_snapshot': {'pmi': 49.4, ...},
            'train_acc': -1.23,
            'test_acc': -1.23,
        }
    """
    from collector.sector_etf import SECTOR_ETFS, ALL_HOLDINGS

    # 데이터 병합
    df = macro.join(sector_ret, how='left').join(holding_ret, how='left').dropna()

    # 피처 스케일링
    X = df[FEATURE_COLS].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

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

    # 상태 예측 및 국면 매핑
    states = model.predict(X_scaled)
    state_to_phase = _map_states_to_phases(model)
    df = df.copy()
    df['phase'] = [state_to_phase[s] for s in states]

    # 최신 시점 확률
    all_proba = model.predict_proba(X_scaled)
    latest_proba_raw = all_proba[-1]
    proba_by_phase = {state_to_phase[i]: float(p) for i, p in enumerate(latest_proba_raw)}
    pred_phase = max(proba_by_phase, key=proba_by_phase.get)
    proba_dict = {PHASE_NAMES[ph]: round(proba_by_phase.get(ph, 0.0), 4) for ph in range(4)}

    # 평가 메트릭 (per-sample log-likelihood)
    avg_ll = float(model.score(X_scaled)) / len(X_scaled)
    train_acc = round(avg_ll, 4)
    test_acc  = round(avg_ll, 4)

    # 국면별 섹터/보유종목 평균 월수익률 (%)
    sector_cols  = [c for c in SECTOR_ETFS if c in df.columns]
    holding_cols = [c for c in ALL_HOLDINGS if c in df.columns]

    phase_sector_perf = {}
    phase_holding_perf = {}
    for ph in range(4):
        mask = df['phase'] == ph
        if mask.sum() == 0:
            continue
        phase_sector_perf[PHASE_NAMES[ph]] = {
            col: round(float(df.loc[mask, col].mean() * 100), 2)
            for col in sector_cols
        }
        phase_holding_perf[PHASE_NAMES[ph]] = {
            col: round(float(df.loc[mask, col].mean() * 100), 2)
            for col in holding_cols
        }

    # 현재 국면 top3 섹터
    current_perf = phase_sector_perf.get(PHASE_NAMES[pred_phase], {})
    top3 = sorted(current_perf, key=current_perf.get, reverse=True)[:3]

    # 매크로 스냅샷
    latest_vals = df[FEATURE_COLS].iloc[-1]
    macro_snapshot = {col: round(float(latest_vals[col]), 4) for col in FEATURE_COLS}

    today_date = str(df.index[-1].date())

    print(f'[SectorCycle] {today_date} → {PHASE_EMOJIS[pred_phase]} {PHASE_NAMES[pred_phase]} '
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
