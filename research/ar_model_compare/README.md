# AR 입술 비교 실험 (부분 구현)

AR_SPEC 1-4(얼굴 영상 기기 밖 전송 금지) 예외 실험, 앱에는 반영하지 않음. 이 도구는 기존 로컬 사진을 사용하고 결과 이미지는 `research/data/`에만 쓴다. 외부 API로 이미지를 전송하지 않는다.

실험 A는 부위 검출, B는 렌더링을 따로 본다. 현재 구현은 전체 요청을 충족하지 않는다. LaPa 정답 및 팀 데이터가 없는 환경에서 우선 공개 얼굴 5장으로 A의 CPU 추론 스모크 테스트와 B의 정성·측정 도구를 실행한다. LaPa 층화·합성 어둠·전체 모델 정답 지표·SegFormer·FaRL·SAM 2 추론·비디오 안정성·GPU/HTTP 측정은 **미구현/미실행**이다. 기존 BiSeNet ONNX는 공개 모델의 SHA-256과 일치하고 전처리 및 클래스 정의도 확인했다. 정답 마스크가 없어 정확도는 측정하지 않았다.

## 실행

PowerShell에서 저장소 루트 기준:

```powershell
research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/build_set.py
research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/run_a.py
research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/hybrid_crop.py
research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/wasm_crop.py
research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/run_b.py
research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/analyze_b.py
research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/check_team.py
```

`build_set.py`는 존재하는 5장의 720×960 얼굴 사진을 고정 순서로 복사하고 manifest 해시를 출력한다. 톤·각도·입 상태와 출처별 상세 라이선스는 임의로 지정하지 않는다. 현재 `condition`, `yaw_bin`, `mouth`, `tone_bin`은 unknown이고 실제 촬영 각도·피부톤 분포를 대표하지 않는다. 정답 마스크도 없다. 파일명과 저장 경로를 해시하므로 입력 파일의 바이트가 바뀌는 경우는 별도 확인이 필요하다. 사진 출처는 로컬 `research/data/lip_texture/src/SOURCES.tsv`에 일부 기록돼 있다. 얼굴 사진은 공개했다고 가정하지 말고 각 사진의 재사용 조건을 확인한다.

`run_b.py`는 앱 페이지를 매번 다시 빌드하고 기존 `lip_texture/render.py`를 사용한다. 같은 정지 이미지를 가짜 카메라로 사용하고 조명·분할 갱신을 고정하지만, 얼굴 추적은 계속되어 미세하게 움직일 수 있다. 결과의 모든 이미지와 시트는 로컬 전용이다. 현재 앱 기본값인 `lightMatch`는 이미 켜져 있어 별도 후보로 취급하지 않았다. 후보는 이전 기록에서 꺼진 `lipDetail`, `wideDetail`, `glossAniso` 조합이다.

`hybrid_crop.py`는 입술 바깥 랜드마크의 사각형 중심에 입 너비 1.6배 정사각형을 만들고, 128/192/256으로 표본화해 BiSeNet에 넣는다. 이 ONNX 모델은 입력이 512×512 **고정**이라 세 크롭을 각각 512로 다시 확대한다. 결과 분류 마스크는 원 영상 좌표로 되돌린다. LaPa 행에 동일 크기의 `gt_path`가 있으면 7·9를 입술로 비교한다(현재 manifest에 LaPa 행 없음). 다른 최상위 모델의 크롭 실행은 미구현이다. `wasm_crop.py`는 동일한 전처리 텐서를 데스크톱 Chrome의 ONNX Runtime Web WASM 단일 스레드로 추론한다. 수치는 **추론만**이며 감지·전처리·마스크 복원은 빠져 있다. 브라우저 요청은 로컬 파일로 가로채고 외부 요청은 차단한다. 폰 WebView 성능은 별도 실측해야 한다.

`sam2_prompts.py`는 앱 입술 윤곽에서 박스와 양·음성 점을 만든다. SAM 2 모델 로딩·이미지 추론·영상 마스크 전파는 아직 구현하지 않았다. 라이선스와 후보별 실행 상태는 보고서에 정리한다.

`analyze_b.py`는 앱 렌더의 변화량(RGB 절대차 합 >24)과 기존 랜드마크 입술 다각형의 교집합을 입 너비의 3%로 침식한다. **정답 마스크가 없으므로 모델과 렌더러의 차이가 완벽히 분리된 GT core가 아니다.** 세부 측정 범위와 누락 지표는 보고서를 따른다. 맨입술 대비 위치는 실제 립스틱 재현 정확도가 아니다. 비교값이 같은 경우 점수는 계산하지 않는다.

## 사람 평가

`rating/index.html`을 브라우저에서 파일로 열고 `research/data/ar_model_compare/rating/` 폴더를 선택한다. A/B/모르겠음을 선택하고 CSV를 내려받는다. 익명 무작위 세션 ID만 기록하며, 같은 사람이 브라우저 세션을 새로 열면 별도 평가자로 집계될 수 있다. 결과를 모아 `python research/ar_model_compare/analyze_rating.py 평가1.csv 평가2.csv`로 집계한다. 사람 평가 전에는 승률을 보고하지 않는다. Wilson 구간은 같은 사람의 반복 투표 간 상관을 고려하지 않는다.

## 팀 데이터 규칙 (수집 후 별도 구현 필요)

`research/data/ar_model_compare/team/<날짜>/`에 동의한 사진과 영상만 둔다. 사진 파일명은 `{사람}_{normal|dark}_{00|30|45}_{bare|applied}_{matte|satin|glossy|none}.jpg`, 맨입술은 `none`을 쓴다. 영상은 `{사람}_{normal|dark}_video.mp4`, 정지 10초 → 좌우 회전 5초 → 손으로 입 반 가리기 3초다. `meta.csv` 열은 `filename,device,time,product,hex,notes`이고 사진·영상마다 한 행을 쓴다. `check_team.py`는 이름·짝·메타 행을 점검한다. 해당 도구는 동의 및 메타 내용의 진위를 검증하지 않으며, 현재 팀 데이터는 manifest에 자동 편입되지 않는다.
