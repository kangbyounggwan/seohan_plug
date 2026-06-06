# seohan_plug — Factor MES 온톨로지 플러그인 플랫폼

> Factor MES 데스크탑 앱에 **여러 작성자가 플러그인을 올릴 수 있는** 마켓플레이스의
> 단일 진실원(SoT). 현재 등급: **T1 — 선언적 데이터 전용**(코드 실행 0).

## 이게 무엇인가

Factor MES 의 "기본 챗봇"(커널)은 업종/회사 색이 빠진 범용 구조다. 플러그인은 그 위에
**회사·업종 고유 온톨로지(공장 구조, 라인/스테이션, 공정 순서, 개념 사전)** 를 얹는
**선언적 데이터 번들**이다. 데스크탑이 플러그인을 다운로드 → 동의(이관 동의서) →
로컬 적용하면, 뷰어로 그래프를 탐색하고 백엔드가 overlay 로 활용한다.

```
[작성자] manifest + pack 작성 → fpkg validate → 게시
   ▼
[레지스트리(이 repo + llm-backend 라우터)] 테넌트 스코프로 서빙
   ▼
[데스크탑] 카탈로그 → 이관 동의서 → install(검증) → app:// 뷰어
```

## 확장 등급 (현재 T1)

| 등급 | 모델 | 상태 |
|---|---|---|
| **T1 선언적 데이터** | 온톨로지/스키마 JSON 만. 코드 실행 0 | ✅ 현재 |
| T2 샌드박스 코드 | 뷰어 확장 (CSP+no-IPC partition) | 향후 |
| T3 신뢰 코드 | 어댑터/커넥터 (서명+심사) | 향후 |

다수 작성자 마켓의 안전을 위해 **선언적 우선**. T1 플러그인은 임의 코드를 실행하지
않으므로 스키마 검증만으로 안전이 보장된다.

## 구조

```
seohan_plug/
├── spec/
│   ├── manifest.schema.json   # 플러그인 매니페스트 계약 (JSON Schema)
│   └── pack.schema.json       # T1 온톨로지 pack 데이터 스키마
├── plugins/
│   └── seohan/
│       ├── manifest.json      # 서한 플러그인 매니페스트
│       └── pack.json          # 온톨로지 데이터 (entities/edges/concepts/…)
├── registry/                  # 순수 디스커버리/검증 로직 (host 비의존, 테스트 가능)
│   ├── registry.py
│   └── validate.py
├── backend/
│   └── router.py              # S3 — llm-backend 에 mount 되는 레지스트리 API (테넌트 스코프)
├── sdk/
│   └── fpkg.py                # 작성자 CLI: validate / build / checksum
├── tests/
│   └── test_registry.py
└── docs/
    └── plugin-author-guide.md # "어떤 식으로 개발해서 올리나" — 작성자 가이드
```

## 작성자 시작점

플러그인을 개발해 올리는 방법은 [docs/plugin-author-guide.md](docs/plugin-author-guide.md) 참조.

## host 통합

- **백엔드(llm-backend)**: `backend/router.py` 를 submodule 로 mount → `/api/ontology/*` 레지스트리 API.
- **데스크탑(factor-desktop)**: S1 `app://` 프로토콜 + S4 install IPC (별도 섹션).

레지스트리 로직(`registry/`)은 host 비의존 순수 모듈이라 이 repo 안에서 단독 테스트된다.
FastAPI 라우터(`backend/router.py`)는 `app.*` 서비스를 **지연 import** 해 mount 시에만 결합한다.
