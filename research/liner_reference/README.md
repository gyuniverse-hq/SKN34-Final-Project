# 속눈썹 윙 평가 (research only)

라이브 셰이더는 `EYELINER_PRESET.lineWing`을 그대로 둔다. 이 폴더는 정면 사진에 지금 눈꺼풀 점 획을 그려 손 라벨·BiSeNet 눈 영역과 비교한다. `app/`과 `faceTrackerHtml.ts`를 import하지 않는다.

## 손 라벨

1. 동의한 정면 사진 20~50장을 `research/data/liner/images/`에 둔다 (git-ignore).
2. 같은 이름 PNG를 `research/data/liner/gt/`에 둔다. 흰 픽셀 = 윗선·언더라인 정답.
3. 실행:

```
python research/liner_reference/eval_liner.py --limit 50
```

표: `research/data/liner/eval/liner.csv` — `hand_iou`, `hand_spill`(획이 정답 밖), LaPa가 있으면 `lapa_spill`·`rim_*`, BiSeNet이 있으면 `bisenet_inside`.

2026-10-28 실행(정면 17장, `--limit 50`): 손 라벨 없음. LaPa 눈 테두리 IoU 0.068, 밖 spill 0.73. BiSeNet 눈 안 비율 0.42. 눈 클래스 IoU가 높아도 가는 선이라는 뜻은 아니다.

## BiSeNet

가중치 `research/data/models/bisenet_resnet18.onnx` (입술 평가와 동일). 눈 클래스 4·5·6만 본다. 눈 전체 영역이라 IoU가 높아도 가는 선이라는 뜻은 아니다. 앱에 연결하지 않는다.

## YouCam

```
python research/youcam/compare_liner.py --image research/data/liner/images/<one>.jpg
```

정지 1장만. 결과 색으로 hex를 바꾸지 않는다.
