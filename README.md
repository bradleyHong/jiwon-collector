# 대구 정부지원사업 모니터링 자동화

매일 오전 9시 7분(Asia/Seoul 기준)에 대구 및 전국 단위 정부지원사업/창업지원/콘텐츠지원 공고를 수집하고, AI/인공지능/미디어아트/미디어파사드/영상/콘텐츠/XR/VR/AR/전시/공공디자인/디지털콘텐츠 관련 유망 공고를 선별합니다.

## 주요 기능

- `sources.yaml` 기반 어댑터형 수집: RSS, 공식 API, HTML 목록 페이지
- source별 네트워크 실패 기록: 한 사이트가 실패해도 전체 실행은 계속 진행
- 금액/마감일/지역/신청대상/키워드 정규화
- 총사업비와 선정규모가 함께 있으면 기업당 추정 지원금 자동 계산
- `title + org + deadline + url` 기준 deduplicate
- `seen.json` 기반 신규/업데이트/기존 공고 상태 관리
- `reports/YYYY-MM-DD.md`, `reports/latest.md` 요약 보고서 생성
- `reports/YYYY-MM-DD.html`, `reports/latest.html` 대시보드형 HTML 보고서 생성
- `site/index.html` 정적 홈페이지용 최신 리포트 생성
- HTML 리포트에서 새로 올라온 공고를 상단 별도 색상 섹션으로 강조
- HTML 리포트에서 최소 지원규모와 대상/업종/조건 검색 지원
- 카드에 지원금/규모, 대상/업력, 마감일, 지역/신청 가능성을 고정 표시
- `company_profile.md`의 관심 업종/종목을 상단 검색 칩으로 표시
- 하단에 공개용 회사 정보와 서비스 안내 표시
- `drafts/YYYY-MM-DD/사업명/application_draft.md` 지원서 초안 생성
- 유망 공고 발생 시 GitHub Issue, Telegram, 이메일 알림

## 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 로컬 실행

알림과 GitHub Issue 생성 없이 보고서와 초안만 생성합니다.

```bash
python -m daegu_grants.run --dry-run
```

GitHub Actions와 같은 필터를 로컬에서 확인하려면 아래처럼 실행합니다.

```bash
python -m daegu_grants.run \
  --dry-run \
  --min-amount 20000000 \
  --region "대구" \
  --keywords "AI,인공지능,미디어아트,미디어파사드,영상,콘텐츠,실감콘텐츠,XR,VR,AR,전시,디자인,공공디자인,공공미디어,디지털콘텐츠"
```

실행 결과:

- `data/opportunities.csv`
- `reports/YYYY-MM-DD.md`
- `reports/latest.md`
- `reports/YYYY-MM-DD.html`
- `reports/latest.html`
- `site/index.html`
- `drafts/YYYY-MM-DD/.../application_draft.md`

HTML 리포트를 브라우저로 열면 표가 훨씬 보기 좋습니다.

```bash
open reports/latest.html
```

## GitHub Secrets

Repository Settings > Secrets and variables > Actions에 아래 값을 설정하세요.

- `OPENAI_API_KEY`: 향후 AI 요약/초안 고도화용. 현재 초안은 허위 생성을 막기 위해 템플릿 기반입니다.
- `TELEGRAM_BOT_TOKEN`: Telegram BotFather에서 발급한 봇 토큰
- `TELEGRAM_CHAT_ID`: 알림을 받을 채팅 ID
- `GH_USERNAME`: Issue assignee로 지정할 GitHub username
- `BIZINFO_API_KEY`: 선택 사항. 기업마당 공식 지원사업정보 API 인증키. 없으면 HTML 목록 fallback을 사용합니다.
- `SMTP_HOST`: 이메일 발송 SMTP 서버. 예: `smtp.gmail.com`
- `SMTP_PORT`: SMTP 포트. 보통 `587`
- `SMTP_USERNAME`: SMTP 로그인 계정
- `SMTP_PASSWORD`: SMTP 비밀번호 또는 앱 비밀번호
- `SMTP_USE_TLS`: 선택 사항. 기본값 `true`
- `MAIL_FROM`: 발신자 이메일
- `MAIL_TO`: 수신자 이메일. 여러 명이면 SMTP 서버 정책에 맞게 쉼표로 구분

`GITHUB_TOKEN`은 GitHub Actions의 `${{ github.token }}` 컨텍스트로 자동 제공되므로 별도 secret을 만들 필요가 없습니다.

