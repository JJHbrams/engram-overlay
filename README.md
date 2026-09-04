# Engram Custom Overlay Toolkit

이미 Engram을 사용하는 사람이 자신의 overlay renderer를 직접 만들고 연동하기 위한
source-first 개발 템플릿이다. 독립 실행형 완제품이 아니며, 포함된 Rabbit/CCTV 등의
overlay는 Event API와 구현 방식을 보여주는 샘플이다.

Release의 주 산출물은 안정된 Git tag와 GitHub Source archive다. 사용자는 release 소스를
clone/fork해 샘플을 수정하거나 `create-engram-overlay` skill로 새 renderer를 만든다.
wheel과 sdist는 샘플 실행 및 패키징 검증을 위한 보조 산출물이다.

이 저장소는 다음 브랜치 정책을 사용한다.

- `master`: 검증과 릴리스를 마친 안정 버전을 유지한다.
- `dev`: 다음 릴리스를 위한 통합 브랜치다.
- `feat/*`: 실제 기능 개발 브랜치이며 검증 후 `dev`에 병합한다.

현재 단계의 목표는 Engram이 제공하는 metadata-only 이벤트를 받아 시각 상태로 표현하고,
필요한 포인터 입력과 창 geometry를 Engram에 돌려주는 개인 renderer 제작 기반을 제공하는 것이다.

## 빠른 시작

준비물은 Engram, Git, Windows PowerShell, Python 3.11 이상이다.

### 1. Release 소스 준비

```powershell
git clone https://github.com/JJHbrams/engram-overlay.git
cd engram-overlay
git checkout v1.0.1.77
```

직접 개발을 이어갈 때는 tag에서 개인 branch를 만들거나 저장소를 fork한다.

### 2. 샘플 설치와 manifest 등록

다음 명령은 `.venv` 생성, editable install, launcher 절대 경로가 들어간 manifest 생성을
한 번에 수행한다.

```powershell
.\scripts\install-dev.ps1 -Overlay rabbit-2d -Mode replace
```

생성되는 파일은 `%USERPROFILE%\.engram\overlays\rabbit-2d\manifest.yaml`이다.
Engram의 `Settings > Overlay`에서 `Rabbit`을 선택하고 Engram을 재시작한다. 이 스크립트는
현재 선택을 자동으로 바꾸지 않는다.

다른 포함 샘플도 같은 방식으로 등록할 수 있다.

```powershell
.\scripts\install-dev.ps1 -Overlay xeyes -Mode observer
.\scripts\install-dev.ps1 -Overlay robot-arm-3d-v3 -Mode replace -EyeEmission
```

manifest의 핵심 형태는 다음과 같다. `command`의 첫 항목은 실제 checkout의 launcher
절대 경로여야 하며, Engram은 검증된 manifest의 argv만 실행한다.

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

### 3. 자신의 overlay 만들기

Codex/Claude 같은 coding agent에는 저장소의 `create-engram-overlay` skill을 사용하도록
요청한다. 이 skill은 backend 선택, module/registry, manifest, focused test, Event API 검증을
한 작업 흐름으로 묶는다.

```text
create-engram-overlay skill을 사용해서 <원하는 동작과 디자인> overlay를 만들어줘.
```

직접 시작하려면 scaffold를 dry-run한 뒤 적용한다.

```powershell
python scripts/scaffold-overlay.py my-overlay --name "My Overlay" --dry-run
python scripts/scaffold-overlay.py my-overlay --name "My Overlay"
```

scaffold가 만든 `manifests/my-overlay/manifest.yaml`의 launcher placeholder를 현재 `.venv`의
절대 경로로 바꾸고 `%USERPROFILE%\.engram\overlays\my-overlay\manifest.yaml`에 복사한다.
그 뒤 Engram 설정에서 `My Overlay`를 선택하고 재시작한다.

