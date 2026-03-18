# ============================================================
# ML_06_Feature2SectorCycle — HMM 경기국면 + 섹터 성과 분석 빈칸 연습
# 원본: processor/feature2_sector_cycle.py
# 총 빈칸: 45개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

import warnings
import numpy as ___                                      # Q1: numpy의 관용적 별칭
import pandas as ___                                     # Q2: pandas의 관용적 별칭
from hmmlearn.hmm import ___                             # Q3: 가우시안 분포 기반 HMM 클래스
from sklearn.preprocessing import ___                    # Q4: 평균 0, 표준편차 1로 정규화하는 스케일러

warnings.filterwarnings('ignore')

# Q5~Q8: 4개 경기국면 이름 매핑
PHASE_NAMES  = {0: '___', 1: '___', 2: '___', 3: '___'}  # Q5~Q8: 경기순환 4단계 (바닥→상승→하강→저점 순서)

# Q9: 10개 매크로 피처 컬럼
FEATURE_COLS = [
    '___', '___', 'anfci', 'icsa_yoy',                   # Q9~Q10: 제조업 경기지수, 장단기 금리차 피처명
    'permit_yoy', '___', 'capex_yoy',                    # Q11: 실질 소매판매 전년비 피처명
    '___', '___', '___',                                 # Q12~Q14: 실질소득 전년비, PMI 3개월 변화, 설비투자 전년비 3개월 변화 피처명
]

# HMM 상태 정렬 후 국면 매핑: rank 0→침체, 1→둔화, 2→회복, 3→확장
RANK_TO_PHASE = [___, ___, ___, ___]                     # Q15~Q18: rank 0→침체, 1→둔화, 2→회복, 3→확장에 대응하는 국면 번호


def _map_states_to_phases(model: GaussianHMM) -> dict[int, int]:
    """HMM hidden states → 경기국면 매핑 (PMI + 모멘텀 복합점수)."""
    scores = model.___[:, 0] + 0.5 * model.means_[:, ___]  # Q19~Q20: HMM 상태별 평균 속성, PMI 모멘텀(pmi_chg3m) 피처의 인덱스
    sorted_states = np.argsort(___)                      # Q21: 정렬 대상인 복합 점수 변수
    return {int(sid): RANK_TO_PHASE[rank] for rank, sid in ___(sorted_states)}  # Q22: 인덱스와 값을 함께 순회하는 내장 함수


