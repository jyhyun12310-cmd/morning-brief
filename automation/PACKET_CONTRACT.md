# ChatGPT → GitHub 카드뉴스 인계 규약

## 운영 상태 — 2026-10-01

사용자가 JBL 7장 실제 공개 게시와 이후 원고 작성부터 게시까지 자동 실행을 승인했습니다. main의 `card-packet.yml`이 운영 경로입니다. `allow_publish=true`, 최초 실제 preview 실행은 36860437531이며 운영 실행 36861877774도 성공했습니다. Instagram에서 캐러셀 7장을 다시 읽어 검증했습니다.

- 게시 계정: @making_money_for_chicken
- 최초 실제 게시: https://www.instagram.com/p/Dd86Xjbm6cq/
- 게시 ID: 18119582245819862
- 영구 게시 기록: automation/publication_log/us-stock-2026-09-30.json
- 실제 게시 시각: 2026-10-01 21:29 KST
- 검사: 모의 회귀 테스트 47개, 실제 렌더링, Pages 이미지 해시, Instagram 게시 및 7장 확인 통과
- 기존 brief.yml과 유료 AI 호출 issue.yml의 예약 및 작업은 중지되었습니다.

## 처리 경로

예약 작업이 웹 원문과 정규장 시세를 검증하여 한국어 원고를 하나의 JSON으로 작성 → main의 automation/inbox/latest.json 업데이트 → card-packet 자동 실행 → 입력 검사 → 라이선스 확인 사진 및 7장 렌더링 → 오프라인 게시 검사 → GitHub Pages 배포 → 공개 이미지 해시 검사 → 영구 중복 방지 예약 → Instagram 캐러셀 게시 → 실제 게시물의 주소와 7장 확인.

별도 유료 AI API는 사용하지 않습니다. GitHub가 원고를 받은 뒤 시세·원고를 새로 생성하거나 변경하지 않습니다. 원고가 없거나 부정확하면 중단합니다. Kakao는 이 Instagram 전용 작업에서 발송하지 않습니다.

## JSON 구조

최상위 필드:
- `schema_version`: 1
- `intent`: `preview` 또는 `publish`
- `is_test`: boolean. 가상 데이터는 반드시 true이며 운영 게시 금지.
- `created_at`: 시간대가 명시된 ISO 시각
- `publication_date_kst`: created_at을 한국 시간으로 환산한 날짜, YYYY-MM-DD
- `market`: 아래 필드가 모두 있어야 함
- `sources`: 원문 출처 목록
- `metrics`: 차트용 출처 연결 수치 목록. 차트가 없으면 빈 배열 가능.
- `summary`: 아래 원고 구조

market:
`ticker`, `name`, `session_date`, `session_close_at`, `price_basis="regular_close"`, `currency="USD"`, `close`, `previous_close`, `change_pct`, `source_id`.

정규장 종가와 바로 전 거래일 종가의 **동일한 조정 기준**을 사용합니다. 시간외 가격과 혼합하지 않습니다. session_date는 미국 뉴욕 시간의 거래일이고 session_close_at은 해당 거래의 실제 종료 시각입니다. 날짜, 휴장, 조기 폐장 여부는 원고 작성자가 현재 공식 거래소 자료로 확인해야 합니다. 단순 요일 검사만으로 휴장 여부를 입증하지 않습니다. 등락률은 `(close/previous_close-1)*100`; 허용 오차는 0.02%p입니다. 종가와 전일 종가는 양수이며 숫자 문자열, NaN, boolean을 사용할 수 없습니다.

sources 각 항목:
`id`, `title`, `url`, `as_of`, `retrieved_at`.
공개 HTTPS 원문 URL, 실제 자료 기준일과 확인 시각을 남깁니다. 토큰·비밀번호·개인 접속 URL을 넣지 않습니다. JSON 출처 목록이 있다는 사실만으로 원문이 주장을 뒷받침하는 것은 아니므로 작성자가 직접 대조해야 합니다.

metrics 각 항목:
`id`, `value`, `unit`, `period`, `basis`, `source_id`.
서로 다른 GAAP/비GAAP, 연결/별도, 단위를 섞어 차트로 만들지 않습니다.

