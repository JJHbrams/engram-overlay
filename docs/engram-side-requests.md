# Engram 측 요청 사항 — rev 2

`engram-overlay`에서 외부 renderer(`bolttagu-2d`)를 만들고 `replace` 모드로 운용하며 확인된, **Engram 본체
변경이 필요한** 항목이다. renderer 쪽에서 해결 가능한 것은 이미 처리했고 여기 넣지 않았다.

- rev 1 대비: **2건 종결**, 3건 미해결 유지, **2건 신규**, 1건 우선도 하향
- 대상 코드: `ProjectIntelContunuum` `dev` @ `31a698f` (읽기 전용 확인, 2026-09-04)
- 기준 계약: [Event API v1](event-api-v1.md), 소유권 경계는 [LLM authoring guide](llm-overlay-authoring.md)

## 요약

| # | 항목 | 유형 | 우선도 | 상태 |
| --- | --- | --- | --- | --- |
| R1 | renderer 종료 시 자식 프로세스 고아화 | 버그 | 높음 | 미해결 |
| R2 | renderer 입력 펌프가 예외 하나로 영구 정지 | 버그 | 높음 | 미해결 |
| R3 | `_inbound` 큐가 handshake 이후 영구 미배수 | 버그 | 중간 | 미해결 |
| R4 | presentation 와이어 문자열 확정 | 조율 | **차단** | 신규 |
| R5 | 서브에이전트·백그라운드 위임에 category 없음 | 계약 확장 | 중간 | 신규 |
| R6 | 종료 예고 이벤트·유예 시간 | 계약 확장 | 낮음 | 우선도 하향 |

**R4가 지금 유일하게 차단 중인 항목이다.** 문자열이 어긋나면 런처 연동이 아예 동작하지 않는다.
R1~R3은 서로 독립이라 각각 따로 고칠 수 있다.

### rev 1에서 종결된 항목

| 항목 | 결과 |
| --- | --- |
| Engram → renderer 크기 요청 경로 부재 | **해결.** `overlay.set_size`가 capability gate와 함께 도입됐다. `main.py:1278`에서 `supports("overlay.set_size")`로 확인 후 `1286`에서 발행하는 것을 dev에서 확인했다. |
| replace 모드 컨텍스트 메뉴 행 | **해결.** native `#32768` popup이 Tk `post()`를 블로킹하는 것이 실제 원인이었고, scoped `WH_MOUSE_LL` hook으로 처리됐다. rev 1에 인계했던 내 가설 두 개는 모두 반증됐다. |

---

## R4. presentation 와이어 문자열 확정 (차단 중)

**배경.** 플로팅 런처 설계가 확정됐다. 런처 클릭 → 전체 캐릭터 등장, 캐릭터 클릭 → 대화 입력(기존
2단계 유지), 캐릭터 "닫기" → **축소만**, tray Quit만 프로세스 종료.

renderer 쪽 구현은 끝났다(`engram-overlay` dev `62e9a6f`). **문자열 3개만 맞추면 붙는다.**

| 방향 | 내가 구현한 문자열 |
| --- | --- |
| capability | `overlay.presentation` |
| Engram → renderer | `overlay.show` / `overlay.hide` |
| renderer → Engram | `overlay.visibility_changed`, payload `{"visible": bool}` |

다른 이름을 쓰기로 했다면 알려주면 상수 3개만 고친다. 셋 다 `protocol.py`에 상수로 모아뒀다.

**renderer가 보장하는 동작.**

| 수신 | 동작 |
| --- | --- |
| `overlay.show` | deiconify → 등장 720ms → `geometry_changed` → `visibility_changed{true}` |
| `overlay.hide` | 퇴장 700ms → withdraw → `visibility_changed{false}` |

- **ack는 애니메이션이 끝난 뒤** 보낸다. 시작 시점에 보내면 Engram이 아직 화면에 있는 창을 없는 것으로 취급한다.
- 숨은 동안 geometry를 보내지 않고 **표시될 때** 보낸다. 한 번도 나타나지 않은 renderer는 위치를 보고한 적이 없어 Engram이 말풍선을 앵커할 곳이 없다.
- 보이는데 `show`, 숨었는데 `hide`는 no-op다. 런처 연타로 인사가 다시 재생되지 않는다.
- 퇴장 재생 중 `show`가 오면 예약된 숨김을 취소하고 창을 유지한다.
- `display_hint`는 표시 여부와 독립이다. 숨은 동안 도착하면 포즈만 갱신하고 창을 열지 않는다.

