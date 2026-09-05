# Engram External Overlay Event API v2

Event API v2의 기본 소유권은 명확하다. Engram은 인증된 loopback metadata-only API와 선택·fallback을
호스팅하고, 외부 앱은 renderer 프로세스, 설치 경로, 시작·종료·재시작을 소유한다. Engram은 renderer를
실행하거나 중지하지 않으며 executable, argv, cwd, venv, asset path, command manifest를 받지 않는다.

## Discovery, 연결, 등록

Engram은 OS-assigned port로 `127.0.0.1`에만 TCP JSONL listener를 열고 현재 사용자 discovery 파일을 쓴다.

```text
~/.engram/overlay-event-api-v2.json
```

```json
{"schema_version":2,"host":"127.0.0.1","port":49152,"instance_id":"example-instance-id","token":"example-only-not-a-live-token"}
```

예시 값은 placeholder다. Windows에서는 current-user ACL, 그 외 OS에서는 `0600`이 적용된다. `port`,
고엔트로피 `token`, `instance_id`는 host 시작마다 바뀐다. token을 argv, 설정, stdout/stderr, 오류,
telemetry에 기록하지 않는다. renderer는 discovery를 직접 읽고 TCP 연결 후 2초 안에 첫 줄로 등록한다.

```json
{"schema_version":2,"type":"overlay.register","payload":{"token":"value-read-from-discovery","instance_id":"current-instance-id","renderer_id":"vendor.renderer","name":"Vendor Renderer","supported_modes":["observer","replace"],"capabilities":["overlay.presentation"]}}
```

필수 payload는 `token`, `instance_id`, `renderer_id`, `name`, `supported_modes`이고 `capabilities`는 선택이다.
`renderer_id`는 1–64자의 ASCII letter/digit/`.`/`_`/`-`이며 mode는 `observer`, `replace` 중 하나 이상이다.
stale instance, 잘못된 token, 중복 ID, 잘못된 mode, timeout은 연결을 닫는다. renderer는 discovery 부재,
connection refusal, EOF 뒤 bounded exponential backoff로 다시 읽고 연결한다. 어느 쪽이 먼저 시작해도 되고
Engram 재시작 뒤 기존 endpoint나 credential을 재사용하지 않는다.

## Host에서 받는 메시지

등록 성공 뒤 `engram.welcome`, 현재 상태를 담은 `state.snapshot`, 초기 `renderer.assignment`가 그 순서로
온다. 선택 재계산 때도 assignment가 다시 온다. welcome payload에는 `selected_schema_version: 2`,
`content_policy: metadata_only`, `mode`, boolean `selected`, `host_instance_id`가 있다. assignment payload에는
exact `mode`와 boolean `selected`가 있다. assignment와 control의 `display_hint`는 현재 resolved hint이며,
payload에 category가 없다는 이유로 renderer의 현재 work state나 `tool_category`를 지우지 않는다.

일반 host envelope은 다음 필드를 가진다.

```json
{"schema_version":2,"id":"evt_example","sequence":1,"timestamp":"2026-01-01T00:00:00+00:00","type":"generation.started","display_hint":"generating","payload":{}}
```

공개 semantic event는 conversation, generation, tool, provider, pointer, speech, memory lifecycle과 bounded
metadata뿐이다. 대화 원문, thinking, tool input/output, 파일 경로, memory/Wiki 본문은 오지 않는다.
`conversation.input_active`는 실제 편집 키 활동 뒤 `input`, `conversation.input_idle`은 700ms inactivity나
focus/hide/submit 뒤 override 종료를 뜻한다. `pointer.left`와 `conversation.input_idle`은 무조건 idle로
초기화하는 명령이 아니다. renderer는 hover/input override 아래 갱신된 generation/tool work hint를 보존하고
override가 끝나면 그 현재 work state로 돌아간다.

`overlay.show`, `overlay.hide`, `overlay.set_position {x,y}`, `overlay.set_size {width,height}`는 선택된 replace
owner에게만 간다. `overlay.presentation`을 광고한 renderer는 show/hide 전이를 수행하고 완료 후 visibility를
ack한다. 의미 이벤트는 observer를 포함한 등록 client에 broadcast될 수 있다.

## Engram으로 보내는 메시지

모든 정상 v2 outbound는 active socket transport의 `schema_version: 2`를 사용한다. payload는 exact schema만
허용하며 extra/nested field를 넣지 않는다.

```json
{"schema_version":2,"type":"overlay.geometry_changed","payload":{"x":120,"y":80,"width":320,"height":480}}
{"schema_version":2,"type":"pointer.action","payload":{"action":"left_click"}}
{"schema_version":2,"type":"pointer.action","payload":{"action":"drag_end","screen_x":240,"screen_y":160}}
{"schema_version":2,"type":"overlay.visibility_changed","payload":{"visible":false}}
{"schema_version":2,"type":"overlay.heartbeat","payload":{}}
```

- geometry의 `x/y`는 -1,000,000–1,000,000 정수, `width/height`는 1–100,000 정수다.
- 좌표 없는 pointer action은 `left_click`, `pointer_enter`, `pointer_leave`, `drag_begin`, `overlay_close`,
  `menu_dismiss`다.
- `right_click`, `drag_move`, `drag_end`는 같은 범위의 정수 `screen_x/screen_y`가 모두 필요하다. drag 좌표는
  raw pointer가 아니라 창 좌상단의 절대 screen position이다.
- visibility payload는 JSON boolean 하나이고 selected replace owner만 보낸다. heartbeat payload는 비어 있다.

host 제한은 UTF-8 line당 65,536 bytes, 등록 전 socket 포함 동시 연결 16개, client당 초당 inbound 120개다.
malformed/oversize/rate 위반은 해당 연결만 종료하거나 거부한다.

## Mode, 선택, fallback

여러 observer가 연결될 수 있지만 replace owner는 선택된 ready renderer 하나다. observer geometry는 그
observer의 transient anchor일 뿐 replace/bundled geometry를 저장하지 않는다. 선택 변경은 assignment로
통지되고 ready replace는 즉시 활성화된다. disconnect 시 Engram은 provider session을 끝내거나 외부
프로세스를 kill하지 않고 bundled renderer로 복귀한다.

Event API v1 stdin/stdout과 command manifest는 retired다. 이 저장소는 parser/headless 회귀용 명시적
`--v1-stdio`만 보존한다. 정상 설치·실행·재접속 경로에는 v1 bridge나 manifest가 없다.