### 4. 검증

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
.\.venv\Scripts\python.exe -m unittest discover -s tests
@() | .\.venv\Scripts\engram-custom-overlay.exe --overlay rabbit-2d --mode replace --headless
```

실제 Engram source와 설치한 manifest의 계약을 함께 확인하려면 다음 검증기를 사용한다.

```powershell
python scripts/verify-engram.py --engram-source <engram-source> --manifest "$HOME\.engram\overlays\rabbit-2d\manifest.yaml"
```

## API 핵심

| 항목 | 계약 |
| --- | --- |
| transport | Engram이 시작한 로컬 child process의 stdin/stdout JSONL |
| schema | `schema_version: 1` |
| handshake | renderer stdout의 첫 줄은 `overlay.hello` |
| privacy | 대화·thinking·도구 payload·파일 경로를 받지 않는 `metadata_only` |
| modes | 번들 캐릭터와 공존하는 `observer` (geometry + click이면 shared bubble anchor), 번들을 대체하는 `replace` |
| fallback | handshake·JSONL·child 오류 시 Engram 번들 renderer 복구 |

세부 계약은 [Event API v1](docs/event-api-v1.md), 프로젝트 구조는
[Overlay 구현 계층](docs/architecture.md), 개발 순서는 [개발 가이드](docs/development.md)를 참고한다.
LLM으로 개인 overlay를 만들 때는 [LLM authoring guide](docs/llm-overlay-authoring.md)와
프로젝트의 `create-engram-overlay` skill을 사용한다.

## 포함된 overlay

| id | backend | 설명 |
| --- | --- | --- |
| `bolttagu-2d` (`Bolttagu`) | Tk sprite sheet | sprite-pack-v8 레이어를 합성해 랜덤 눈깜빡임·커피 김·wondering 루프·등장/퇴장 one-shot을 재생하고 포인터 쪽으로 돌아보는 2D 캐릭터 |
| `rabbit-2d` | Tk sprite grid | 손그림 토끼 5개 상태를 Engram 의미 이벤트에 맞춰 고정·랜덤 회전하는 2D 캐릭터 |
| `xeyes` | Tk | 화면 전체의 mouse pointer를 따라보는 두 눈. 첫 API/입력 smoke 구현 |
| `robot-arm` | Tk | 천장 root에서 Z 자세로 내려오며 iris·LED·ambient 표정을 재생하는 단안 3-link arm |
| `robot-arm-3d` | Tk software 3D | 고정 카메라에서 독립적인 XYZ 운동을 원근 투영·depth sort·면 조명으로 렌더링하는 단안 3-link arm |
| `robot-arm-3d-v2` | Tk textured software 3D | 생성형 material atlas를 quad 세분 면에 샘플링하고 적층 외장·케이블 레일을 확장한 산업형 단안 arm |
| `robot-arm-3d-v3` (`CCTV`) | Tk textured software 3D + 2D actors | V2 arm의 실제 gaze를 감지해 엄폐·엿보기·이동하는 작은 순례자 실루엣을 합성한 감시 장면 |

### Bolttagu 애니메이션 clip

`bolttagu-2d`는 `sprite-pack-v8`의 1254×1254 전체 캔버스 PNG를 그대로 담지 않는다.
`scripts/build-bolttagu-assets.py`가 모든 프레임의 알파 bounding box 합집합으로 한 번 crop하고
0.25배로 축소해 가로 sheet로 묶으므로, 모든 포즈가 같은 발 기준점에 정렬된 채 270×302 셀이 된다.
crop·배율·발 기준점은 `assets/bolttagu_2d/atlas.json`에 기록되고 overlay가 이 값을 읽어 사용한다.
원본 팩을 갱신했으면 스크립트를 다시 실행한다.

```powershell
python scripts/build-bolttagu-assets.py --pack <sprite-pack-v8>
```

프레임은 아래에서 위로 합성하는 `(sheet, cell)` 레이어 recipe로 표현한다. idle이 서로 독립적인
두 루프의 합성이라 단일 프레임으로는 표현되지 않기 때문이다. 합성은 눈에 보이는 프레임이
바뀔 때만 수행하므로 미리 조합을 캐싱하지 않는다.

| display hint | recipe |
| --- | --- |
| `idle`, `default`, `input`, `success` | idle 눈 상태 + 커피 김 |
| `hover`, `click`, `error` | 아하 alert 정지 포즈 |
| `generating`, `search`, `thought`, `memory` | wondering 8프레임 10fps 반복 |
| `provider_error` | 뒷모습 퇴장 3프레임 one-shot 후 alert 유지 |

- **눈깜빡임**: 반감김 50ms → 닫힘 90ms → 반감김 70ms → 열림. 다음 깜빡임은 완료 후
  2.5~6초에서 무작위로 정한다. 난수원은 주입 가능해서 테스트에서는 고정된다.
  idle로 다시 들어올 때와 등장 인사가 끝날 때 재무장한다.
- **커피 김**: 24프레임 10fps(2.4초) 반복. 캐릭터가 들고 있는 머그의 김이라 바닥 레이어를
  꺼도 나온다. 깜빡임과 위상이 독립이다.
- **포인터 방향**: 원본이 볼따구와 머그를 화면 왼쪽으로 두고 그려져 이미 왼쪽을 보므로,
  포인터가 창 중심보다 오른쪽에 있을 때만 좌우반전한다. 중심 ±24px는 deadzone으로
  두어 경계에서 깜빡이며 뒤집히지 않는다. 끄려면 `--no-face-pointer`를 넘긴다.

renderer가 열릴 때 등장 인사 3프레임(200/300/220ms)이 한 번 재생된다.
불투명 타원 바닥과 쏟은 커피는 `Bolttagu2dView(show_floor=True)`로 켤 수 있고 기본값은 꺼짐이다.

#### 크기

Engram 설정의 **캐릭터 높이 비율(`overlay.char_height_ratio`)은 번들 renderer에만 적용된다.**
Event API에는 Engram에서 renderer로 가는 크기 필드가 없고, `overlay.geometry_changed`는 renderer가
자기 크기를 보고하는 방향뿐이라 외부 overlay는 자기 창 크기를 스스로 소유한다. 그래서 크기는
manifest argv의 `--scale`로 지정한다. 기본값 1.0이 원화 그대로의 270×302이고 허용 범위는 0.2~4.0이다.

```yaml
command:
  - "C:/.../engram-custom-overlay.exe"
  - "--overlay"
  - "bolttagu-2d"
  - "--mode"
  - "replace"
  - "--scale"
  - "1.6"
