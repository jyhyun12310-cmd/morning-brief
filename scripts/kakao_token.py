"""카카오 리프레시 토큰을 처음 한 번 발급받는 스크립트. 내 PC에서 실행합니다.

    python scripts/kakao_token.py

사전 준비 (developers.kakao.com):
  1) 애플리케이션 추가 → [앱 키]에서 REST API 키 복사
  2) [카카오 로그인] 활성화 ON
  3) [카카오 로그인] > Redirect URI 에 https://example.com/oauth 등록
  4) [동의항목] 에서 '카카오톡 메시지 전송'(talk_message) 을 선택 동의로 설정
"""

import urllib.parse

import requests

REDIRECT_URI = "https://example.com/oauth"


def main() -> None:
    rest_key = input("REST API 키: ").strip()
    client_secret = input("Client Secret (안 쓰면 엔터): ").strip()

    params = {
        "client_id": rest_key,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
    }
    url = "https://kauth.kakao.com/oauth/authorize?" + urllib.parse.urlencode(params)

    print("\n아래 주소를 브라우저에서 열고 동의하세요.")
    print("동의하면 example.com 으로 넘어가면서 주소창에 ?code=... 가 붙습니다.")
    print("페이지가 안 열려도 정상입니다. 주소창의 code 값만 복사하세요.\n")
    print(url, "\n")

    code = input("code 값: ").strip()

    payload = {
        "grant_type": "authorization_code",
        "client_id": rest_key,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    r = requests.post("https://kauth.kakao.com/oauth/token", data=payload, timeout=20)
    if r.status_code != 200:
        print("\n실패:", r.text)
        return

    body = r.json()
    print("\n── GitHub 시크릿에 등록할 값 ──")
    print("KAKAO_REST_API_KEY  =", rest_key)
    if client_secret:
        print("KAKAO_CLIENT_SECRET =", client_secret)
    print("KAKAO_REFRESH_TOKEN =", body["refresh_token"])
    print(f"\n(리프레시 토큰 유효기간: {body.get('refresh_token_expires_in', 0) // 86400}일)")
    print("매일 실행되면 자동으로 연장되므로 다시 발급받을 필요는 없습니다.")


if __name__ == "__main__":
    main()