## GitHub Actions

`.github/workflows/daily-watch.yml`은 다음 조건으로 실행됩니다.

- `timezone: "Asia/Seoul"`을 사용해 매일 09:07 KST 실행
- `workflow_dispatch` 수동 실행
- 실행 후 `reports`, `data`, `drafts` 변경사항 commit/push
- `high_priority` 또는 `needs_review` 공고가 있으면 Issue 생성
- SMTP secrets가 있으면 `reports/latest.html`과 같은 HTML 본문으로 이메일 발송
- GitHub Pages나 정적 호스팅을 `site/` 폴더에 연결하면 홈페이지가 매일 자동 갱신됩니다.

## 소스 추가/수정

`sources.yaml`에 항목을 추가합니다.

```yaml
- id: example_source
  name: 예시기관
  org: 예시기관
  adapter: html_list
  url: "https://example.or.kr/notice"
  search_url: "https://example.or.kr/notice"
  rss_or_api: none_found
  notes: "공식 공고 목록. robots.txt와 이용조건 확인 후 추가."
```

지원 어댑터:

- `rss`: RSS/Atom feed
- `bizinfo_api`: 기업마당 공식 API. `BIZINFO_API_KEY` 필요
- `html_list`: HTML 목록 페이지. 무리한 상세 크롤링 없이 목록 텍스트와 링크 중심 수집

요청 간 sleep은 `sources.yaml`의 `settings.request_delay_seconds`로 조정합니다. 사이트가 robots.txt로 차단하면 해당 source는 건너뛰고 보고서의 `Source Errors`에 기록합니다.

## 선별 기준

- 대구 소재 기업이 신청 가능하거나 전국 공고로 대구 기업도 신청 가능하면 포함
- AI, 인공지능, 미디어아트, 미디어파사드, 영상, 콘텐츠, 실감콘텐츠, XR, VR, AR, 전시, 디자인, 공공미디어, 디지털콘텐츠 키워드 가점
- 정책자금, 융자, 대출, 보증, 특례보증, 이자지원, 경영안정자금도 별도 모니터링
- 제조업, 도소매업, 화훼/꽃, 로봇, 아트/콘텐츠 등 업종 키워드 검색 가능
- 지원금이 20,000,000원 이상이면 `high_priority`
- 총사업비만 공개된 경우 선정/선발 기업 수를 파싱해 기업당 추정액을 함께 표시
- 금액이 불명확해도 제작지원, 실증, R&D, 창업패키지, 여성기업, 사업화 지원이면 `needs_review`
- 마감일이 14일 이내면 점수 가점

## 보고서 컬럼

```markdown
| 추천 | 상태 | 기관 | 사업명 | 지원금 | 마감일 | D-day | 관련성 | 신청 가능성 | 링크 | 다음 액션 |
```

## 테스트

```bash
pytest -q
```

테스트 범위:

- 금액 파싱
- 마감일 파싱
- 키워드/우선순위 분류
- deduplication

## 확인한 주요 공식 소스

- 달구벌여성창업플랫폼 사업공고: `https://w-startup.daegu.go.kr/business`
- DASH 대구창업허브 지원사업공고: `https://startup.daegu.go.kr/index.do?menu_id=00002552`
- K-Startup 모집중 공고: `https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do`
- 모두의창업 공식 플랫폼: `https://www.modoo.or.kr/`
- 기업마당 지원사업정보 API: `https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do`
- 대구테크노파크 사업공고: `https://www.dgtp.or.kr/bbs/BoardControll.do?bbsId=BBSMSTR_000000000003`
- 대구디지털혁신진흥원 사업공고: `https://www.dip.or.kr/home/notice/businessbbs/boardList.ubs?fboardcd=business`
- 대구광역시 고시공고: `https://www.daegu.go.kr/index.do?menu_id=00940170`
- 대구 구·군청 공식 홈페이지: 북구, 동구, 달서구, 달성군, 수성구, 중구, 남구, 서구
- 대구신용보증재단: `https://ttg.co.kr/`
- 신용보증기금: `https://www.kodit.or.kr/kodit/main.do`
- 기술보증기금: `https://www.kibo.or.kr/index.do`
- 소상공인 정책자금: `https://ols.semas.or.kr/`
- 중소벤처기업부 사업공고 RSS: `https://mss.go.kr/rss/smba/board/310.do`
