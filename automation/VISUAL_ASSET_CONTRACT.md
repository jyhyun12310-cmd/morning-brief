# 승인된 편집 이미지와 실제 게시 연결

2026-10-20 사용자 “다 수정해” 승인으로 추가한 공통 제작 계약이다. 새 원고에는 `summary.design="editorial-v2"`를 적용한다. 기존 게시물·오래된 inbox를 이 디자인으로 다시 게시하지 않는다. 금융 데이터·장수·신선도·중복·일일 최대 2편과 preview → 실제 이미지 검수 → 동일 바이트 publish 절차는 유지한다.

## 실행마다 읽을 파일

본 문서, CONTENT_PLAYBOOK.md, EDITORIAL_GUIDE.md, 해당 시리즈 계약과 settings/workflow, src/editorial_visuals.py, src/editorial_render.py, src/editorial_card.html, src/editorial_card.css, src/build.py, src/editorial_packet.py, src/reviewed_preview.py를 main에서 읽는다. 최근 5편의 원고·실제 이미지와 editorial_review를 비교해 이번 편에서 개선할 점을 고른다.

## 매 장에 다른 이미지를 연결

`summary.visual_story` 각 장에 `visual`을 넣는다. 필수 항목은 path, sha256, alt(8~180자), tone(light/dark), kind(concept/photo)다. `accent`는 선택이며 제목에 실제 존재하는 정확한 부분 문자열이어야 한다. 제목·본문·수치·출처는 원고 JSON과 HTML/CSS로 결정적으로 렌더링한다. 그림 안에 금융 숫자나 본문을 생성해 넣지 않는다.

- concept: 내장 이미지 생성 기능으로 사건을 설명하는 개념 이미지를 제작하고 실제 사용한 prompt(20~2400자)를 기록한다. 실제 현장·공식 제품 사진으로 소개하지 않는다. 카드와 상세 페이지에 AI 개념 이미지임을 표시한다. 별도 유료 AI API나 새 비밀키는 사용하지 않는다.
- photo: 확인된 원본 source_url, credit, license를 기록한다. 회사명과 비슷한 검색어라는 이유로 다른 사물·시설 사진을 연결하지 않는다. 허가된 이용 범위를 확인하지 못하면 사용하지 않는다.
- 한 장에 의미 있는 시각 요소 하나, 장마다 다른 구도와 해시를 쓴다. 같은 그림의 색·크롭만 바꿔 다양성을 가장하지 않는다. 따뜻한 오프화이트·검정·코발트, 큰 두 줄 제목, 충분한 여백을 유지한다.

## 저장과 검증

실제 파일의 SHA256을 계산하고 `automation/visual_assets/<64자리 sha256>.png` 또는 `.jpg`로 신규 추가한다. path와 sha256이 일치해야 한다. 단일 프레임 PNG/JPEG, 두 변 모두 640~4096px, 파일당 12MB 이하만 허용한다. 기존 해시 경로의 바이트를 덮어쓰거나 삭제하지 않는다. 인증정보·외부 실행 파일·임의 URL fetch는 넣지 않는다.

신규 이미지의 추가와 해당 시리즈 inbox 갱신은 반복 제작에 승인된 범위다. 새 이미지를 먼저 main에 추가하고 원격 파일을 다시 읽어 해시를 확인한 뒤 inbox를 현재 SHA 조건으로 제출한다. routine 제작에서 코드·workflow·settings·권한·journal·다른 시리즈 inbox는 변경하지 않는다. 이미지 추가만으로 게시되었다고 보고하지 않는다.

코드는 파일 경로·해시·형식·크기를 확인하고 이미지를 내장해 렌더링한다. 글자가 넘치면 줄이거나 원고를 고치고 새 preview를 만든다. 글씨를 작게 만들어 강제로 넣지 않는다. 이미지·출처·내용·시각 변경은 모두 새 preview 검수 대상이다.

`layout-review-only-do-not-publish`는 코드 배치 시험용이다. 실제 공개에는 제출 커밋에 해당하는 main의 성공한 `*-packet-preview` artifact에서 out/packet.json, out/state.json, 실제 전체 7/5/3장 JPEG를 직접 확인해야 한다. publish 전환은 그 원고의 intent와 reviewed_preview만 바꾸며 기존 workflow가 검수한 JPEG 바이트를 그대로 배포·전송한다.

## 매일 개선하기

최근 편의 약점 1~2개와 이번에 바꾼 위치를 기존 editorial_review에 남긴다. 한 편마다 새로운 주장·장별 시각 요소·마지막 판단이 있는지 확인한다. 조회수 등 실제 분석 자료가 없으면 성과 상승을 주장하지 않는다. 적격 소재가 없으면 게시 횟수를 채우지 않는다.
