---
title: 리눅스 서버 리소스 사용량 총정리…top·meminfo·free로 CPU·메모리 보는 법
labels: [사용량, 서버, 생활정보, 리눅스, 서버모니터링, top, meminfo, free, df, iostat, CPU, 메모리, 디스크, 리소스, 인프라]
keyword: 리눅스 서버 리소스 사용량
intent: how-to
---

정보 기준일: 2026-08-05  
도구·출력 항목은 배포판·커널에 따라 조금 다를 수 있습니다. 숫자만 보지 말고 **단위·캐시·스왑**까지 같이 해석하세요.

## 한 줄 요약

이 글을 읽으면 서버가 느릴 때 **CPU·메모리·디스크·I/O 중 어디가 병목인지**를 `top`·`free`·`/proc/meminfo`·`df`·`iostat`로 바로 좁힐 수 있습니다. 설치 가이드가 아니라 **리소스 사용량 점검 모음집**입니다.

## 핵심 사실 (범위·대상·조건)

| 항목 | 내용 | 확인 포인트 |
| --- | --- | --- |
| 범위 | CPU·메모리·디스크·I/O 일상 점검 | `top`/`htop`, `free`, meminfo, `df`/`du`, `iostat` |
| 목표 | 병목 원인을 5~10분 안에 후보 축소 | 한 번에 전부 고치지 말고 원인부터 |
| 흔한 오해 | `free`의 buff/cache = “메모리 부족” | 대부분 회수 가능한 캐시 |
| 클라우드 | VM 크기·디스크 타입도 병목 | [Compute Engine 문서](https://cloud.google.com/compute/docs) |
| 정보 기준일 | 2026-08-05 | 커널·sysstat 패키지 유무 확인 |

클라우드 인스턴스라면 OS 지표와 함께 콘솔의 CPU/디스크 차트도 보세요. GCP는 [Compute Engine 모니터링](https://cloud.google.com/compute/docs/instances/monitor-instance)을 참고하면 됩니다.

## 나에게 해당되는지

### 맞는 사람

- VPS·온프레미스·클라우드에서 **느림·OOM·디스크 full**을 직접 보는 사람
- `top` 숫자는 보는데 **어디를 보면 되는지** 매번 헷갈리는 사람
- 장애 초동 대응 체크리스트를 팀 위키에 두고 싶은 사람

### 비대상·보류가 나은 경우

- 관리형 PaaS만 쓰고 게스트 OS에 접속하지 않는 경우
- APM/프로메테우스 대시보드만으로 충분한 대규모 관제 환경(이 글은 터미널 초동용)
- 원인 확인 없이 `kill -9`부터 하려는 경우 → 먼저 지표 확인

## 목차 (모음집)

1. 30초 초동 순서  
2. CPU (`top` / load)  
3. 메모리 (`free` / meminfo)  
4. 디스크 용량 (`df` / `du`)  
5. 디스크 I/O (`iostat` / `iotop`)  
6. 프로세스 원인 좁히기  
7. 상황별 해석 표  

관련 기본 명령(압축·SSH·방화벽)은 [리눅스 서버 셋업마다 검색하던 명령어 총정리](https://yeondodo.blogspot.com/2026/08/1-8.html)를 함께 보세요.

---

## 1) 지금 바로 할 초동 점검 (30초)

서버가 “느리다”고 들어오면 아래 순서가 안전합니다.

```bash
uptime
top -bn1 | head -20
free -h
df -h
df -i
```

| 순서 | 보는 것 | 이상 신호 |
| --- | --- | --- |
| 1 | `uptime` load | CPU 코어 수보다 부하가 오래 높음 |
| 2 | `top` %CPU / wa | 특정 프로세스 또는 I/O wait 높음 |
| 3 | `free -h` available | available이 거의 없고 swap 사용↑ |
| 4 | `df -h` / `df -i` | 용량 또는 inode 100% 근접 |
| 5 | 아래 I/O·프로세스 심화 | 원인 PID 확정 |

## 2) CPU — `top` / load average

### load average를 먼저

```bash
uptime
# 예: load average: 2.10, 1.50, 0.80  → 1분/5분/15분
nproc
```

대략 **load ≈ 실행 대기+실행 중 큐 길이**입니다. 코어가 2개인데 1분 load가 4~5면 CPU 또는 디스크 wait 쪽을 의심합니다. 15분 값까지 높으면 일시 spike가 아니라 지속 부하입니다.

### `top`에서 볼 칸

```bash
top
# 배치 1회 스냅샷
top -bn1 | head -30
```

| 항목 | 의미 | 메모 |
| --- | --- | --- |
| `%Cpu(s) us` | 유저 프로세스 CPU | 앱/연산 부하 |
| `sy` | 커널 | 시스템콜·드라이버 |
| `wa` | I/O wait | 디스크/네트워크 대기 → CPU만 늘려도 안 나음 |
| `id` | idle | 여유 |
| `%CPU` (프로세스) | 해당 프로세스 점유 | `P`로 CPU 정렬(환경별 키 다를 수 있음) |
| `RES` | 상주 메모리 | 메모리 용의자 후보 |

`htop`이 있으면 보기 편합니다.

```bash
sudo apt install -y htop   # Debian/Ubuntu
htop
```

클라우드에서 vCPU를 줄인 VM은 load가 낮아도 체감이 느릴 수 있습니다. 인스턴스 타입도 [Compute 문서](https://cloud.google.com/compute/docs/machine-resource)와 맞춰 보세요.

## 3) 메모리 — `free` / `/proc/meminfo`

### `free -h` 읽는 법

```bash
free -h
```

| 칸 | 의미 |
| --- | --- |
| `total` | 전체 RAM |
| `used` | 사용 중(계산 방식은 버전에 따라 표기 차이) |
| `buff/cache` | 버퍼·페이지 캐시(대개 압박 시 회수됨) |
| `available` | **앱이 새로 쓰기 쉬운 여유(핵심)** |
| `Swap used` | 스왑 사용량 |

**기억할 한 줄:** “메모리가 없다”는 판단은 `buff/cache`가 아니라 **`available`이 작고 swap이 늘어나는지**로 하세요.

### `/proc/meminfo` 핵심 키

```bash
grep -E 'MemTotal|MemFree|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|Dirty|Writeback' /proc/meminfo
```

| 키 | 볼 때 |
| --- | --- |
| `MemAvailable` | 실질 여유 (free의 available과 대응) |
| `Cached` / `Buffers` | 파일 캐시·버퍼 |
| `SwapFree` vs `SwapTotal` | 스왑이 줄면 메모리 압박 |
| `Dirty` / `Writeback` | 디스크에 아직 못 쓴 데이터 → I/O 병목과 함께 봄 |

```bash
# 메모리 상위 프로세스
ps aux --sort=-%mem | head -15
```

OOM이 의심되면:

```bash
sudo dmesg -T | grep -i -E 'oom|killed process' | tail -20
journalctl -k -g -i 'out of memory|killed process' -n 20 --no-pager
```

## 4) 디스크 용량 — `df` / `du`

```bash
df -h
df -i
du -xh /var | sort -h | tail -20
```

| 증상 | 명령 | 조치 힌트 |
| --- | --- | --- |
| 용량 100% | `df -h` | 로그·오래된 백업·Docker 볼륨 |
| inode 100% | `df -i` | 작은 파일 폭풍(캐시·메일·세션) |
| 어느 폴더? | `du -xh` | `/var/log`, `/var/lib/docker` 등 |

```bash
# 큰 파일 후보
sudo find / -xdev -type f -size +500M 2>/dev/null | head -30
```

용량을 비울 때도 열려 있는 삭제 파일은 공간이 안 돌아올 수 있습니다. `lsof | grep deleted`로 확인하세요.

## 5) 디스크 I/O — `iostat` / `iotop`

CPU `%wa`가 높거나 디스크 latency가 의심될 때입니다.

```bash
# sysstat 패키지 필요할 수 있음
sudo apt install -y sysstat
iostat -xz 1 5
```

| 항목 | 힌트 |
| --- | --- |
| `%util` | 장치에 가까울수록 I/O 바쁨(대략적) |
| `await` | 평균 대기 시간(ms) 상승 → 느린 디스크/큐 |
| `r/s` `w/s` | 읽기/쓰기 빈도 |

```bash
sudo apt install -y iotop
sudo iotop -oP
```

클라우드 SSD/표준 영구 디스크 한도도 병목입니다. 디스크 타입·IOPS는 [Compute 디스크 문서](https://cloud.google.com/compute/docs/disks)를 함께 보세요.

## 6) 프로세스 원인 좁히기

```bash
# CPU 상위
ps aux --sort=-%cpu | head -15

# 특정 포트/서비스와 연결
ss -tulpn
systemctl status nginx mysql docker --no-pager

# 스레드까지 (필요 시)
ps -eLf | head
```

| 목적 | 명령 |
| --- | --- |
| 실시간 CPU | `top` / `htop` |
| 1회 스냅샷 정렬 | `ps aux --sort=-%cpu` |
| 메모리 정렬 | `ps aux --sort=-%mem` |
| 열린 파일·삭제 잔존 | `lsof -p PID` / `lsof \| grep deleted` |
| 서비스 단위 | `systemctl status` + `journalctl -u NAME -n 100` |

원인 PID를 찾은 뒤에야 재시작·스케일아웃·쿼리 튜닝을 고르세요. 초동에서 `kill -9`는 마지막입니다.

## 7) 상황별 한눈에 해석

| 증상 | 지표 | 다음 액션 |
| --- | --- | --- |
| 전체가 버벅 | load↑, `%wa` 낮음, us↑ | CPU 상위 프로세스·스케일/최적화 |
| 디스크 때문에 느림 | `%wa`↑, `iostat await`↑ | 느린 쿼리·로그 폭주·디스크 타입 |
| 메모리 부족 | `available`↓, swap↑, OOM | 메모리 상위·누수·인스턴스 메모리 증설 |
| 갑자기 쓰기 실패 | `df -h` 또는 `df -i` 100% | 로그/도커 정리, inode 원인 폴더 |
| 재부팅 후만 괜찮음 | 메모리·디스크 누적 | 크론 정리·로그로테이트·캐시 정책 |

---

## 체크리스트 / 피해야 할 실수

- □ `uptime` + `nproc`로 load를 코어 수와 비교했다  
- □ `top`에서 `wa`(I/O wait)를 봤다  
- □ 메모리는 `buff/cache`가 아니라 `available`·swap으로 판단했다  
- □ `df -h`와 `df -i`를 둘 다 봤다  
- □ `%wa`가 높으면 `iostat`/`iotop`으로 장치를 확인했다  
- □ 원인 PID 없이 서비스부터 kill하지 않았다  
- 피해야 할 실수: cache가 크다고 **무조건 메모리 증설**부터 하는 것

## FAQ

**Q. `free`에서 used가 높은데 available도 넉넉해요. 문제인가요?**  
A. 보통 아닙니다. 리눅스는 남는 RAM을 캐시로 씁니다. 앱이 필요하면 회수됩니다. `available`과 swap을 보세요.

**Q. load는 낮은데 체감이 느려요.**  
A. 단일 스레드 병목, 디스크 latency, 네트워크, 애플리케이션 락을 의심하세요. `%wa`·`iostat`·앱 로그를 같이 봅니다.

**Q. swap을 쓰고 있으면 무조건 나쁜가요?**  
A. 조금 쓰는 건 흔합니다. **지속 증가 + available 고갈 + 응답 지연**이면 메모리 압박입니다.

**Q. `df`는 여유인데 새 파일이 안 만들어져요.**  
A. inode 고갈(`df -i`) 가능성이 큽니다. 작은 파일이 많은 디렉터리를 `du`/`find`로 찾으세요.

**Q. 클라우드 콘솔 그래프와 `top`이 다르게 보여요.**  
A. 집계 주기·에이전트·steal time 차이일 수 있습니다. 둘 다 보고, 게스트 OS 지표로 프로세스를 좁히세요.

## 관련 글

- [리눅스 서버 셋업마다 검색하던 명령어 총정리…tar·chmod·SSH·rsync 복붙 가이드](https://yeondodo.blogspot.com/2026/08/1-8.html)
- [갤럭시 폴드8·울트라·플립8 뭐 살까? 사전판매·가격 비교 가이드](https://yeondodo.blogspot.com/2026/07/88.html)
- [욘두두 블로그 소개 — 신청·예약·요금 정보를 쉽게](https://yeondodo.blogspot.com/2026/07/9-728-2.html)

## 한눈에 정리

| 할 일 | 명령 | 결과 |
| --- | --- | --- |
| 초동 | `uptime` `top` `free -h` `df -h` | 병목 축 후보 |
| CPU | `top` / `ps --sort=-%cpu` | 무거운 프로세스 |
| 메모리 | `free -h` / meminfo / `ps --sort=-%mem` | 여유·OOM 여부 |
| 디스크 | `df` `du` `iostat` | 용량 vs I/O |
| 조치 | 재시작·정리·스케일 선택 | 원인 확인 후 |

이 글은 서버 점검 참고용입니다. 프로덕션 조치 전에는 스냅샷·백업과 영향 범위를 확인하세요.