**Engram 쪽에 필요한 것.**

1. capability를 광고한 renderer에게 `overlay.show` / `overlay.hide` 발행 (`set_size`와 같은 gate 패턴)
2. manifest argv에 `--presentation` 추가. 이 플래그가 있을 때만 renderer가 capability를 광고하고 숨은 상태로 시작한다
3. `overlay.visibility_changed` 수용 (선택 — 아이콘 상태 동기화용, 없어도 동작함)

**2번이 왜 필요한가.** capability를 무조건 광고하고 숨어서 시작하면 런처가 없는 Engram에서 영원히 안
보인다. 반대로 보이게 시작하면 새 Engram에서 첫 `hide`가 도착하기 전에 캐릭터가 번쩍인다. 플래그로
갈라서 양쪽 모두 회귀가 없게 했다.

## R5. 서브에이전트·백그라운드 위임에 category가 없다

**현상.** 팩이 제공하는 `waiting` 애니메이션(큐·재시도·대기)을 위임 작업에 쓸 수 없다.

**근거.** `tool_category()`가 Task/Agent를 어느 패턴에도 매칭하지 않아 `other`로 떨어진다.
`execute`는 `shell`·`exec`·`build`·`test`·`run`만 잡는다.

renderer는 `tool.started`의 `payload.category`를 이미 활용하고 있다. 이게 `generating`으로 뭉개진
도구들을 가르는 유일한 단서다.

| category | 현재 renderer 표시 |
| --- | --- |
| `write` | 작성 (코드·문서·아티팩트) |
| `execute` | 대기 (백그라운드 명령) |
| `read` | 열람 |
| 그 외 / 없음 | 응답 스트리밍 |

**제안 — 둘 중 하나.**

| 안 | 변경 | 장단 |
| --- | --- | --- |
| **A (권장)** | `execute` 패턴에 `task`·`agent` 추가 | 한 줄. 계약 변경 없음. renderer 수정 없이 오늘 바로 동작 |
| B | 새 category `delegate` 신설 | "명령 실행"과 "서브에이전트 대기"를 구분 가능. category enum이 늘지만 renderer는 모르는 값을 무시하므로 additive-safe |

A로 충분하다고 본다. B가 필요할 만큼 두 상태를 구분해야 하는지는 실사용을 보고 판단하면 된다.

## R1. renderer 종료 시 자식 프로세스가 고아로 남는다

*(rev 1에서 변경 없음. dev `31a698f`에서 `stop()`이 여전히 단순 `terminate()`/`kill()`을 호출한다.)*

**현상.** Engram을 종료하거나 renderer를 교체해도 오버레이 창이 화면에 남는다.

**근거.** `engram-custom-overlay.exe`는 setuptools 콘솔 스크립트 런처이고, 실제 Tk 창은 그것이 **별도
프로세스로 spawn한 `python.exe`**가 소유한다. `event_api.py`의 `stop()`은 `Popen`이 직접 만든 런처만
종료하므로 창을 든 자식은 살아남는다. 검증 세션에서 창을 든 python 프로세스 4개가 실제로 잔존했다.

**영향.** 유령 창이 누적된다. 번들 renderer로 복구해도 외부 창이 그대로 떠 있어 fallback이 동작하지
않은 것처럼 보인다.

**제안.** `stop()`이 프로세스 **트리**를 종료한다. Windows에서는 `CREATE_NEW_PROCESS_GROUP` +
`taskkill /PID <pid> /T /F` 또는 Job Object. 이미 `terminate()` → `wait` → `kill()` 단계가 있으니 각
단계의 대상을 트리로 바꾸면 된다.

**참고.** manifest `command`를 런처 대신 `python.exe -m engram_overlay`로 직접 지정하면 피할 수 있지만,
renderer 작성자마다 알아서 피해가야 하는 함정이 된다. Engram이 임의 argv를 실행하는 이상 호스트에서
트리를 종료하는 편이 맞다.

## R2. renderer 입력 펌프가 예외 하나로 영구 정지한다

