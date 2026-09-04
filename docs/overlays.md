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

매핑은 팩이 `event-map.json`에 밝혀둔 의도를 따른다. 타이밍도 팩의 `sprites.json` 값 그대로다.

| display hint | 상태 | 프레임 · 타이밍 |
| --- | --- | --- |
| `idle`, `default` | idle | 눈 상태 3 + 김 24 레이어 합성 |
| `success` | success → idle | 280/360/360ms **1회** 재생 후 idle 복귀 |
| `hover`, `click` | alert | 아하 정지 포즈 |
| `input` | listening | 420/420/420ms 반복 |
| `generating` | speaking | 220/220/260ms 반복 |
| `thought` | wondering | 320/260/320ms 반복 |
| `search`, `memory` | searching | 650/500/650ms 반복 |
| `error`, `provider_error` | error | 260/300/420ms 반복 |

`generating`은 Engram이 search·memory가 아닌 **모든** 도구를 몰아넣는 catch-all이다. 그래서
`tool.started`의 `payload.category`로 한 단계 더 갈라 쓴다. 이게 없으면 파일을 고치는 것과
답변을 스트리밍하는 것이 똑같이 보인다.

| category | 도구 예 | 상태 |
| --- | --- | --- |
| `write` | write·edit·patch·delete | **writing** — 코드·문서·아티팩트 수정 |
| `execute` | shell·exec·build·test·run | **waiting** — 기다릴 일이 있는 작업 |
| `read` | read·open | searching (문서 열람) |
| 그 외 / 없음 | — | speaking (응답 스트리밍) |

- category는 그 메시지에만 해당한다. `tool.completed`는 category 없이 오므로 상태가 초기화되고,
  도구가 끝난 뒤에도 writing이 남아있지 않는다.
- category는 `generating`만 세분한다. `search`·`thought` 같은 구체적 hint를 덮지 않는다.
- 서브에이전트·백그라운드 태스크 대기는 아직 정확히 잡히지 않는다. Engram의 `tool_category`가
  Task/Agent를 어느 패턴에도 매칭하지 않아 `other`로 떨어지기 때문이다. `execute`가 그 절반을
  덮는다.
- 실패 상태는 **반복**한다. 한 번 재생하고 사라지면 실패가 화면에 남지 않는다.
- 합성은 눈에 보이는 프레임이 바뀔 때만 한다. 조합을 미리 캐싱하지 않는다. 전부 캐싱하면 배율에 따라 수십 MB가 된다.
- 등장 인사 3프레임(200/300/220ms)은 아래 presentation 절 참고.

### 애니메이션

- **눈깜빡임** — 반감김 50ms → 닫힘 90ms → 반감김 70ms → 열림. 다음 깜빡임은 완료 후 2.5~6초에서 무작위. 난수원은 주입 가능해 테스트에서는 고정된다. idle 재진입과 등장 인사 종료 때 재무장한다.
- **커피 김** — 24프레임 10fps(2.4초) 반복. 캐릭터가 든 머그의 김이라 바닥 레이어를 꺼도 나온다. 깜빡임과 위상이 독립이다.
- **포인터 방향** — 원본이 볼따구와 머그를 화면 왼쪽에 두고 그려져 이미 왼쪽을 본다. 그래서 포인터가 창 중심보다 **오른쪽**일 때만 좌우반전한다. 중심 ±24px는 deadzone이라 경계에서 깜빡이며 뒤집히지 않는다. `--no-face-pointer`로 끈다.

### presentation — 런처 아이콘 연동

Engram의 플로팅 런처가 캐릭터의 표시 여부를 소유한다. 2단계 상호작용이다: **런처 클릭 → 캐릭터 등장**,
**캐릭터 클릭 → 대화 입력**. 캐릭터의 "닫기"는 **축소**일 뿐이고 프로세스 종료는 tray의 Quit만 한다.

`--presentation`을 manifest argv에 넣으면 활성화된다.

| 플래그 | capability 광고 | 시작 상태 | 등장 인사 |
| --- | --- | --- | --- |
| 없음 (기본) | 안 함 | 보임 | 프로세스 시작 시 |
| `--presentation` | `overlay.presentation` | 숨김 | `overlay.show` 수신 시 |

플래그로 가른 이유는 롤아웃 안전 때문이다. 런처가 없는 Engram에 capability를 광고하고 숨어서 시작하면
영원히 안 보인다. 반대로 보이게 시작하면 새 Engram에서 hide가 도착하기 전에 캐릭터가 번쩍인다.

| 수신 | 동작 |
| --- | --- |
| `overlay.show` | 창 표시 → `enter` 720ms → 현재 hint 포즈. geometry와 `visibility_changed{true}` 회신 |
| `overlay.hide` | `exit` 700ms → 창 숨김 → `visibility_changed{false}` 회신 |

- **ack는 애니메이션이 끝난 뒤** 보낸다. 시작할 때 보내면 Engram이 아직 화면에 있는 창을 없는 것으로 취급한다.
- 숨은 동안 `tick`을 돌리지 않는다. 안 보이는 창을 다시 그릴 이유가 없다.
- 숨어 있을 때는 geometry를 보내지 않고, **표시될 때 보낸다.** 숨은 renderer는 위치를 보고한 적이 없으므로 Engram이 말풍선을 앵커할 곳이 없다.
- 창은 host가, 전환 애니메이션은 view가 소유한다. view의 `begin_enter`/`begin_exit`는 선택 hook이라, 이를 구현하지 않은 overlay도 애니메이션 없이 즉시 전환된다.

전이 규칙:

| 현재 | 수신 | 결과 |
| --- | --- | --- |
| 보임 | `show` | no-op. 인사를 다시 재생하지 않는다 (런처 연타) |
| 숨김 | `hide` | no-op |
| `exit` 재생 중 | `show` | 예약된 숨김을 취소하고 창을 유지한 채 `enter` |
| `success` one-shot 중 | `hide` | `exit`가 이긴다. lifecycle이 연출보다 우선 |
| 숨김 | hint 변경 | 포즈만 갱신, 창을 열지 않는다 |
| 숨김 | `set_size`/`set_position` | 적용하고 회신. 표시와 무관 |

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
