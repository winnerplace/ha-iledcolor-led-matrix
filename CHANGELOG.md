# Changelog

이 프로젝트의 주요 변경사항을 기록한다. 포맷은 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)를 따른다.

버전 체계는 `YY.M.PATCH`이며 릴리즈마다 PATCH를 1씩 올린다. manifest `version`, git 태그, GitHub 릴리즈가 항상 동일해야 한다. 자세한 규칙은 [CLAUDE.md](CLAUDE.md) 참고.

## [26.6.11] - 2026-06-26

### Added
- 한국어 번역(`translations/ko.json`) — `상태표시`, `갱신 주기`, `텍스트 표시`, 서비스/옵션 한글화.
- 브랜드 아이콘(글래스 LED 매트릭스) — home-assistant/brands 제출용 `icon.png`(256), `icon@2x.png`(512).

### Changed
- 상태표시 행 포맷을 `{장소} {엔티티 이름} {값}`으로 변경 (area 레지스트리에서 장소 조회, 없으면 생략).

## [26.6.10] - 2026-06-26

### Added
- **Pretendard 폰트 번들** (`custom_components/iledcolor/fonts/`, OFL) — HA(리눅스 컨테이너)처럼 시스템 CJK 폰트가 없는 환경에서도 한글이 렌더된다.

### Changed
- 폰트 로드를 `lru_cache`로 캐싱 — 매 렌더마다 폰트를 11회씩 재로드하던 것을 1회로. 텍스트/상태표시 갱신 속도가 크게 개선된다.

## [26.6.9] - 2026-06-26

GIF/텍스트/이미지 효과·전송 개선 + 개발용 GUI.

### Added
- `display_color` 서비스 — 패널 단색 채우기.
- 이미지/GIF **파일 업로드** 지원 (`file_upload` 의존성, 서비스 다이얼로그에서 직접 업로드).
- `display_image`에 배경 키아웃(`background`/`tolerance`)·`effect`·`speed`·`dwell` 추가.
- `display_gif`에 `effect`·`speed` 추가.
- `display_text`에 `dwell`(정지시간) 추가.
- effect 코드 정리 — 0 정지 / 1 좌 / 2 우 / 3 상 / 4 하 / 5 눈송이 / 6 두루마리 / 7 레이저.
- 개발용 직접통신 도구 — CLI `iledcolor_display.py`, Tkinter GUI `iledcolor_gui.py`(자동 스캔·미리보기·effect 애니메이션·버튼 상태 관리).

### Changed
- 벌크 전송을 윈도우 스트리밍(in-flight 32)으로 변경 — 작은 전송은 빠르고 큰 전송은 안정적.
- legacy GIF 포맷 수정 — 프레임 뒤에 trailing `be16(speed)` 부착, stayTime(`frame_hold`, 기본 10)을 speed와 분리. 단일 프레임 GIF도 동일 포맷.
- 투명 알파를 검정으로 합성, 한글 등 CJK 폰트 자동 선택.
- 텍스트/이미지 스크롤 시 `dwell=0`으로 무정지 연속 가능.

### Fixed
- GIF 컬러 깨짐 — multi-frame pixel data에 trailing speed 누락이 원인.
- GIF 배경 흰색 노출 — `background` 키아웃으로 해결.

## [26.6.8] - 2026-06-25

- legacy(demo) 소스 포맷 실구현 — `0x54 0x06` 헤더 + textData PULL 스트리밍. 벤더 demo 소스와 바이트 단위 일치. 실기 텍스트 디스플레이 검증.

## [26.6.7] - 2026-06-25

- 벌크 미응답 시 락 장기 점유로 on/off가 멈추던 문제 완화.
- capability 자동 재파싱.

## [26.6.6] - 2026-06-25

- legacy `0x54` 벌크 경로 추가.
- Display text 엔티티 + status display 가이드.

## [26.6.5] - 2026-06-25

- capability 파싱 오프셋 정정 + 교차검증 반영.
- 패널 크기 / 세대(legacy·app2024) 오버라이드.

## [26.6.4] - 2026-06-25

- power/brightness를 legacy 프레이밍으로 복구 (on/off 복구).
- 패널 크기 가드 추가.

## [26.6.3] - 2026-06-25

- 텍스트·이미지·GIF 표시 구현 (`0xA8` 벌크 경로).

## [26.6.2] - 2026-06-25

- 밝기 프레임을 shipped 앱 인코딩으로 정정.
- 벌크 와이어 리버스 엔지니어링 + 상태표시 스캐폴딩.

## [26.6.1] - 2026-06-24

- iLEDcolor BLE Home Assistant 통합 최초 릴리즈.
