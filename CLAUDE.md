# CLAUDE.md

## 버전 업데이트 규칙

릴리즈할 때 아래 4곳의 버전 문자열을 **반드시 한 번에 동기화**한다. 하나라도 어긋나면 HACS·사용자가 잘못된 버전을 본다.

```
manifest.json version  ==  git 태그  ==  GitHub 릴리즈  ==  CHANGELOG 헤더
```

### 버전 번호
- 형식: `YY.M.PATCH` (예: `26.6.9`). **`v` 접두사 없음** (태그도 bare `26.6.9`).
- 릴리즈마다 **PATCH를 1 증가**시킨다. 날짜 기반 아님 — `26.6.8` 다음은 `26.6.9` (`26.6.26` 같은 날짜 표기 금지).
- `YY.M`은 임의로 바꾸지 않는다. 변경이 필요하면 명시적으로 합의 후.

### 릴리즈 체크리스트
1. `custom_components/iledcolor/manifest.json`의 `version`을 새 버전으로 올린다.
2. `CHANGELOG.md` 맨 위에 `## [버전] - YYYY-MM-DD` 섹션을 추가한다 (`### Added` / `### Changed` / `### Fixed`).
3. 테스트 통과 확인: `python3 -m pytest tests/ -q`.
4. 커밋 — 제목 끝에 `(버전)`을 붙인다. 예: `feat: ... (26.6.9)`.
5. 같은 커밋에 bare 태그를 단다: `git tag -a 26.6.9 -m "Release 26.6.9"`.
6. push: `git push origin main --tags`.
7. **GitHub 릴리즈** 생성: `gh release create 26.6.9 --title "26.6.9 — <요약>" --notes-file <CHANGELOG 해당 섹션>`.

기존 릴리즈를 재작성해야 하면(태그/메시지 정정) 태그를 다시 달고(`git tag -f`), 원격 태그를 갱신(`git push -f origin <tag>`)한 뒤 GitHub 릴리즈도 맞춘다.
