# ChatGPT → GitHub 카드뉴스 인계 규약

## 현재 상태 — 2026-09-30

수정 코드는 `chatgpt/no-paid-ai-20260930` 작업 브랜치에 있습니다. main 운영 전환은 하지 않았습니다. 일반 파일 읽기·쓰기는 확인했습니다. 기존 GitHub Pages 실행 36645999107의 재실행은 성공했지만, 신규 워크플로 파일 쓰기는 ChatGPT 보안 검토에서 차단되어 설치되지 않았습니다. 차단을 우회하지 않았습니다.

로컬의 모의 테스트 40개가 통과했습니다. 실제 사진 다운로드, 기존 HTML/Playwright를 이용한 7장 렌더링, 신규 GitHub 워크플로 실행, 실제 Instagram 계정 게시까지 검증한 것은 아닙니다. 테스트 데이터는 가상 데이터입니다. `allow_publish=false`가 기본값입니다.

## 처리 경로

ChatGPT가 웹에서 확인한 원고와 시세·출처를 **하나의 JSON**으로 작성 → `automation/inbox/latest.json`에 커밋 → 승인 후 설치할 `card-packet.yml`의 파일 push 트리거 → 입력 검증 → 기존 `visual_assets.prepare_visual_assets` → 기존 `render.render_cards` 및 상세 페이지 → 오프라인 게시 검증 → 운영 허용 시 GitHub Pages 배포 → 공개 이미지 바이트 검증 → 영구 중복 방지 기록 → 기존 `publish_instagram.publish_carousel`.

`src/build.py`, `src/summarize.py`의 새 실행 경로는 Claude/OpenAI 등 유료 AI API를 호출하지 않습니다. 원고가 없으면 건너뛰며 유료 AI 또는 새 시세 조회로 대체하지 않습니다. 사진 취득은 기존 기능이며, 사진 준비 과정에서 시세·출처 입력을 바꾸면 실패합니다. 다른 기존 워크플로까지 모두 전환한 상태는 아닙니다. Kakao는 이번 Instagram 전용 경로에서 보내지 않습니다.

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

## ChatGPT 예약 작업 원칙

한국 시간 화–토 아침에 최근 완료된 미국 거래일을 확인합니다. 새 거래가 없거나 확인 가능한 근거가 부족하면 건너뜁니다. 큰 가격 변동만을 자극적으로 단정하지 말고 뉴스 발생일과 기사 발행일을 구분합니다. 회사 IR·SEC·거래소 등 원문을 우선합니다. 수치뿐 아니라 자연어 주장도 원문에 대조하고 사실, 해석, 불확실성을 구분합니다.

연결된 GitHub로 main의 설정과 워크플로, 최근 실행 기록을 먼저 읽습니다. main에 이 규약이 없거나 신규 워크플로 설치와 성공한 실제 렌더링 preview를 확인하지 못하면 작업 브랜치 `chatgpt/no-paid-ai-20260930`에 **preview 원고만** 작성합니다. main 전환 후에도 allow_publish=false이면 preview만 작성합니다. 작업이 보안 승인에서 멈추면 파일 전달 성공 또는 자동 게시 완료라고 보고하지 않습니다. 워크플로·설정·보안 권한을 예약 작업이 임의로 변경하지 않습니다.

운영 모드에서는 allow_publish=true와 preview_verified_run_id에 해당하는 성공한 신규 워크플로 실행을 확인해야 합니다. 기존 Pages 성공 기록은 렌더링 preview 증거가 아닙니다. `automation/publication_log/us-stock-YYYY-MM-DD.json`이 있으면 해당 미국 거래일을 다시 게시하지 않습니다. latest.json에 같은 거래일이 이미 전달되어 있으면 덮어써 새 게시를 만들지 않고 현재 상태를 보고합니다. 전송할 때 기존 파일 SHA를 읽고 내용 쓰기 후 다시 읽어 일치 여부를 확인합니다. 저장소에는 비밀키를 저장하지 않습니다.

## 중복 및 오래된 데이터 방지