summary 필드:
- `market_basis`: market 중 **ticker, session_date, price_basis, currency, close, previous_close, change_pct**의 7개 키와 값을 그대로 복제한 객체. 추가 키를 넣지 않습니다.
- `central_question`: 12–70자
- `thesis`: 40–220자
- `edition`: 1–30자
- `instagram_caption`: 500–2,200자. 출처 URL을 포함해 최종 2,200자 이내로 편집해야 하며 절삭하지 않습니다.
- `sources`: 최상위 sources와 같은 id/title/url/as_of. 사용한 시세 및 차트 출처를 모두 포함합니다.
- `evidence_notes`: 4개 이상. 항목마다 `id`, `claim`(15–450자), `source_ids`(유효한 출처 ID 배열).
- `visual_story`: 정확히 7개 카드.

카드 순서와 layout:
1. `cover`: 종목, 오늘의 변화, 호기심을 자극하는 중심 질문
2. `photo`: 확인된 사건과 발생일, 무엇이 새로 바뀌었는가
3. `annotated`: 제품·사업 구조와 사건의 연결
4. `comparison`: 같은 기준의 검증된 숫자 또는 근거 비교
5. `explain`: 주가 반응과 사업 성과의 구분, 평가 근거와 한계
6. `conditions`: 기대가 성립하는 조건과 반론·위험
7. `closing`: 첫 질문의 답, 다음에 확인할 지표와 일정

모든 카드에 `layout`, `title`, `body`, `takeaway`, `bridge`, `evidence_ids`, `labels`를 작성합니다. 제목은 8–55자, 최대 2줄; body는 표지 40–85자, 나머지 80–170자; takeaway 25–70자; bridge 18–45자입니다. 제목과 본문은 7장 모두 달라야 합니다. labels는 최대 3개이며 각 `label` 1–24자, `text` 3–70자입니다. 2·3·5·7장 및 차트 없는 4장은 labels가 2개 이상 필요합니다.

6장에는 `origin`(5–65자), `branches` 정확히 2개가 추가로 필요합니다. 각 branch는 `label`(3–24자), `text`(12–65자), `check`(10–65자)를 가집니다.

4장의 선택적 `chart`: `source`(3–120자), `note`(5–100자), `unit`(1–40자), `rows` 2–5개. 각 row는 `metric_id`, 숫자 `value`, `label`(1–34자), `display`(1–32자)를 가집니다. row의 value와 chart의 unit은 연결한 metric과 정확히 같아야 합니다. 근거 없는 숫자를 넣는 대신 차트를 생략하고 비교 설명 labels를 사용합니다.

가상 예시는 `tests/test_packet_pipeline.py`의 `sample_packet()`에서 생성할 수 있습니다. 예시는 실제 종목·출처·투자 자료가 아니며 게시하면 안 됩니다.

## 예약 운영

ChatGPT Work 클라우드의 활성 예약 `미국주식 7장 클라우드 자동게시`(ID `6abe558092a081918e9ecc4fb326252d`)가 Asia/Seoul 기준 화–토 오전 8시 30분에 시작하도록 저장되었습니다. 첫 일정은 2026-10-02 08:30이며 서버 next_run_time은 저장 확인 당시 null이므로 아직 첫 예약 실행을 관찰한 상태는 아닙니다. 연결 대화 ID는 `6abe54a7-2420-83e8-b396-9bda1f7327f5`입니다. 원고 작성은 클라우드의 웹 검색·GitHub 연결로 실행하고, 렌더링·배포·게시는 GitHub 호스팅 환경에서 실행합니다. 사용자 PC 파일·전원·Codex 앱에 의존하지 않습니다. 기존 로컬 예약 ID 7은 중지했습니다. 별도 유료 AI API는 사용하지 않지만 기존 서비스 이용 한도는 적용됩니다.

2026-10-01 클라우드 설정에서 저장소·규약·검증코드·설정·최신 원고·영구 기록·성공 실행 로그 읽기와 이미 게시한 거래일의 중복 건너뛰기를 확인했습니다. 새 원고 작성은 `automation/EDITORIAL_GUIDE.md`를 함께 따릅니다. 디자인 예시는 운영 입력이 아니며, workflow_dispatch의 design_preview=true로 게시 없이 7장을 확인할 수 있습니다. 예시 경로는 live 게시 게이트에서 제외됩니다.

