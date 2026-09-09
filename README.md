# 조간 시황 브리핑 자동화

매일 아침 7시(KST), 전일 미국장 핵심 이슈와 금일 한국장 방향을 **카드뉴스 5장**으로 만들어
**카카오톡 나에게 보내기**(5개 메시지)와 **인스타그램**(캐러셀 게시물 1개)에 자동 발송합니다.

```
07:00 KST  →  데이터 수집  →  Claude 요약  →  카드 5장 JPEG 생성
                                                   ↓
                              GitHub Pages 업로드 → 카톡(5개) + 인스타(캐러셀 1개) 발송
```

5장 구성: **①표지(오늘 코스피 방향) ②미국 지수 마감 ③미국장 핵심 이슈 ④국내증시 체크(코스피·코스닥·수급·특징주) ⑤오늘의 체크포인트**

---

## 설정 순서

전부 처음이면 40분쯤 걸립니다. 순서대로만 하시면 됩니다.

### 1. 저장소 만들기

이 폴더를 GitHub에 **공개(Public) 저장소**로 올립니다.

> 공개로 만드는 이유: 인스타그램 API는 파일 업로드를 지원하지 않아서 이미지가 공개
> HTTPS 주소에 있어야 하는데, 비공개 저장소에서 GitHub Pages를 쓰려면 유료 플랜이
> 필요합니다. API 키는 저장소가 아니라 GitHub Secrets에 암호화되어 들어가므로
> 공개 저장소여도 노출되지 않습니다.

### 2. GitHub Pages 켜기

`Settings → Pages → Source: Deploy from a branch → Branch: main / docs` → Save

주소는 `https://<아이디>.github.io/<저장소이름>` 이 됩니다.

### 3. Anthropic API 키 발급

