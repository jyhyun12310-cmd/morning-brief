"""인스타그램 장기 액세스 토큰을 처음 한 번 발급받는 스크립트. 내 PC에서 실행합니다.

    python scripts/instagram_token.py

사전 준비:
  1) 인스타 계정을 프로페셔널(비즈니스 또는 크리에이터)로 전환
     — 개인 계정은 API 접근이 아예 불가능합니다.
  2) developers.facebook.com → 앱 만들기 → 'Instagram' 제품 추가
  3) [Instagram] > API 설정 > '비즈니스 로그인 설정'에서
     - OAuth 리디렉션 URL 에 https://example.com/oauth 등록
     - 권한: instagram_business_basic, instagram_business_content_publish
  4) [앱 역할] > 역할 에서 내 인스타 계정을 Instagram Tester 로 추가하고,
     인스타 앱 > 설정 > 웹사이트 권한 > 테스터 초대 에서 수락
     — 이렇게 하면 앱 심사 없이 개발 모드로 내 계정에 게시할 수 있습니다.
"""

import urllib.parse

import requests

REDIRECT_URI = "https://example.com/oauth"
API_VERSION = "v23.0"


def main() -> None:
    app_id = input("Instagram 앱 ID: ").strip()
    app_secret = input("Instagram 앱 시크릿: ").strip()

    params = {
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "instagram_business_basic,instagram_business_content_publish",
    }
    url = "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode(params)

    print("\n아래 주소를 브라우저에서 열고 동의하세요.")
    print("주소창의 ?code=... 값을 복사하세요. 끝에 #_ 가 붙어 있으면 떼고 넣어도 됩니다.\n")
    print(url, "\n")

    code = input("code 값: ").strip().rstrip("#_")

    # 1) 단기 토큰
    r = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=20,
    )
    if r.status_code != 200:
        print("\n단기 토큰 실패:", r.text)
        return
    short = r.json()["access_token"]

    # 2) 장기 토큰 (60일)
    r = requests.get(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret,
            "access_token": short,
        },
        timeout=20,
    )
    if r.status_code != 200:
        print("\n장기 토큰 실패:", r.text)
        return
    long_token = r.json()["access_token"]

    # 3) 사용자 ID
    me = requests.get(
        f"https://graph.instagram.com/{API_VERSION}/me",
        params={"fields": "id,username", "access_token": long_token},
        timeout=20,
    ).json()

    print("\n── GitHub 시크릿에 등록할 값 ──")
    print("IG_USER_ID      =", me.get("id"))
    print("IG_ACCESS_TOKEN =", long_token)
    print(f"\n(계정: @{me.get('username')})")
    print("장기 토큰은 60일짜리지만 매일 자동 갱신되므로 재발급할 필요는 없습니다.")


if __name__ == "__main__":
    main()
