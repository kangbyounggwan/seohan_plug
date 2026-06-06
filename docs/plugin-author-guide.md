# 플러그인 작성자 가이드 (T1 선언적)

> "어떤 식으로 개발해서 올리나" — Factor MES 마켓에 플러그인을 올리는 표준 흐름.
> 현재 등급: **T1 선언적 데이터 전용**. 플러그인은 **코드를 실행하지 않는다**(JSON 데이터만).

## 1. 플러그인이란

업종/회사 고유 **온톨로지 overlay** 를 커널 위에 얹는 선언적 데이터 번들이다.
- 커널(기본 챗봇)은 색이 빠진 범용 구조.
- 플러그인 = 그 회사의 공장 구조(엔티티/변수), 관계(라인→스테이션, 공정 순서), 개념 사전.
- 데스크탑이 다운로드 → 이관 동의 → 적용하면 뷰어 그래프 + 백엔드 overlay 로 쓰인다.

## 2. 번들 구조

```
plugins/<id>/
├── manifest.json     # 계약 (spec/manifest.schema.json)
└── pack.json         # 온톨로지 데이터 (spec/pack.schema.json)
```

`<id>` 는 `^[a-z0-9_]+$`, 전역 고유. ontology 타입은 `adapter_type` 과 동일하게 권장.

## 3. manifest.json — 계약

```json
{
  "schema_version": "1.0",
  "id": "acme",
  "name": "ACME 금속가공 온톨로지",
  "version": "1.0.0",
  "type": "ontology",
  "adapter_type": "acme",
  "visibility": "company-private",
  "company_id": "<회사 UUID>",
  "author": { "name": "ACME", "verified": false },
  "kernel_api": "^1.0",
  "description": "…",
  "permissions": [],
  "data": { "pack": "pack.json" },
  "checksum": "sha256:<자동계산>"
}
```

| 필드 | 의미 |
|---|---|
| `id` / `version` | 고유 id + semver. 같은 id 의 새 version = 레지스트리 새 row |
| `type` | T1 은 `ontology` 만 |
| `visibility` | `public`(누구나) / `company-private`(소유 회사만) |
| `company_id` | company-private 필수 — 이 회사 사용자에게만 노출 |
| `kernel_api` | 호환 커널 범위. 비호환 커널에선 install 거부 |
| `permissions` | **T1 은 반드시 `[]`** (코드/권한 없음 = 안전 보장) |
| `checksum` | pack 의 canonical sha256. `fpkg checksum` 으로 자동 |

## 4. pack.json — 데이터

`spec/pack.schema.json` 준수. 필수: `adapter_type`, `entities`, `edges`.
- `entities`: `{ <엔티티>: { vars: { <변수>: {role,dtype,volatility,sample,source} } } }`
- `edges`: `[{ src, dst, type }]` (hasChild/produces/hasMeasure/hasEvent/hasCause/precedes)
- 선택: `concepts`, `station_types`, `alarm_types`, `line_routes`, `node_call_plan`

실 DB 에서 pack 을 자동 생성하려면 빌더 스크립트 패턴 참조(예: 서한은 DB+API 카탈로그를
캐서 pack 구성). 손으로 작성해도 무방.

## 5. 개발 → 검증 → 올리기

```bash
# (1) 번들 작성: plugins/<id>/manifest.json + pack.json

# (2) pack 수정할 때마다 체크섬 갱신
python sdk/fpkg.py checksum plugins/<id>

# (3) 계약 검증 (스키마·필수키·adapter_type 일치·체크섬)
python sdk/fpkg.py validate plugins/<id>
#   ✅ plugins/<id> — 유효  →  통과해야 게시 가능

# (4) 배포 패키지 생성 (선택)
python sdk/fpkg.py build plugins/<id>     # dist/<id>-<ver>.fpkg

# (5) 올리기: 검증 통과한 번들을 레지스트리에 게시
#     - 현재: plugins/<id>/ 를 이 repo 에 PR → 머지 시 등록(drop-in)
#     - 향후: fpkg publish (운영 레지스트리 API + 서버측 게이트 + 심사)
```

## 6. 서버측 게이트 (게시 시 자동 검증)

올라온 플러그인은 서버가 다시 검증한다(작성자 로컬 검증을 신뢰하지 않음):
스키마·필수키·`adapter_type` 일치·크기 상한·체크섬·중복 id. 하나라도 실패 → 거부.

## 7. 신뢰 등급

| 등급 | 조건 | install 시 |
|---|---|---|
| `verified` | 서명 + 심사 통과 (`author.verified=true`) | 표준 동의 |
| `community` | 서명만 | 경고 + 동의 |
| `private` | 회사 내부(company-private) | **이관 동의서** (회사 자산 로컬 이관 동의) |

데스크탑 install 은 다운로드 전 **이관 동의서** 를 띄우고, 동의해야 배포·적용한다.

## 8. 호환성 / 버전

- `kernel_api` semver range 로 커널 호환을 선언. 커널이 깨지는 변경을 하면 major 를 올리고,
  구버전 플러그인은 install 단계에서 거부된다.
- pack 데이터 스키마가 바뀌면 `schema_version` 을 올리고 마이그레이션 노트를 남긴다.

## 9. 하지 말 것 (T1)

- 코드/스크립트 포함 금지 (JSON 데이터만). `permissions` 비어야 함.
- mutation API 참조 금지 (read-only 카탈로그만). 서버가 mutation 흔적 발견 시 거부.
- 타사 `company_id` 사칭 금지 — 서버가 게시자 신원과 대조.
