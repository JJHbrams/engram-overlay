# Overlay 구현 계층

> 각 overlay는 자기 렌더링 기술과 assets를 소유하고, Engram Event API 계약만 공통으로 사용한다.

## 계층

```text
Engram child process / JSONL
└─ protocol.py + state.py          # 공통 Event API와 metadata-only 상태
   └─ registry.py                  # overlay id → 실행 factory
      ├─ backends/                 # 창·입력·렌더 loop 기술
      │  ├─ tk.py                  # 2D/Tk 공통 host
      │  ├─ opengl.py              # 향후 3D backend
      │  └─ webview.py             # 향후 Live2D/Web renderer
      └─ overlays/<id>/            # 개별 작품의 behavior, scene, packaged assets
         ├─ xeyes.py               # asset 없는 작은 mouse tracking 예제
         ├─ robot_arm.py           # ceiling 3-link Z-IK + single-eye expression VFX
         ├─ image-character/       # 향후 기능형 2D 이미지 + assets/
         ├─ object-3d/             # 향후 3D object + model/texture
         └─ live2d-character/      # 향후 Live2D model + runtime assets

manifests/<id>/manifest.yaml       # Engram 설치·선택 단위
tests/<id>/...                     # behavior와 contract 테스트
```

## 경계 원칙

| 계층 | 소유하는 것 | 소유하지 않는 것 |
| --- | --- | --- |
| protocol/state | JSONL, handshake, hint, geometry, pointer envelope | Tk/OpenGL/Live2D API |
| registry | overlay id와 lazy-loaded 실행 factory | renderer별 설정·assets |
| backend | window, render loop, 공통 pointer/drag/geometry | 작품별 scene과 animation |
| overlay | scene, animation, mouse tracking, renderer별 설정 | Engram 내부 이벤트와 사용자 payload |
| manifest | 설치 command와 지원 mode | runtime behavior |

백엔드는 필요한 범위에서만 공유한다. 2D 이미지와 xeyes는 Tk 또는 Qt host를 공유할 수 있지만,
3D와 Live2D를 같은 view interface에 억지로 맞추지 않는다. 모든 구현이 공유해야 하는 최소 계약은
`OverlayRunner.run()`과 Event API transport뿐이다. Registry는 선택한 overlay module만 import하므로
향후 OpenGL·Live2D dependency가 다른 overlay 실행 환경을 오염시키지 않는다.

## 새 overlay 추가

1. `overlays/<id>/` 또는 작은 구현이면 `overlays/<id>.py`에 runner/factory를 만든다.
2. 필요한 backend가 있으면 `backends/`에 기술별 lifecycle을 둔다.
3. `registry.py`에 id와 factory를 등록한다.
4. `manifests/<id>/manifest.yaml`과 overlay package 내부 `assets/`를 추가한다.
5. headless contract, behavior 수학, 실제 window smoke를 분리해 검증한다.
