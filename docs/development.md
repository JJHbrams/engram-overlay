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

1. stdout 첫 줄에 `overlay.hello`를 출력한다.
2. stdin JSONL을 별도 reader에서 파싱한다.
3. `display_hint`를 renderer 내부의 시각 상태로 매핑한다.
4. `overlay.set_position`으로 창 위치를 동기화한다.
5. replace에서는 geometry와 pointer action을 stdout으로 보낸다. interactive observer도 geometry와 pointer action을 보내면 같은 bubble session의 클릭 앵커가 된다.
6. 프로토콜 로그는 stderr로만 출력한다.
7. parser와 outbound envelope을 UI 없이 테스트할 수 있게 분리한다.

## 로컬 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[tools]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\engram-custom-overlay.exe --overlay xeyes --mode replace
```

개발 설치와 manifest 생성을 한 번에 하려면 `scripts/install-dev.ps1`을 실행한다.
생성 위치는 `%USERPROFILE%/.engram/overlays/xeyes/manifest.yaml`이다.
선택을 자동화할 때는 `scripts/select-overlay.py`의 dry-run을 먼저 확인하고 `--apply`를 사용한다.
이 스크립트는 기존 top-level 설정 키를 검증하고 백업 뒤 원자적으로 `overlay.external_renderer`만 바꾼다.

프로젝트 계층과 새 renderer 추가 규칙은 [Overlay 구현 계층](architecture.md)을 따른다.

## 완료 기준

- handshake가 stdout 첫 줄에 한 번 출력된다.
- 잘못된 입력 JSONL이 renderer를 중단시키지 않고 stderr에 기록된다.
- 알 수 없는 type과 필드를 무시한다.
- 모든 공개 `display_hint`가 안전한 기본 상태를 가진다.
- protocol 단위 테스트와 실제 child-process JSONL smoke test가 통과한다.
- Engram 설정용 manifest 예제가 제공된다.