*(rev 1에서 변경 없음. `main.py`의 `_drain_external_renderer_messages`에서 재예약이 여전히 `try` 밖이다.)*

**현상(잠재).** 어느 시점 이후 renderer 입력이 전부 무시된다. 클릭·메뉴·geometry·드래그가 모두 죽는데,
renderer는 별도 프로세스라 계속 애니메이션이 돌아 **정상으로 보인다.**

**근거.** 잡는 예외가 `queue.Empty` 하나뿐이다. `_handle_external_renderer_message`가 내부에서
`(KeyError, TypeError, ValueError)`만 처리하므로 `TclError`·`AttributeError`·`OSError` 등은 그대로
올라오고, 그러면 `root.after(50, ...)` 재예약이 실행되지 않아 펌프가 프로세스 수명 내내 멈춘다.
`report_callback_exception`이 로그로만 흘리므로 조용히 죽는다. `_restore_bundled_renderer()` 호출은
try 보호도 없다.

`replace`가 더 위험하다. `observer`는 드래그에서 early return하고 geometry 경로를 건너뛰지만, `replace`는
메시지마다 geometry·모니터 work rect·상태 파일 쓰기를 타고 withdraw된 창에 접근한다.

**제안.** 재예약을 `finally`로 옮겨 펌프 생존을 보장하고, 넓은 `except`로 로그를 남긴다.

**주의.** 이 결함은 종결된 컨텍스트 메뉴 건의 원인이 **아니었다.** 그것과 무관하게 독립적으로 고칠
가치가 있는 구조 결함이다.

## R3. `_inbound` 큐가 handshake 이후 배수되지 않는다

*(rev 1에서 변경 없음. `event_api.py`에서 `put`은 매 메시지, `get`은 handshake 1회뿐이다.)*

**근거.** `_read_stdout()`이 renderer의 **모든** 메시지를 `_inbound`에 적재하지만, `_inbound.get()`은
`start()`의 handshake 대기 한 번뿐이다. 실제 소비는 `on_message` 콜백이 담당하므로 `_inbound`는 아무도
읽지 않는 사본이다.

**영향.** `replace`에서 창을 드래그하면 `drag_move`가 마우스 이동마다 발생해 증가가 가장 빠르다.
무제한 큐라 `put`이 막히지는 않지만 장시간 세션에서 메모리가 단조 증가한다.

**제안.** handshake 이후 적재하지 않거나 `maxsize`를 두고 오래된 항목을 버린다. handshake 전용이라면
`queue.Queue(maxsize=1)` + 이후 무시가 가장 단순하다.

## R6. 종료 예고 이벤트와 유예 시간 (우선도 하향)

**하향 이유.** 런처 설계에서 흔한 "닫기"는 프로세스 종료가 아니라 **축소**이고, 그 경로는 R4의
`overlay.hide`로 퇴장 애니메이션이 제대로 재생된다. 이제 이 항목은 tray Quit 한 경로에만 해당한다.

**남은 현상.** 캐릭터가 표시된 상태에서 tray Quit을 하면 작별 인사 없이 사라진다. `stop()`이 stdin을 닫은
직후 곧바로 종료시켜 재생할 틈이 없다.

**제안(원안 유지).** stdin을 닫기 전에 `overlay.shutdown` + `grace_ms`(1초 내외 상한)를 보내고 짧게
기다린다. 무응답 renderer는 지금과 똑같이 강제 종료되므로 회귀가 없다.

시각적 완성도 문제이고 기능 손실은 없다. R1~R5 뒤로 미뤄도 된다.

---

## 부록: 우리 쪽에서 이미 처리한 것

Engram 변경 없이 renderer 쪽에서 해결했으므로 요청 대상이 아니다.

- **상태별 애니메이션** — `display_hint` 12종 전부와 `payload.category`를 팩의 11개 상태로 매핑했다.
- **크기** — `--scale`로 시작 크기를 소유하고, `overlay.set_size` 요청은 종횡비를 지켜 수용한다.
- **좌우반전** — 포인터 방향 추적을 renderer 내부에서 처리한다.
- **presentation 전이 규칙** — 연타·중복·전환 중 반전 등 엣지 케이스는 renderer가 흡수한다.