예약 실행은 최신 main의 규약·설정·코드 및 실행 기록을 먼저 확인합니다. allow_publish가 false이면 실제 게시하지 않습니다. 워크플로·설정·권한·비밀키를 예약 실행이 변경하지 않습니다. 공개 게시 권한은 사용자가 이미 부여했으므로 매번 재승인을 요청하지 않습니다.

최신 완료된 미국 거래일과 공식 휴장·조기폐장 일정을 확인합니다. 새 거래가 없거나 이미 published이면 건너뜁니다. reserved/불명확한 기록은 자동 삭제하거나 재시도하지 않습니다. 같은 거래일 원고가 처리 중이면 덮어쓰지 않습니다. 입력만의 문제이며 아직 게시를 시도하지 않았다고 확인된 실패는 내용을 교정할 수 있습니다.

회사 IR·SEC·거래소 원문을 우선하고, 사실·해석·불확실성을 나눕니다. 뉴스 발생일과 발행일을 구분하며 숫자와 자연어 주장을 모두 원문에 대조합니다. 확인 가능한 근거가 부족하면 종목을 바꾸거나 건너뜁니다.

운영 JSON은 is_test=false, intent=publish로 전송합니다. 기존 파일 SHA를 읽고 갱신 후 다시 읽어 일치를 확인합니다. workflow 성공 외에도 영구 기록의 published/media_id 및 로그의 실제 7장·permalink 확인을 확인해야 게시 완료로 보고합니다. 완료·실패·사용자 조치가 필요한 경우에 알리고, 휴장이나 변화 없는 상태는 조용히 종료합니다.

## 중복 및 오래된 데이터 방지

거래일을 키로 삼아 종목·원고를 바꿔도 같은 거래일 게시가 중복되지 않도록 합니다. GitHub Contents API의 생성 충돌과 SHA 비교로 게시 전에 reserved 기록을 영구 저장합니다. 성공하면 published/media_id로 갱신합니다. 타임아웃·프로세스 중단·결과 저장 실패는 reserved 상태를 남기며 자동 재시도하지 않습니다. 이는 중복 회피를 위해 누락 가능성을 감수하는 보수적 설계입니다. 수동으로 기록을 지우면 보호가 약화되므로 실제 Instagram을 먼저 확인해야 합니다.

운영 원고는 생성 후 24시간, 시장 종료 후 36시간 이내이며 한국 날짜가 오늘이어야 합니다. JSON과 캡션의 일치, JPEG 7장 및 1080×1350 규격, 이미지 해시를 검사합니다. 파일명에는 원고 해시가 들어가고, Pages에서 내려받은 JPEG 바이트의 해시가 만들어진 이미지와 정확히 같을 때만 게시를 시도합니다. 가격 문장 전체의 의미를 검증하는 금융 사실 검증기는 아니므로 원고 작성 단계의 출처 확인이 필수입니다.

## 연결 및 검증

기존 IG_USER_ID 및 IG_ACCESS_TOKEN 비밀값을 사용합니다. GH_TOKEN은 github.token을 사용해 영구 게시 기록을 저장하며, 기존 GH_PAT으로 갱신된 Instagram 토큰을 시크릿에 되씁니다. 2026-10-01 운영 실행에서 토큰 갱신과 저장도 성공했습니다. 비밀값을 원고·로그·아티팩트에 노출하지 않습니다. 인증이 해제되거나 만료되면 사용자 재연결이 필요할 수 있습니다.

GitHub Pages Source는 GitHub Actions이며 PAGES_BASE_URL은 https://jyhyun12310-cmd.github.io/morning-brief 입니다. 게시 후 검증 결과는 card-publication-result 아티팩트와 실행 로그에 남습니다. 이미 게시한 거래일은 검증 조회만 재시도할 수 있으며 게시 자체를 재실행하지 않습니다.

테스트: `PYTHONPATH=src python -m pytest tests/test_packet_pipeline.py -q`. 모의 테스트 성공만으로 실제 계정 게시 성공을 주장하지 않으며 실제 실행과 Instagram 응답을 별도로 확인합니다.
