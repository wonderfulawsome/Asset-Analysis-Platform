"""noise_regime.noise_score 부호 일괄 반전 (1회성 마이그레이션)

배경: 2026-04-29 부호 컨벤션을 뒤집었다 — 양수 = 이성, 음수 = 감정.
기존 적재분(음수=이성, 양수=감정)을 새 컨벤션과 맞추기 위해 한 번만 실행.

사용:
    python -m scripts.flip_noise_score_sign        # 실제 적용
    python -m scripts.flip_noise_score_sign --dry  # 변경 미리보기만

도 같은 컨셉의 contribution 필드(feature_contributions JSONB) 도 부호 반전.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.supabase_client import get_client


def flip_all(dry: bool = False) -> int:
    client = get_client()
    rows = client.table('noise_regime').select('*').execute().data
    print(f"[Flip] 대상 행 {len(rows)}건")

    updated = 0
    for r in rows:
        ns = r.get('noise_score')
        if ns is None:
            continue
        new_ns = -float(ns)

        # feature_contributions JSONB — 'contribution' 필드 부호 반전
        fc = r.get('feature_contributions')
        if isinstance(fc, str):
            try:
                fc = json.loads(fc)
            except Exception:
                fc = None
        new_fc = None
        if isinstance(fc, list):
            new_fc = [{**c, 'contribution': -float(c['contribution'])}
                      if c.get('contribution') is not None else c
                      for c in fc]

        # 부호 변경 후 일치/불일치 라벨 재산정
        if new_ns > 0:
            new_regime_id, new_regime_name = 0, '펀더멘털-주가 일치'
        else:
            new_regime_id, new_regime_name = 2, '펀더멘털-주가 불일치'

        update_payload = {
            'noise_score': round(new_ns, 4),
            'regime_id': new_regime_id,
            'regime_name': new_regime_name,
        }
        if new_fc is not None:
            update_payload['feature_contributions'] = json.dumps(new_fc, ensure_ascii=False)

        if dry:
            print(f"  [DRY] {r['date']}: {ns} → {new_ns:.4f}, "
                  f"{r.get('regime_name')} → {new_regime_name}")
            continue

        client.table('noise_regime').update(update_payload).eq('date', r['date']).execute()
        updated += 1
        if updated % 20 == 0:
            print(f"  [Flip] {updated}/{len(rows)} 진행")

    print(f"[Flip] {'시뮬레이션' if dry else '적용'} 완료: {updated}건")
    return updated


if __name__ == '__main__':
    dry = '--dry' in sys.argv
    flip_all(dry=dry)