def run_sector_cycle(macro, sector_ret, holding_ret) -> dict:
    """매크로 + 섹터수익률로 HMM 학습 → 현재 국면 예측 + 성과 반환."""
    from collector.sector_etf import SECTOR_ETFS, ___    # Q23: 전체 보유 종목 리스트 상수

    # 데이터 병합
    df = macro.___(sector_ret, how='left').join(holding_ret, how='left').___()  # Q24~Q25: 데이터프레임 결합 메서드, 결측치 행 제거 메서드

    # 피처 스케일링
    X = df[___].values                                   # Q26: 10개 매크로 피처 컬럼명 리스트 상수
    scaler = ___()                                       # Q27: 표준 정규화 스케일러 인스턴스 생성
    X_scaled = scaler.___(X)                             # Q28: 학습과 변환을 한번에 수행하는 메서드

    # GaussianHMM 학습
    for cov_type in ('full', '___'):                      # Q29: 대각 공분산 타입 문자열
        try:
            model = GaussianHMM(
                n_components=___,                        # Q30: 경기국면 수 (정수)
                covariance_type=cov_type,
                n_iter=200,
                random_state=___,                        # Q31: 재현성을 위한 랜덤 시드 값
            )
            model.fit(X_scaled)
            break
        except (ValueError, np.linalg.LinAlgError):
            if cov_type == 'diag':
                raise

    # 상태 예측 및 국면 매핑
    states = model.___(X_scaled)                         # Q32: 가장 확률 높은 상태를 반환하는 메서드
    state_to_phase = ___(model)                          # Q33: HMM 상태를 경기국면에 매핑하는 함수
    df = df.copy()
    df['phase'] = [state_to_phase[s] for s in ___]       # Q34: 예측된 상태 배열 변수

    # 최신 시점 확률
    all_proba = model.___(X_scaled)                      # Q35: 각 상태의 사후 확률을 반환하는 메서드
    latest_proba_raw = all_proba[___]                     # Q36: 가장 마지막 행의 인덱스
    proba_by_phase = {state_to_phase[i]: float(p) for i, p in enumerate(latest_proba_raw)}
    pred_phase = max(proba_by_phase, key=proba_by_phase.___)  # Q37: 딕셔너리에서 값을 가져오는 메서드

    # 국면별 섹터 평균 월수익률 (%)
    sector_cols  = [c for c in SECTOR_ETFS if c in df.columns]
    phase_sector_perf = {}
    for ph in range(___):                                # Q38: 전체 국면 수
        mask = df['phase'] == ph
        if mask.___() == 0:                              # Q39: True 개수를 세는 메서드
            continue
        phase_sector_perf[PHASE_NAMES[ph]] = {
            col: round(float(df.loc[mask, col].___() * 100), 2)  # Q40: 평균을 구하는 메서드
            for col in sector_cols
        }

    # 현재 국면 top3 섹터
    current_perf = phase_sector_perf.get(PHASE_NAMES[pred_phase], {})
    top3 = sorted(current_perf, key=current_perf.get, reverse=___)[:3]  # Q41: 내림차순 정렬 여부 (불리언)

    # 매크로 스냅샷
    latest_vals = df[FEATURE_COLS].iloc[___]              # Q42: 가장 마지막 행의 인덱스
    macro_snapshot = {col: round(float(latest_vals[col]), 4) for col in FEATURE_COLS}

    return {
        'date':               str(df.index[-1].date()),
        'current_phase':      pred_phase,
        'phase_name':         ___[pred_phase],            # Q43
        'probabilities':      {PHASE_NAMES[ph]: round(proba_by_phase.get(ph, 0.0), 4) for ph in range(4)},
        'phase_sector_perf':  phase_sector_perf,
        'top3_sectors':       ___,                        # Q44
        'macro_snapshot':     macro_snapshot,
    }


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | as ___                        | np                     |
# | Q2 | as ___                        | pd                     |
# | Q3 | import ___                    | GaussianHMM            |
# | Q4 | import ___                    | StandardScaler         |
# | Q5 | 0: '___'                      | 회복                   |
# | Q6 | 1: '___'                      | 확장                   |
# | Q7 | 2: '___'                      | 둔화                   |
# | Q8 | 3: '___'                      | 침체                   |
# | Q9 | '___'                         | pmi                    |
# | Q10| '___'                         | yield_spread           |
# | Q11| '___'                         | real_retail_yoy        |
# | Q12| '___'                         | real_income_yoy        |
# | Q13| '___'                         | pmi_chg3m              |
# | Q14| '___'                         | capex_yoy_chg3m        |
# | Q15| ___                           | 3                      |
# | Q16| ___                           | 2                      |
# | Q17| ___                           | 0                      |
# | Q18| ___                           | 1                      |
# | Q19| model.___                     | means_                 |
# | Q20| means_[:, ___]                | 8                      |
# | Q21| argsort(___)                  | scores                 |
# | Q22| ___(sorted_states)            | enumerate              |
# | Q23| import ___                    | ALL_HOLDINGS           |
# | Q24| macro.___                     | join                   |
# | Q25| .___()                        | dropna                 |
# | Q26| df[___]                       | FEATURE_COLS           |
# | Q27| ___()                         | StandardScaler         |
# | Q28| scaler.___                    | fit_transform          |
# | Q29| '___'                         | diag                   |
# | Q30| n_components=___              | 4                      |
# | Q31| random_state=___              | 42                     |
# | Q32| model.___                     | predict                |
# | Q33| ___(model)                    | _map_states_to_phases  |
# | Q34| for s in ___                  | states                 |
# | Q35| model.___                     | predict_proba          |
# | Q36| all_proba[___]                | -1                     |
# | Q37| .___                          | get                    |
# | Q38| range(___)                    | 4                      |
# | Q39| mask.___()                    | sum                    |
# | Q40| .___()                        | mean                   |
# | Q41| reverse=___                   | True                   |
# | Q42| .iloc[___]                    | -1                     |
# | Q43| ___[pred_phase]               | PHASE_NAMES            |
# | Q44| ___                           | top3                   |
# ============================================================
