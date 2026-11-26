# 올리기 서버 설정 (처음 한 번, 10분)

사이트의 **전시 올리기** 페이지는 zip 을 이 작은 서버로 보냅니다. 서버는 비밀번호를 확인한 뒤 GitHub 에 대신 올려 줍니다.
비밀번호와 GitHub 토큰은 Cloudflare 안에만 저장되고, 이 레포나 사이트 어디에도 들어가지 않습니다.

무료 Cloudflare 계정 하나면 됩니다. 카드 등록은 필요 없습니다.

## 1. GitHub 토큰 만들기

1. GitHub 오른쪽 위 프로필 → **Settings** → 맨 아래 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
2. 이름은 `aaa-upload` 처럼 아무거나, 만료일은 길게 잡습니다. (만료되면 올리기가 멈추니 새로 만들어 3번의 `GITHUB_TOKEN` 만 바꿔 넣으면 됩니다)
3. **Repository access** → **Only select repositories** → `aaa-exhibition` 하나만 고릅니다.
4. **Permissions → Repository permissions** 에서 두 가지만 **Read and write** 로 바꿉니다.
   - **Contents**
   - **Actions**
5. **Generate token** 을 누르고 나온 `github_pat_…` 값을 복사해 둡니다. 이 화면을 닫으면 다시 볼 수 없습니다.

## 2. Cloudflare 에 서버 만들기

1. <https://dash.cloudflare.com> 에 가입하고 로그인합니다.
2. 왼쪽 메뉴 **Workers & Pages** → **Create** → **Start with Hello World!** (또는 Create Worker)
3. 이름을 `aaa-upload` 로 적고 **Deploy**.
4. **Edit code** 를 눌러 원래 있던 코드를 전부 지우고, 이 폴더의 [`worker.js`](worker.js) 내용을 통째로 붙여 넣은 뒤 **Deploy**.

## 3. 값 다섯 개 넣기

만든 Worker 의 **Settings → Variables and Secrets → Add** 에서 아래 다섯 개를 넣고 **Deploy** 합니다.

| 종류 | 이름 | 값 |
| --- | --- | --- |
| **Secret** | `UPLOAD_PASSWORD` | 정한 올리기 비밀번호. 직접 입력합니다 |
| **Secret** | `GITHUB_TOKEN` | 1번에서 복사한 `github_pat_…` |
| Text | `GITHUB_REPO` | `jeonsan-9/aaa-exhibition` |
| Text | `SITE_URL` | `https://jeonsan-9.github.io/aaa-exhibition` |
| Text | `ALLOWED_ORIGIN` | `https://jeonsan-9.github.io` |

비밀번호와 토큰은 꼭 **Secret** 으로 넣습니다. Secret 은 저장한 뒤에는 Cloudflare 화면에서도 다시 보이지 않습니다.

## 4. 사이트에 서버 주소 알려 주기

Worker 화면 위쪽에 `https://aaa-upload.<내계정>.workers.dev` 같은 주소가 나옵니다. 브라우저로 열어 `{"ok":true,…}` 가 보이면 정상입니다.

이 레포의 [`config.json`](../config.json) 을 연필 아이콘으로 열어 주소를 넣고 **Commit changes** 합니다.

```json
{
  "upload_url": "https://aaa-upload.내계정.workers.dev"
}
```

3분쯤 뒤부터 `https://jeonsan-9.github.io/aaa-exhibition/upload/` 에서 올릴 수 있고, 전시 맨 아래에 **전시 올리기** 링크가 생깁니다.

## 알아 둘 것

- **비밀번호 바꾸기**: Cloudflare 에서 `UPLOAD_PASSWORD` 값만 새로 넣으면 됩니다.
- **틀린 비밀번호 막기**: 같은 곳에서 10분에 5번, 전체로 1시간에 30번 틀리면 한동안 막습니다. 다만 서버 메모리에 세는 간단한 장치라 완벽하지는 않습니다. 숫자 네 자리보다는 글자를 섞은 긴 비밀번호가 안전합니다.
- **비밀번호를 아는 사람은** 새 전시를 올릴 수 있고, 같은 이름으로 올려 기존 전시를 바꿀 수도 있습니다. 믿을 수 있는 사람에게만 알려 주세요. 바뀌기 전 zip 은 남지 않으니 원본은 따로 보관합니다.
- **크기**: zip 하나에 95MB 까지입니다. 더 크면 메인 안내서의 Releases 방법을 씁니다.
- 올린 zip 은 레포의 **Releases** 에 전시 이름으로 쌓입니다. 전시를 없애려면 그 릴리스를 지우고 Actions 에서 "전시 사이트 만들기" 를 다시 실행합니다.
