# 시장 핵심 속보 — 3장 자동 게시

2026-10-02 사용자 요청: 핵심 내용을 다루고 주식시장에 영향을 줄 뉴스가 나오면 신속하게 반영하여 Instagram @making_money_for_chicken에 게시한다. 기존 오전 7장·오후 5장 예약은 유지한다. 별도 유료 AI API 없이 클라우드에서 실행한다.

## 감시와 선별

현재 활성 예약은 주말 포함 24시간 매시간 정각(Asia/Seoul)이다. 2026-10-02 등록 시 연결된 hosted 예약 도구의 최소 간격이 1시간이어서 요청한 15분 간격은 지원되지 않았다. Automation ID: 6abf0bb710f08191aa63879d7281aa37. 확인된 주요 소식은 원문 검증과 3장 제작을 마치는 대로 게시한다. 초 단위 실시간 감지나 발생 즉시 게시를 보장하지 않는다. 매 확인 후 중요한 새 소식이 없으면 아무 게시/알림/파일 변경 없이 종료한다. 검색 색인·공식 소스 갱신·검증·렌더링·플랫폼 지연이 추가될 수 있다. 새로운 일정이나 작업을 실행마다 만들지 않는다. 같은 감시를 여러 예약으로 쪼개 도구의 주기 제한을 우회하지 않는다.

매 실행 시 main의 본 계약, EDITORIAL_GUIDE.md, src/breaking_packet.py, breaking_settings.json, examples/breaking-preview.json, breaking_inbox/latest.json, breaking-packet.yml, 최근 publication_log 및 docs 상세 원고를 읽는다. 최신 공식 발표와 이전 확인 이후 새로 발견한 미게시 주요 발표를 이전 게시와 대조한다. 최근 3시간은 우선 검색 범위일 뿐 게시 제한이 아니다. 사건·공식 발표일과 공개된 시각을 확인한다. 2026-10-04 사용자 승인에 따라 3시간 경과나 정확한 시각 미공개만으로 게시를 보류하지 않는다. 시각을 추정하거나 확인 시각을 발표 시각으로 대체하지 않는다. 검색 결과 요약만으로 게시하지 않는다. 원문을 직접 읽는다.

우선순위: 중앙은행 금리 결정과 유의미한 정책 변화, 물가·고용 등 주요 경제지표, 시장 전반에 영향을 줄 정책/관세/규제, 확인된 지정학적 사태, 시스템 금융 위험, 주요 지수·업종에 파급력이 있는 대형 기업 실적/전망. 자잘한 개별 종목 뉴스, 재탕 해설, 단순 전망 기사, 유명인의 추측, 미확인 소문은 제외한다. '영향이 있을 수도 있다'는 문구만 붙이지 말고 어느 시장·업종에 어떤 경로로 중요한지 구체적으로 설명할 수 있을 때만 게시한다. 내용이 부족하면 억지로 3장을 채우지 않는다.

연준/BLS/BEA/미 재무부/한국은행/국가 통계기관/정부 부처/KRX/DART/SEC/기업 IR 등 발표 주체의 원문을 우선한다. 공식 원문이 확인되지 않은 사건은 다른 매체가 속보로 보도해도 우선 보류한다. 지정학적 사태는 정부·공식기관의 확인과 독립적인 신뢰할 보도를 대조한다. 수치·사망자·피해·행위 주체를 추정하지 않는다. 단순 공식 일정 예고는 속보가 아니다. 수익 보장·근거 없는 상승/하락 단정·매매 유도 금지.

## 작성과 중복 방지

확인한 주요 발표 1건을 headline/impact/watch 3장으로 작성한다. 1장은 확정된 새 사실, 2장은 주식시장에 전달되는 경로, 3장은 다음 확인 지표/조건이다. 제목은 짧은 두 줄, 본문은 2문장 이내, 각 항목은 한 가지 메시지. fact/analysis/watch를 구분한다. 시장 가격을 읽지 못했으면 실제 반응이라고 쓰지 않는다. 예상치·직전치·실제치를 섞지 않고 %와 %포인트, 발표 시각과 대상 기간을 구분한다. 캡션은 2문장+2~3개 해시태그만 쓰며 출처 링크는 자동 추가된다.