```

셀을 미리 확대하지 않고 **완성된 프레임만** 리샘플링하므로 배율을 올려도 메모리는 그대로다.
초당 12회 이하만 다시 그리므로 비용도 무시할 수준이다.

### Rabbit 상태 grid

`rabbit-2d`는 `docs/컨셉아트/rabbit.jpg`의 다섯 포즈를 투명 3×2 atlas로 정리해 사용한다.
Engram 기본 sprite grid처럼 한 time bucket 안에서는 프레임을 고정하고, 다음 bucket에서
직전 프레임을 제외한 후보를 무작위로 고른다.

| display hint | rabbit 상태 |
| --- | --- |
| `idle`, `default` | 졸림·놀람·울먹임·궁금함·화남 5종 shuffle |
| `hover`, `success` | 놀람 |
| `click` | 놀람 또는 화남 |
| `input` | 궁금함 |
| `generating`, `search`, `thought`, `memory` | 의미별 2종 random |
| `provider_error`, `error` | 울먹임 또는 화남 |

## 패키징과 릴리스

overlay 작성자는 개발 중 editable install을 사용한다. wheel은 저장소를 사용하는 필수 조건이
아니며, 완성한 renderer를 Python 패키지로 공유하거나 release 패키징을 검증할 때 사용한다.

버전은 `Major.Minor.Patch.Build` 형식이다. `VERSION`은 앞 세 자리를 관리하고,
Build는 공식 빌드 시 고정한 Git revision count를 사용한다. 재현 가능한 로컬 패키지는 다음처럼 만든다.

```powershell
.\scripts\build-release.ps1 -Build <build> -Python .\.venv\Scripts\python.exe
```

## 문서 기준

이 문서는 2026-08-25 기준 Engram의 `커스텀 오버레이 Event API v1` 매뉴얼과
`ProjectIntelContunuum/docs/overlay-event-api-v1.md`를 대조해 작성했다.
