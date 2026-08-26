# Engram Custom Overlay

Engram의 External Overlay Event API v1을 사용하는 독립 커스텀 오버레이 프로젝트다.

이 저장소는 다음 브랜치 정책을 사용한다.

- `master`: 검증과 릴리스를 마친 안정 버전을 유지한다.
- `dev`: 다음 릴리스를 위한 통합 브랜치다.
- `feat/*`: 실제 기능 개발 브랜치이며 검증 후 `dev`에 병합한다.

현재 단계의 목표는 Engram이 제공하는 metadata-only 이벤트를 받아 시각 상태로 표현하고,
필요한 포인터 입력과 창 geometry를 Engram에 돌려주는 최소 renderer를 만드는 것이다.

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

## 포함된 overlay

| id | backend | 설명 |
| --- | --- | --- |
| `xeyes` | Tk | 화면 전체의 mouse pointer를 따라보는 두 눈. 첫 API/입력 smoke 구현 |
| `robot-arm` | Tk | 천장 root에서 Z 자세로 내려오며 iris·LED·ambient 표정을 재생하는 단안 3-link arm |
| `robot-arm-3d` | Tk software 3D | 고정 카메라에서 독립적인 XYZ 운동을 원근 투영·depth sort·면 조명으로 렌더링하는 단안 3-link arm |
| `robot-arm-3d-v2` | Tk textured software 3D | 생성형 material atlas를 quad 세분 면에 샘플링하고 적층 외장·케이블 레일을 확장한 산업형 단안 arm |

## 설치와 릴리스

GitHub Release의 wheel을 내려받아 설치하거나 저장소에서 editable install을 사용할 수 있다.

```powershell
python -m pip install .\engram_custom_overlay-1.0.0.<build>-py3-none-any.whl
```

버전은 `Major.Minor.Patch.Build` 형식이다. `VERSION`은 앞 세 자리를 관리하고,
Build는 공식 빌드 시 고정한 Git revision count를 사용한다. 재현 가능한 로컬 패키지는 다음처럼 만든다.

```powershell
.\scripts\build-release.ps1 -Build <build> -Python .\.venv\Scripts\python.exe
```

## 문서 기준

이 문서는 2026-08-25 기준 Engram의 `커스텀 오버레이 Event API v1` 매뉴얼과
`ProjectIntelContunuum/docs/overlay-event-api-v1.md`를 대조해 작성했다.