event.issuer와 release_id는 같은 공식 발표의 불변 식별자다. 예: us-fed / 2026-09-16-fomc-decision, us-bls / 2026-09-employment, us-bls / 2026-09-cpi. 기업 실적은 ticker·회계연도·분기·earnings를 포함한다. 같은 사건의 매체/제목/작성일을 바꿔 ID를 새로 만들지 않는다. `publication_key(packet)`은 두 ID의 SHA256 앞 24자로 `market-news-...`를 만들며 날짜가 달라도 같은 키다. 해당 journal이 published면 종료, reserved면 절대 재게시하지 않고 확인 필요를 알린다. 오전/오후 원고에 이미 동일 사건과 결론이 충분히 담겨 있으면 별도 속보를 반복하지 않는다. 기존 기사를 새 기사처럼 올리지 않는다.

실질적으로 새로운 공식 결정·정정·수치가 나온 경우에만 별도 후속 발표로 취급한다. 표현 변화만으로 새 release_id를 쓰지 않는다. 같은 날 주요 뉴스 여러 건은 중요도 순으로 각각 검토하되 한 게시물엔 한 사건만 담는다. 과도한 게시 횟수를 목표로 삼지 않는다.

## JSON과 실제 게시

- schema_version=1, kind=breaking_news, intent=publish, is_test=false, created_at/snapshot_at=timezone 포함 ISO8601, publication_date_kst=작성일 한국 날짜.
- event: issuer/release_id(영문 소문자·숫자·하이픈 3~80자), occurred_at(실제 공식 발표 시각; 아래 날짜 전용 규격에서는 생략), category(rates/inflation/employment/policy/geopolitics/systemic/major_earnings), status=confirmed, market_scope(broad_market/major_sector/systemic), primary_source_id, materiality(시장에 중요한 구체적 이유 25~300자).
- sources: 각 {id,kind(primary/secondary),title,url,as_of,retrieved_at}. 시각을 아는 primary source에는 published_at을 넣으며 event.occurred_at과 같아야 한다. 시각 미공개라면 event.time_precision=date, occurred_date=YYYY-MM-DD, source_timezone=공식 발표 주체의 IANA 시간대를 사용하며 occurred_at은 생략한다. primary source에는 같은 날짜의 published_date를 넣고 published_at은 생략한다. 날짜는 원문 그대로 표시하고 KST 시각으로 변환하거나 자정으로 채우지 않는다. 공개 HTTPS 원문만, 비밀키나 비공개 자료 금지.
- summary.instagram_caption: 20~400자, summary.visual_story 정확히 3장. layout=headline/impact/watch. 각 {title(5~38자),body(15~100자),source_ids,items}. items 2~3개, 각 {label(2~22자),text(5~80자),type(fact/analysis/watch),source_ids}. 모든 내용은 원문에 근거하거나 해석으로 표시.
- summary.editorial_review에 improvement/reason/application을 짧게 넣어 게시 후 사용자에게 한 줄 보고.
- 공개 게시 때 원고와 확인 시각은 35분 이내. 사건 발생 후 3시간 제한은 없다. 미래 발표·원문과 날짜 불일치·자료 확인 이전에 아직 발표되지 않은 사건은 차단한다. 새벽·주말이라도 세계 시장에 중요한 확인된 사건은 허용한다. 오래된 예시는 테스트용이며 절대 publish로 바꾸지 않는다.

새 원고는 `automation/breaking_inbox/latest.json`만 수정한다. 오전/오후 inbox, 설정, 코드, 워크플로, 권한, 비밀키, journal은 편집하지 않는다. 현재 파일 SHA와 관련 journal, Actions 진행 상태를 제출 직전 재조회한다. 처리 중 원고를 덮어쓰지 않는다. 동시 진행이 있으면 완료를 확인한 뒤 제출하거나 다음 점검으로 넘긴다. push가 breaking-packet.yml을 실행한다. 실행이 없음을 확인한 경우에만 해당 workflow live=true로 실행한다.

원고 검증·3장 렌더링·실제 공개 이미지 hash검증·영구 journal 예약·Instagram 전송·image_count=3과 permalink 확인을 순서대로 수행한다. 전송 전 명확한 원고 오류만 고친다. reserved/published 또는 전송 결과 불명확 상태에서는 재실행·잠금 삭제·ID 변경으로 중복 전송하지 않는다. 오류나 권한 차단을 우회하지 않고 알린다. 사용자에게 게시 링크, 핵심 변화 1문장, 개선 적용 1줄만 보고한다. 새 소식 없음/중복은 조용히 종료한다. 이 채팅 결과만 사용하며 외부 메시지를 별도로 보내지 않는다.


