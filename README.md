# Engram Custom Overlay Toolkit

이미 Engram을 쓰는 사람이 자신의 overlay renderer를 만들어 연동하는 source-first 템플릿이다.

- 포함된 preset은 완제품이 아니라 Event API 구현 예시다.
- Release 주 산출물은 Git tag와 Source archive다. wheel/sdist는 샘플 실행·패키징 검증용 보조 산출물이다.
- 브랜치: `master` 안정 · `dev` 통합 · `feat/*` 개발 후 검증해 `dev`에 병합.

준비물은 Engram, Git, Windows PowerShell, Python 3.11 이상이다.

## 빠른 시작

### 1. 소스 준비

```powershell
git clone https://github.com/JJHbrams/engram-overlay.git
cd engram-overlay
git checkout v1.1.0.89
```

개발을 이어갈 때는 tag에서 개인 branch를 만들거나 저장소를 fork한다.

### 2. preset 실행

Engram은 Event API v2에서 loopback API만 제공하고 renderer를 실행하지 않는다. renderer가 스스로
접속하는 독립 프로그램이므로, 등록할 manifest가 아니라 실행할 런타임이 필요하다.

```powershell
.\scripts\install-runtime.ps1 -List                          # 목록만 보기
.\scripts\install-runtime.ps1 -Overlay rabbit-2d             # 설치하고 실행
.\scripts\install-runtime.ps1 -Overlay rabbit-2d -Autostart  # Windows 시작 시 자동 실행
python scripts/build-sprite-preview.py                       # 신호별 동작 고르기
```

- 런타임 위치는 `%LOCALAPPDATA%\engram-overlay\`이고, checkout을 지우거나 옮겨도 계속 동작한다.
- **실행 중인 renderer만** Engram `Settings > Overlay`에 나온다. 설치만으로는 목록에 안 뜬다.
- 옵션: `-Scale`·`-Presentation`·`-NoFacePointer`(bolttagu-2d), `-EyeEmission`(robot-arm-3d-v2/v3).
- 설치하면 바로 실행된다. 옵션을 바꿀 때도 다시 실행하면 renderer를 내렸다 새로 띄운다. 설치만 하려면 `-NoStart`.
- 수동 실행은 `%LOCALAPPDATA%\engram-overlay\start-overlay.cmd`. 자동 실행 해제는 `-RemoveAutostart`.
- v1 시절 `%USERPROFILE%\.engram\overlays\*\manifest.yaml`은 이제 동작하지 않는다.
  `-RemoveLegacyManifests`가 manifest만 지우고 `mapping.json` 같은 나머지는 남긴다.
- 코드를 고치며 쓸 때는 `install-dev.ps1`. checkout을 editable로 연결해 수정이 바로 반영된다.
- 설치 없이 목록만 보려면 `engram-custom-overlay --list-overlays`.
- preset 목록의 단일 출처는 `engram_overlay.registry`다. overlay를 추가해도 스크립트는 손대지 않는다.

`build-sprite-preview.py`는 스프라이트 preset에만 해당한다. localhost에 미리보기 페이지를 띄우고 브라우저를 연다.
상단 탭으로 오버레이를 고르면 각 동작이 실제 타이밍으로 재생되고, 어떤 신호에 무엇을 붙일지 눈으로
고를 수 있다. **바로 적용**을 누르면 그 오버레이의 `mapping.json`에 곧바로 쓴다. 코드 수정은 필요 없고,
자세한 규칙은 [Overlay preset 상세](docs/overlays.md)에 있다.

renderer가 Engram을 찾는 방법:

- `%USERPROFILE%\.engram\overlay-event-api-v2.json`에서 현재 `host`/`port`/`instance_id`/`token`을 읽는다.
- 세 값 모두 Engram이 켜질 때마다 새로 생성되므로 캐시하지 않는다.
- Engram이 꺼져 있으면 실패가 아니라 대기다. backoff로 재시도하다 켜지면 붙는다.
- `token`은 argv·설정·로그 어디에도 남기지 않는다.

### 3. 자신의 overlay 만들기

coding agent에는 저장소의 `create-engram-overlay` skill을 쓰게 한다. backend 선택, module/registry, roster, focused test, Event API 검증을 한 흐름으로 묶는다.

```text
create-engram-overlay skill을 사용해서 <원하는 동작과 디자인> overlay를 만들어줘.
```

직접 시작하려면 scaffold를 dry-run한 뒤 적용한다.

```powershell
python scripts/scaffold-overlay.py my-overlay --name "My Overlay" --dry-run
python scripts/scaffold-overlay.py my-overlay --name "My Overlay"
```

- scaffold는 module·test·registry 항목과 `tests/roster.json` 항목을 만든다. 등록할 manifest는 없다.
- `install-dev.ps1`로 editable install 후 `--overlay my-overlay`로 실행하면 Engram에 나타난다.

### 4. 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
@() | .\.venv\Scripts\engram-custom-overlay.exe --overlay rabbit-2d --v1-stdio --headless
python scripts/verify-connection.py --overlay rabbit-2d
```

