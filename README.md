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

### 2. preset 등록

`install-dev.ps1`이 `.venv` 생성, editable install, launcher 절대 경로가 박힌 manifest 생성을 한 번에 한다.

```powershell
.\scripts\install-dev.ps1 -List               # 목록만 보기
.\scripts\install-dev.ps1 -Overlay rabbit-2d  # 하나만 등록
.\scripts\install-dev.ps1 -All                # 전부 등록
```

- manifest 위치는 `%USERPROFILE%\.engram\overlays\<id>\manifest.yaml`이다.
- 등록 뒤 Engram `Settings > Overlay`에서 고르고 재시작한다. 스크립트는 현재 선택을 바꾸지 않는다.
- `-Mode observer|replace` (기본 `replace`), `-Scale`(bolttagu-2d), `-EyeEmission`(robot-arm-3d-v2/v3).
- Engram 런처가 캐릭터 표시를 소유하게 하려면 manifest argv에 `--presentation`을 넣는다.
- `-All`은 overlay별 옵션과 같이 못 쓴다. 그 옵션이 필요한 preset은 따로 등록한다.
- 설치 없이 목록만 보려면 `engram-custom-overlay --list-overlays`.
- preset 목록의 단일 출처는 `engram_overlay.registry`다. overlay를 추가해도 스크립트는 손대지 않는다.

manifest 형태:

```yaml
schema_version: 1
id: rabbit-2d
name: Rabbit
command:
  - "C:/path/to/engram-overlay/.venv/Scripts/engram-custom-overlay.exe"
  - "--overlay"
  - "rabbit-2d"
  - "--mode"
  - "replace"
supported_modes: [observer, replace]
```

- `command` 첫 항목은 실제 checkout의 launcher 절대 경로여야 한다.
- Engram은 검증된 manifest의 argv만 실행한다. shell 문자열이 아니다.

### 3. 자신의 overlay 만들기

coding agent에는 저장소의 `create-engram-overlay` skill을 쓰게 한다. backend 선택, module/registry, manifest, focused test, Event API 검증을 한 흐름으로 묶는다.

```text
create-engram-overlay skill을 사용해서 <원하는 동작과 디자인> overlay를 만들어줘.
```

직접 시작하려면 scaffold를 dry-run한 뒤 적용한다.

```powershell
python scripts/scaffold-overlay.py my-overlay --name "My Overlay" --dry-run
python scripts/scaffold-overlay.py my-overlay --name "My Overlay"
```

- scaffold가 만든 `manifests/my-overlay/manifest.yaml`의 launcher placeholder를 `.venv` 절대 경로로 바꾼다.
- 그 파일을 `%USERPROFILE%\.engram\overlays\my-overlay\manifest.yaml`로 복사하고 Engram을 재시작한다.

### 4. 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
@() | .\.venv\Scripts\engram-custom-overlay.exe --overlay rabbit-2d --mode replace --headless
python scripts/verify-engram.py --engram-source <engram-source> --manifest "$HOME\.engram\overlays\rabbit-2d\manifest.yaml"
```

세 줄은 각각 단위 테스트, JSONL handshake, 실제 Engram source와 설치된 manifest의 계약 검증이다.

## 포함된 preset

| id | 이름 | backend | 설명 |
| --- | --- | --- | --- |
| `bolttagu-2d` | Bolttagu | Tk sprite sheet | 검색·작성·응답·실패 등 상태별 애니메이션과 랜덤 눈깜빡임·커피 김을 합성하는 2D 캐릭터 |
| `rabbit-2d` | Rabbit | Tk sprite grid | 손그림 토끼 5개 포즈를 의미 이벤트에 맞춰 회전 |
| `xeyes` | Engram XEyes | Tk | mouse pointer를 따라보는 두 눈. 첫 API/입력 smoke |
| `robot-arm` | Engram 3-Link Robot Arm | Tk | 천장에서 내려오는 iris·LED 표정의 단안 3-link arm |
| `robot-arm-3d` | Engram 3D Robot Arm | Tk software 3D | 같은 arm을 원근 투영·depth sort·면 조명으로 렌더링 |
| `robot-arm-3d-v2` | Engram Textured 3D Robot Arm V2 | Tk textured software 3D | 생성형 material atlas를 세분 quad에 샘플링한 산업형 arm |
| `robot-arm-3d-v3` | CCTV | Tk textured software 3D + 2D actors | V2 arm의 gaze를 피해 숨고 엿보는 순례자 실루엣 |

각 preset의 상태 매핑과 애니메이션 세부는 [Overlay preset 상세](docs/overlays.md)에 있다.
`bolttagu-2d`의 신호별 동작은 `python scripts/build-bolttagu-preview.py --open`으로 띄우는
미리보기 페이지에서 골라 `mapping.json`으로 내보낼 수 있다.

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
