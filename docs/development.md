# 개발 가이드

## 브랜치 흐름

```text
master (문서 기준선)
  └─ dev (다음 버전 통합)
       └─ feat/<slug> (구현과 테스트)
```

기능은 `dev`에서 `feat/*` 브랜치를 만든 뒤 구현하고, 검증 후 `--no-ff`로 `dev`에 병합한다.
안정화 전에는 구현 파일을 `master`에 병합하지 않는다.

## 첫 구현 범위

1. renderer 프로세스를 외부 앱이 독립적으로 시작한다. Engram용 command manifest를 만들지 않는다.
2. discovery 파일을 renderer가 읽고 loopback TCP에 연결해 첫 줄로 `overlay.register`를 보낸다.
3. Engram 시작 순서와 재시작에 관계없이 discovery를 다시 읽고 bounded backoff로 재접속한다.
4. `display_hint`를 renderer 내부의 시각 상태로 매핑한다.
5. `overlay.set_position`으로 창 위치를 동기화한다.
6. replace에서는 geometry와 pointer action을 socket으로 보낸다. interactive observer도 geometry와 pointer action을 보내면 같은 bubble session의 클릭 앵커가 된다.
7. 모든 정상 outbound envelope은 `schema_version: 2`이고 로그는 stderr로만 출력한다.
8. parser와 outbound envelope을 UI 없이 테스트할 수 있게 분리한다. `--v1-stdio`는 legacy/test-only다.

## 로컬 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[tools]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\engram-custom-overlay.exe --overlay xeyes --mode replace
```

`.venv` 생성과 editable install을 한 번에 하려면 `scripts/install-dev.ps1`을 실행한다.
checkout과 무관하게 사는 런타임을 설치하거나 Windows 시작 시 자동 실행하려면
`scripts/install-runtime.ps1`을 쓴다. 둘 다 manifest를 만들지 않는다 — v2의 Engram은
renderer를 실행하지 않으므로 실행 방법을 적어둘 곳이 없다.
`install-runtime.ps1 -All`은 package와 모든 asset을 독립 runtime에 복사하고 catalog provider 하나를
실행한다. `-Overlay <id>`는 기존 singleton 개발/호환 경로다. catalog provider가 선택된 preset을 private
`--v1-stdio --presentation` worker 하나로 바꾸는 것은 renderer package 내부 구현이며 Engram에는 worker
command, path, asset 또는 lifecycle이 노출되지 않는다.
접속이 되는지 확인할 때는 `scripts/verify-connection.py`를 쓴다. discovery 읽기·접속·등록까지만 하고
바로 끊으므로 실행 중인 renderer의 선택을 건드리지 않는다. Engram이 꺼져 있으면 exit 2다.

프로젝트 계층과 새 renderer 추가 규칙은 [Overlay 구현 계층](architecture.md)을 따른다.

## 완료 기준

- `overlay.register`가 소켓의 첫 줄로 한 번 전송되고 token은 어디에도 기록되지 않는다.
- geometry, visibility, pointer, heartbeat outbound가 active v2 transport에서 schema 2를 사용한다.
- 잘못된 입력 JSONL이 renderer를 중단시키지 않는다.
- 알 수 없는 type과 필드를 무시한다.
- 모든 공개 `display_hint`가 안전한 기본 상태를 가진다.
- Engram이 꺼져 있거나 재시작해도 창이 살아남고 backoff로 다시 붙는다.
- protocol 단위 테스트와 `verify-connection.py`의 실제 등록이 통과한다.

구현 가능한 전체 wire 계약은 [Event API v2](event-api-v2.md)를 기준으로 한다. [Event API v1](event-api-v1.md)은
명시적 `--v1-stdio` 회귀 테스트용 문서다.
