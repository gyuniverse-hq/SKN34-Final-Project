# 환경 점검 (2026-11-20)

조사 범위: 로컬 PC. 가중치는 받지 않음. 모델을 돌리지 않음.

| 항목 | 결과 | 상태 |
|---|---|---|
| NVIDIA 드라이버 / `nvidia-smi` | 명령을 찾을 수 없음 | 로컬 GPU 추론 불가 |
| PyTorch CUDA | `torch.cuda.is_available() == False` | 로컬 GPU 추론 불가 |
| FLUX.1-Kontext-dev 라이선스 | Hugging Face에 로그인·동의 여부를 이 PC에서 확인하지 않음. 가중치 미다운로드 | 확인 불가 |
| MagicMakeup 체크포인트 `Anyou/MagicMakeup` | 미다운로드 | 실행 미검증 |
| Stable-Makeup Google Drive 가중치 | 미다운로드 | 실행 미검증 |
| ART LoRA `csbowei/ART` | 미다운로드 | 실행 미검증 |
| `research/data/hw01_raw` | 경로 없음 | 숙제 01 전후 사진 없음 |
| 립 제품 1색 통제 전후 | 저장소·`research/data`에서 동일 인물·동일 조명 제품 전후를 확정하지 못함 | 제품명 미확정 |
| Kaggle Makeup Detection (26쌍, CC BY-NC-ND) | `docs/AR_PROGRESS.md` 10-22: `research/data/reference/makeup_detection/` 예정. 조명 비통제, 트랙 B·제품 ΔE 정답 아님 | 참고만 |
| 사용자 맨얼굴 셀카 (멘토링 첨부) | 바른 뒤 사진 없음. 생성 모델 입력·보고서 삽입에 쓰지 않음 | 정답 아님 |

결론: 11월 21일 전까지 이 PC에서 Stable-Makeup·MagicMakeup 추론을 돌릴 수 없다. 비교 PDF ②의 생성 결과·ΔE는 전부 **미측정**이다.