거래일을 키로 삼아 종목·원고를 바꿔도 같은 거래일 게시가 중복되지 않도록 합니다. GitHub Contents API의 생성 충돌과 SHA 비교로 게시 전에 reserved 기록을 영구 저장합니다. 성공하면 published/media_id로 갱신합니다. 타임아웃·프로세스 중단·결과 저장 실패는 reserved 상태를 남기며 자동 재시도하지 않습니다. 이는 중복 회피를 위해 누락 가능성을 감수하는 보수적 설계입니다. 수동으로 기록을 지우면 보호가 약화되므로 실제 Instagram을 먼저 확인해야 합니다.

운영 원고는 생성 후 24시간, 시장 종료 후 36시간 이내이며 한국 날짜가 오늘이어야 합니다. JSON과 캡션의 일치, JPEG 7장 및 1080×1350 규격, 이미지 해시를 검사합니다. 파일명에는 원고 해시가 들어가고, Pages에서 내려받은 JPEG 바이트의 해시가 만들어진 이미지와 정확히 같을 때만 게시를 시도합니다. 가격 문장 전체의 의미를 검증하는 금융 사실 검증기는 아니므로 원고 작성 단계의 출처 확인이 필수입니다.

## 소유자 승인 후 설치·전환

1. 기존 유료 AI 기반 `brief.yml` 및 다른 예약/수동 워크플로의 호출 경로를 점검하고 기존 자동 게시 스케줄을 비활성화합니다. 이 PR은 main을 자동 변경하거나 기존 작업을 비활성화하지 않았습니다.
2. 변경 PR을 검토·병합하고, 대화 첨부 패치의 `.github/workflows/card-packet.yml`을 소유자가 검토 후 같은 경로에 설치합니다. 이 파일은 저장소에 설치되지 않았습니다. Settings → Pages → Source를 GitHub Actions로 설정합니다. Pages 주소가 다른 경우 YAML의 PAGES_BASE_URL을 실제 공개 주소에 맞춥니다. 현재 게시 검증은 github.io 호스트를 사용합니다.
3. 원고를 intent=preview로 전달하고 `Card packet — no paid AI`를 live=false로 실행합니다. artifact에서 실제 사진·한글·7장 구성·잘림 여부를 직접 확인합니다. 원본 사진이 없거나 라이선스가 확인되지 않으면 실패한 상태로 둡니다.
4. 성공한 실제 렌더링 실행 ID를 settings.preview_verified_run_id에 기록하고 allow_publish=true로 변경한 뒤, 새 거래일의 최신 원고부터 운영 전환합니다. 예전 가상 테스트 원고나 오래된 원고는 게시하지 않습니다.

운영에 필요한 기존 GitHub secrets는 IG_USER_ID, IG_ACCESS_TOKEN입니다. 게시 잠금용 GH_TOKEN은 워크플로의 github.token을 사용하고 contents:write가 필요합니다. 토큰 갱신 보존은 기존 GH_PAT 권한이 있는 경우에만 수행합니다. GH_PAT이 없으면 장기 토큰 갱신값이 저장되지 않아 추후 수동 갱신이 필요할 수 있습니다. 비밀값은 대화나 원고 파일에 붙여 넣지 않습니다.

새 워크플로는 별도 AI SDK를 설치하지 않으며 GitHub 호스팅 실행 자원과 기존 Meta 게시 API를 사용합니다. 별도 AI 사용료가 없다는 뜻이지 모든 서비스의 계정 한도·정책 또는 향후 비용까지 보장한다는 뜻은 아닙니다.

## 테스트

`python -m pip install pytest Pillow requests` 후 `PYTHONPATH=src python -m pytest tests/test_packet_pipeline.py -q`.

검사 항목: 기준 가격 불일치, 출처/근거 ID 누락, 비정상 숫자, 원고 7장 미완성, 시세 변조, 날짜·신선도 제한, 출처 연결 차트 수치, 상태·캡션 변조, 가상 JPEG 7장과 오프라인 dry-run, 생성 전/후 중복 기록, 응답 타임아웃, 기록 갱신 실패, 예약 경쟁 충돌, 빈 SHA 확인 응답, 오래된 HTTP 200 이미지, 잘못된 이미지 크기.

40개 성공은 모의 회귀 테스트 결과이며 실제 Instagram 권한·토큰·게시 성공 또는 새 워크플로 성공의 증거가 아닙니다.