세 줄은 각각 단위 테스트, JSONL 파싱 계약, 실제 Engram 접속·등록 검증이다.
마지막 줄은 Engram이 떠 있어야 하고, 없으면 실패가 아니라 exit 2로 알린다.

## 포함된 preset

| id | 이름 | backend | 설명 |
| --- | --- | --- | --- |
| `bolttagu-2d` | Bolttagu | Tk sprite sheet | 검색·작성·응답·실패 등 상태별 애니메이션과 랜덤 눈깜빡임·커피 김을 합성하는 2D 캐릭터 |
| `rabbit-2d` | Rabbit | Tk sprite grid | 손그림 토끼 5개 포즈를 의미 이벤트에 맞춰 회전. 매핑 선택 가능 |
| `xeyes` | Engram XEyes | Tk | mouse pointer를 따라보는 두 눈. 첫 API/입력 smoke |
| `robot-arm` | Engram 3-Link Robot Arm | Tk | 천장에서 내려오는 iris·LED 표정의 단안 3-link arm |
| `robot-arm-3d` | Engram 3D Robot Arm | Tk software 3D | 같은 arm을 원근 투영·depth sort·면 조명으로 렌더링 |
| `robot-arm-3d-v2` | Engram Textured 3D Robot Arm V2 | Tk textured software 3D | 생성형 material atlas를 세분 quad에 샘플링한 산업형 arm |
| `robot-arm-3d-v3` | CCTV | Tk textured software 3D + 2D actors | V2 arm의 gaze를 피해 숨고 엿보는 순례자 실루엣 |

각 preset의 상태 매핑과 애니메이션 세부는 [Overlay preset 상세](docs/overlays.md)에 있다.

## API 핵심

| 항목 | 계약 |
| --- | --- |
| transport | Engram이 시작한 로컬 child process의 stdin/stdout JSONL |
| schema | `schema_version: 1` |
| handshake | renderer stdout의 첫 줄은 `overlay.hello` |
| privacy | 대화·thinking·도구 payload·파일 경로를 받지 않는 `metadata_only` |
| modes | `observer`는 번들 캐릭터와 공존, `replace`는 번들을 대체 |
| sizing | `overlay.set_size`를 advertise한 `replace` renderer만 크기 요청을 받는다 |
| presentation | `overlay.presentation`을 advertise한 renderer는 Engram 런처가 show/hide로 표시를 소유한다 |
| fallback | handshake·JSONL·child 오류 시 Engram 번들 renderer 복구 |

- 세부 계약: [Event API v1](docs/event-api-v1.md)
- 프로젝트 구조: [Overlay 구현 계층](docs/architecture.md)
- 개발 순서: [개발 가이드](docs/development.md)
- LLM으로 만들 때: [LLM authoring guide](docs/llm-overlay-authoring.md)

## 패키징과 릴리스

- 개발 중에는 editable install을 쓴다. wheel은 필수가 아니다.
- 버전은 `Major.Minor.Patch.Build`다. `VERSION`이 앞 세 자리, Build는 빌드 시 고정한 Git revision count다.

```powershell
.\scripts\build-release.ps1 -Build <build> -Python .\.venv\Scripts\python.exe
```

## 문서 기준

2026-08-25 기준 Engram의 `커스텀 오버레이 Event API v1` 매뉴얼과 `ProjectIntelContunuum/docs/overlay-event-api-v1.md`를 대조해 작성했다.
