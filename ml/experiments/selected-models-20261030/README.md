# 2026-10-30 선정 모델 학습 코드 보존본

모공, 주름, 색소침착, ROI 피부타입 모델에 실제 사용한 학습·데이터 준비
스크립트를 실행 폴더에서 복사한 기록이다. 원본 데이터, 얼굴 이미지, 인물별
분할 목록, ROI 캐시, 모델 가중치는 포함하지 않는다.

| 폴더 | 역할 |
|---|---|
| `pore-backbone-original-20261028` | 모공 백본 비교 및 선정 모델 학습 |
| `pore-unsharp75-contrast40-20261028` | 기존 분할을 사용하는 질감 전처리 실험 준비 |
| `mobilenet-skin-bundle-20261030` | 주름·색소침착 ROI 준비 및 학습 |
| `skin-type-mobilenet-20261030` | 피부타입 인벤토리 및 학습 코드 생성 |
| `skin-type-roi-mobilenet-20261030` | ROI 피부타입 분할 준비 및 학습 |

## 실행과 재현의 제한

이 파일들은 **원본 실행 코드를 보존한 것**이며 이 폴더에서 바로 실행할 수
있는 완결된 재현 패키지는 아니다. 코드가 `ml/runs/`의 기존 결과물 경로,
로컬 데이터 경로와 GPU UUID를 참조한다. 실행하려면 원본 데이터의 사용 권한,
기존 인물별 분할 manifest 및 ROI pixel cache가 필요하다. 특히 전처리 준비는
`runs/batch-diversity-ablation-20261027/cv-head1-6fold/fold-1/manifest/manifest.json`
을 입력으로 요구하며, 피부타입 준비도 이 분할과 원본 메타데이터를 사용한다.
해당 자료는 이 저장소에 포함되지 않으므로 분할을 임의로 다시 만들면 기존
수치와의 정확한 재현을 보장할 수 없다.

실행 환경은 `ml/pyproject.toml`과 `ml/uv.lock` 및 `ml/src/skin_analysis/`에
의존한다. 실행 시 해당 코드의 경로·GPU 설정을 환경에 맞춰 조정하고 원본
manifest의 경로 및 fingerprint 검증을 유지해야 한다. 코드와 보고서만으로
학습 완료 체크포인트나 동일한 성능이 생성된다고 보장하지 않는다.

실험 설정과 결과는 [모델 선정 근거 보고서](../../../reports/skin-analysis/model-selection-20261030/model-selection-evidence-20261030.md)를 참고한다.