[console.anthropic.com](https://console.anthropic.com) → API Keys → 새 키 생성.
브리핑 1건당 비용은 몇 십 원 수준입니다.

### 4. 카카오 설정

[developers.kakao.com](https://developers.kakao.com)

1. 애플리케이션 추가 → **앱 키**에서 REST API 키 복사
2. **카카오 로그인** 활성화 ON
3. **카카오 로그인 → Redirect URI** 에 `https://example.com/oauth` 등록
4. **동의항목** 에서 `카카오톡 메시지 전송(talk_message)` 을 선택 동의로 설정

그다음 내 PC에서:

```bash
pip install requests
python scripts/kakao_token.py
```

안내대로 브라우저에서 동의하고 주소창의 `code` 값을 붙여넣으면
`KAKAO_REFRESH_TOKEN` 이 출력됩니다.

### 5. 인스타 설정

먼저 **인스타 계정을 프로페셔널(비즈니스 또는 크리에이터)로 전환**하세요.
개인 계정은 API 접근이 아예 불가능합니다.

[developers.facebook.com](https://developers.facebook.com)

1. 앱 만들기 → **Instagram** 제품 추가
2. Instagram → API 설정 → 비즈니스 로그인 설정
   - OAuth 리디렉션 URL: `https://example.com/oauth`
   - 권한: `instagram_business_basic`, `instagram_business_content_publish`
3. **앱 역할 → 역할** 에서 내 인스타 계정을 **Instagram Tester** 로 추가
4. 인스타 앱 → 설정 → 웹사이트 권한 → 테스터 초대 에서 **수락**

3~4번을 하면 앱 심사 없이 개발 모드로 내 계정에 게시할 수 있습니다.
심사는 남의 계정에 올릴 때만 필요합니다.

```bash
python scripts/instagram_token.py
```

`IG_USER_ID` 와 `IG_ACCESS_TOKEN` 이 출력됩니다.

### 6. GitHub PAT 만들기

갱신된 토큰을 시크릿에 되쓰려면 필요합니다.

`Settings → Developer settings → Personal access tokens → Fine-grained tokens`
→ 이 저장소만 선택 → 권한에서 **Secrets: Read and write** 체크 → 생성

### 7. 시크릿 등록

저장소의 `Settings → Secrets and variables → Actions → New repository secret`

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | 3단계 |
| `KAKAO_REST_API_KEY` | 4단계 |
| `KAKAO_CLIENT_SECRET` | 4단계 (안 쓰면 생략) |
| `KAKAO_REFRESH_TOKEN` | 4단계 |
| `IG_USER_ID` | 5단계 |
| `IG_ACCESS_TOKEN` | 5단계 |
| `GH_PAT` | 6단계 |

### 8. 실행

`Actions → 조간 시황 브리핑 → Run workflow` 로 수동 실행해 보세요.
성공하면 이후로는 매일 아침 7시에 자동으로 돕니다.

---

## 내 PC에서 미리 보기

발송 없이 카드만 만들어 확인할 수 있습니다.

```bash
pip install -r requirements.txt
playwright install chromium

export ANTHROPIC_API_KEY=sk-ant-...
PYTHONPATH=src python src/build.py --force

open docs/cards/$(date +%Y-%m-%d).jpg
```

`--force` 는 휴장일 체크를 건너뜁니다.

---

## 바꾸고 싶을 때

| 하고 싶은 것 | 고칠 파일 |
|---|---|
| 지수·종목·뉴스 소스 변경 | `src/config.py` |
| 카드 디자인·색·레이아웃 | `src/card.html` (`card_num` 1~5 블록) |
| 요약 톤이나 항목 구성 | `src/summarize.py` 의 `SYSTEM` |
| 발송 시각 | `.github/workflows/brief.yml` 의 `cron` |
| 카드 장수 조정 | `src/render.py` 의 `CARD_COUNT`, `card.html` 에 새 `card_num` 블록 추가 (인스타 캐러셀은 2~10장까지 가능) |

카드는 상승 빨강 / 하락 파랑의 한국식 표기를 씁니다.
`card.html` 의 `--up`, `--down` 을 바꾸면 미국식으로 뒤집을 수 있습니다.

---

## 알아둘 것

**발송 시각이 조금씩 밀립니다.** GitHub Actions의 cron은 혼잡할 때 5~20분 지연됩니다.
정확히 7시에 받아야 하면 cron을 `0 21 * * 0-4`(06:00 KST)로 당겨두세요.

**카톡 미리보기에서 카드가 잘릴 수 있습니다.** 카드는 인스타 비율(4:5)에 맞춰
세로로 깁니다. 카톡 말풍선에서는 일부만 보이고, 탭하면 전체가 열립니다.
카톡 위주로 보실 거면 `config.py` 의 `CARD_HEIGHT` 를 `1080`(정사각형)으로 바꾸세요.
(5장 전부 같은 비율로 다시 렌더링됩니다.)

**코스피·코스닥은 이제 실제 데이터입니다.** pykrx 로 전일 종가와 외국인·기관·개인
수급까지 4번 카드에 직접 표시합니다 (LLM 요약을 거치지 않아 숫자 오차가 없습니다).
과거에 쓰던 뉴욕 상장 한국 ETF(EWY)는 더 이상 카드에 표시하지 않습니다.

**두 달쯤 뒤 조용히 멈추는 경우**, 대부분 토큰 문제입니다.
`GH_PAT` 의 Secrets 쓰기 권한이 살아있는지, PAT 자체가 만료되지 않았는지 확인하세요.
PAT는 만료일을 1년 이상으로 잡아두는 편이 낫습니다.

**투자 권유는 담지 마세요.** 요약 프롬프트에 매수·매도 권유 금지가 들어가 있습니다.
개인 기록용이면 문제없지만, 공개 계정에 추천 뉘앙스가 반복되면
유사투자자문업 신고 대상이 될 수 있습니다. "시황 정리" 톤을 유지하세요.
이 도구가 만드는 것은 정보 정리이지 투자 자문이 아닙니다.
