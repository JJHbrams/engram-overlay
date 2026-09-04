# Overlay preset 상세

각 preset이 `display_hint`를 어떤 그림으로 옮기는지와, 그 그림을 만드는 방식이다.
등록 방법은 [README](../README.md), 계약은 [Event API v1](event-api-v1.md)을 본다.

## bolttagu-2d

### 에셋

- 원본 sprite pack은 1254×1254 전체 캔버스 PNG 27MB다. 그대로 담지 않는다.
- 현재 반영 버전은 `atlas.json`의 `source`에 기록된다 (`sprite-pack-v9`).
- `scripts/build-bolttagu-assets.py`가 모든 프레임의 알파 bbox 합집합으로 한 번 crop하고 0.25배로 축소해 가로 sheet로 묶는다. 결과는 270×302 셀, 총 549 KiB.
- 한 crop을 공유하므로 모든 포즈가 같은 발 기준점에 정렬된다.
- crop·배율·발 기준점은 `assets/bolttagu_2d/atlas.json`에 기록되고 overlay가 그 값을 읽는다. 코드에 하드코딩하지 않는다.

```powershell
python scripts/build-bolttagu-assets.py --pack <sprite-pack-vN>
```

### 상태 매핑

프레임은 아래에서 위로 합성하는 `(sheet, cell)` 레이어 recipe다. idle이 독립된 두 루프의 합성이라 단일 프레임으로 표현되지 않기 때문이다.

| display hint | recipe |
| --- | --- |
| `idle`, `default`, `input`, `success` | idle 눈 상태 + 커피 김 |
| `hover`, `click`, `error` | 아하 alert 정지 포즈 |
| `generating`, `search`, `thought`, `memory` | wondering 8프레임 10fps 반복 |
| `provider_error` | 뒷모습 퇴장 3프레임 one-shot 후 alert 유지 |

- 합성은 눈에 보이는 프레임이 바뀔 때만 한다. 조합을 미리 캐싱하지 않는다. 전부 캐싱하면 배율에 따라 수십 MB가 된다.
- renderer가 열릴 때 등장 인사 3프레임(200/300/220ms)이 한 번 재생된다.
- 종료 애니메이션은 종료 시점에 재생되지 않는다. Event API에 종료 예고가 없어 `provider_error`에 붙여둔 것이다.

### 애니메이션

- **눈깜빡임** — 반감김 50ms → 닫힘 90ms → 반감김 70ms → 열림. 다음 깜빡임은 완료 후 2.5~6초에서 무작위. 난수원은 주입 가능해 테스트에서는 고정된다. idle 재진입과 등장 인사 종료 때 재무장한다.
- **커피 김** — 24프레임 10fps(2.4초) 반복. 캐릭터가 든 머그의 김이라 바닥 레이어를 꺼도 나온다. 깜빡임과 위상이 독립이다.
- **포인터 방향** — 원본이 볼따구와 머그를 화면 왼쪽에 두고 그려져 이미 왼쪽을 본다. 그래서 포인터가 창 중심보다 **오른쪽**일 때만 좌우반전한다. 중심 ±24px는 deadzone이라 경계에서 깜빡이며 뒤집히지 않는다. `--no-face-pointer`로 끈다.

### 크기

- 시작 크기는 manifest argv의 `--scale`로 정한다. 기본 1.0이 원화 그대로의 270×302, 허용 범위는 0.2~4.0이다.
- `replace` 모드에서는 이후 Engram이 크기를 요청할 수 있다. renderer가 handshake에서 `overlay.set_size` capability를 advertise하기 때문이다.
- 요청받은 높이는 종횡비를 지킨 채 위 배율 범위 안으로 clamp하고, 적용된 실제 크기를 `overlay.geometry_changed`로 회신한다. 그림을 늘리지 않는다.
- `observer` 모드와 capability를 알리지 않은 renderer는 크기 요청을 받지 않는다.
- 셀을 미리 확대하지 않고 완성된 프레임만 리샘플링하므로 배율을 올려도 메모리는 그대로다. 초당 12회 이하만 다시 그리므로 비용도 무시할 수준이다.

### 옵션

- 불투명 타원 바닥과 쏟은 커피는 `Bolttagu2dView(show_floor=True)`로 켠다. 기본은 꺼짐이다.

## rabbit-2d

- `docs/컨셉아트/rabbit.jpg`의 다섯 포즈를 투명 3×2 atlas로 정리해 쓴다.
- Engram 기본 sprite grid처럼 한 time bucket 안에서는 프레임을 고정하고, 다음 bucket에서 직전 프레임을 뺀 후보 중 무작위로 고른다.

| display hint | rabbit 상태 |
| --- | --- |
| `idle`, `default` | 졸림·놀람·울먹임·궁금함·화남 5종 shuffle |
| `hover`, `success` | 놀람 |
| `click` | 놀람 또는 화남 |
| `input` | 궁금함 |
| `generating`, `search`, `thought`, `memory` | 의미별 2종 random |
| `provider_error`, `error` | 울먹임 또는 화남 |

## robot-arm 계열

- `robot-arm` — 천장 root에서 Z 자세로 내려오며 iris·LED·ambient 표정을 재생하는 단안 3-link arm.
- `robot-arm-3d` — 같은 arm을 고정 카메라에서 원근 투영·depth sort·면 조명으로 렌더링한다.
- `robot-arm-3d-v2` — 생성형 material atlas를 세분 quad 면에 샘플링하고 적층 외장·케이블 레일을 더한 산업형 arm. `--eye-emission`으로 gaze 방향 mood glow를 켠다.
- `robot-arm-3d-v3` (`CCTV`) — V2 arm의 실제 gaze를 감지해 엄폐·엿보기·이동하는 순례자 실루엣을 합성한 감시 장면.

## xeyes

- 화면 전체의 mouse pointer를 따라보는 두 눈. Event API와 포인터 입력을 처음 확인한 smoke 구현이라 새 overlay의 최소 출발점으로 쓰기 좋다.
