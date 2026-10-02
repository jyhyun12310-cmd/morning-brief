# 오후 두시 시장 뉴스 — 클라우드 원고 계약

사용자 승인: 2026-10-02, 기존 @making_money_for_chicken 계정에 한국 장중 시황과 오늘 밤 미국장 관전 포인트를 오후 2시쯤 자동 게시. 별도 유료 AI API를 사용하지 않는다. 오전 미국 주식 한 종목 7장과 별도로 운영한다.

## 매 실행 순서

1. GitHub main의 이 계약, EDITORIAL_GUIDE.md, src/market_packet.py, automation/examples/market-preview.json, market_settings.json, market-packet.yml, publication_log 및 최근 게시물 5개를 읽는다. 로컬 PC 파일에 의존하지 않는다.
2. 한국 기준 월~금, 실제 한국 증시 거래일에만 실행한다. 당일 거래 중임을 확인한 지수 제공자나 당일 시각이 명시된 보도도 개장 증거로 사용할 수 있다. 휴장이면 조용히 건너뛴다. 장중 거래 여부·출처·최신 수치를 검증할 수 없으면 게시하지 않고 이유를 알린다.
3. `kr-market-YYYY-MM-DD-afternoon.json`이 published이면 종료, reserved이면 재게시하지 말고 확인 요청. 오전 us-stock 기록은 별개다.
4. 13:50 이후 코스피·코스닥의 현재값, 이전 종가, 등락률, 각각의 실제 관측 시각을 확인한다. 동일 시각을 우선한다. 장중/시가/전일 종가를 혼동하지 않는다. 검색 결과의 게시시각을 시세 기준시각으로 쓰지 않는다. 현재 두 지수를 확보하지 못하면 꾸며 넣지 않는다. 수급·환율·국채금리·주요 업종은 확인된 것만 쓰고 기준시각과 단위를 붙인다. 숫자끼리 맞지 않거나 신뢰할 출처가 충돌하면 해결 전 게시 금지.
5. 오늘 한국장을 설명하는 핵심 재료 2개, 강약이 갈린 업종/수급 2개, 오늘 밤 미국 일정, 다음에 확인할 조건 3개를 독자적인 짧은 문장으로 작성한다. 공식 공시·정부 통계·거래소·기업 IR과 신뢰할 보도를 확인한다. 타 매체 문장·사진을 복제하지 않는다. 특정 뉴스가 주가를 움직였다고 단정할 근거가 없으면 동시 발생 사실과 해석을 분리한다.
6. 미국 일정은 BLS, BEA, Federal Reserve, 회사 IR 등 발표 주체의 공지를 직접 확인한다. 시간대를 포함한 at을 저장한다. 한국 시간은 렌더러가 변환하며 서머타임을 반영한다. 확인된 일정이 없으면 events=[]로 두며 억지로 채우지 않는다. 결과/예상치/이전치를 혼용하지 않는다. 상승·수익 보장, 매수 유도, 공포성 제목을 쓰지 않는다.
7. 아래 형식으로 `automation/market_inbox/latest.json`만 갱신한다. 오전 inbox를 절대 덮어쓰지 않는다. `intent=publish`, `is_test=false`. 예시의 날짜·숫자·문장을 그대로 재사용하지 않는다. 실제 확인한 내용으로 모든 시각/근거/수치/일정을 교체한다.
8. 가능하면 원고를 내려받아 검증한 뒤 커밋한다. push로 market-packet 워크플로가 실행된다. 미실행이면 해당 workflow만 live=true로 수동 실행한다. 테스트 실패·렌더링 잘림은 원고 길이 등을 수정해 재실행할 수 있으나 reserved/published 기록이 생겼으면 재게시 금지. 설정, 워크플로, 게시 잠금, 권한, 비밀키를 바꾸지 않는다.
9. workflow 성공과 게시 기록 published, API 확인 image_count=5 및 permalink를 확인하고 실제 카드 이미지를 열어 살핀다. 완료 후 사용자에게 링크와 `개선점 → 이유 → 적용 방식` 한 줄을 알린다. 검증되지 않은 완료·성과를 주장하지 않는다. 휴장/중복/변화 없음은 조용히 종료한다. 실패나 조치 필요는 간단히 알린다.

## JSON 형식

- schema_version=1, kind=market_brief, intent=preview/publish, is_test=boolean.
- created_at, snapshot_at: ISO8601 시각과 시간대. publication_date_kst=YYYY-MM-DD.
- kr_session={date, status:'open', source_id, evidence}. 출처로 당일 실제 개장을 확인.
- sources: 2개 이상, 각 {id,title,url,as_of,retrieved_at}. 비밀키 없는 공개 HTTPS URL. as_of는 자료 기준시점, retrieved_at은 확인시각.
- quotes: KOSPI,KOSDAQ 각 1개. {id,name,value,previous_close,change_pct,basis:'intraday',as_of,source_id}. 등락률은 이전 종가 대비 퍼센트. 공개 게시 시 두 관측값 모두 35분 이내이고 기준일이 오늘이어야 한다.
- events: 0~3개 {title,at,note,source_id}; snapshot 이후 36시간 이내 확인된 일정. at에는 -04:00/-05:00 등 실제 시간대를 정확하게 기록한다.
- summary.instagram_caption: 20~400자, 목표 2문장+2~3개 해시태그. 전체 수치/출처를 나열하지 않는다. 상세 출처 링크는 자동 추가된다.
- summary.visual_story: 정확히 5개, layout 순서 headline/drivers/sectors/calendar/watch. 각 {layout,title,body,source_ids,items}. title 5~38자(두 줄 권장), body 15~110자(40~65자 목표). drivers/sectors/watch에는 items 2~3개, 각 {label(2~25자),text(5~85자),type(fact/analysis/watch),source_ids}. 근거 ID 필수. 카드마다 새 정보/관점을 하나씩 제공한다.
- summary.editorial_review: {improvement,reason,application,avoided_repetition}; 사용자 결과 보고용이며 Instagram 설명에 길게 넣지 않는다.
- 실제 게시 시각 13:45~14:40 KST, 원고와 시세 35분 이내. 작업은 13:50 시작하여 약14:00 게시를 목표로 한다. 지연되면 오래된 자료를 강행하지 않는다.

## 카드와 운영

1080×1350 JPEG 5장. 표지 지수판, 뉴스 행, 업종 비교칸, 시간표, 관전 목록을 각각 사용한다. 같은 사진 크롭 반복은 하지 않는다. 수치 그래프는 데이터가 있을 때만 쓰고 장식용 가짜 가격 곡선을 넣지 않는다. 오전과 같은 Gmarket Sans/Pretendard, 짙은 녹색·크림·코럴 계열을 유지한다. 유료 AI API·로컬 PC·브라우저 로그인 세션에 의존하지 않는다. 기존 GitHub/Instagram 연결만 이용한다.
