---
title: 리눅스 서버 구축 명령어 가이드 총정리…압축·권한·SSH·방화벽 따라하기
labels: [명령어, 서버, 생활정보, 리눅스, 서버구축, tar, chmod, ssh, rsync, 방화벽, ufw, systemd, crontab, Docker, 인프라]
keyword: 리눅스 서버 명령어
intent: how-to
---

정보 기준일: 2026-08-05  
배포판·패키지 이름·방화벽 도구는 환경마다 다를 수 있습니다. 명령 실행 전 `man`·공식 문서와 스테이징에서 한 번 더 확인하세요.

## 한 줄 요약

이 글을 읽으면 서버 셋업할 때마다 검색하던 **압축·권한·SSH·rsync·방화벽·systemd·cron·Docker** 옵션을 한곳에서 바로 복붙해 쓸 수 있습니다. 뉴스 요약이 아니라 **인프라 구축 치트시트 모음집**입니다.

## 핵심 사실 (범위·대상·조건)

| 항목 | 내용 | 확인 포인트 |
| --- | --- | --- |
| 범위 | Linux 서버 일상 명령 10블록 | Ubuntu/Debian 기준, RHEL계열은 패키지명만 치환 |
| 목적 | 구축·배포·장애 대응 시 빠른 참조 | 옵션 표 + 복붙 예시 |
| 위험도 | `rm`/`chmod -R`/`ufw --force`/`rsync --delete` | dry-run·백업 후 실행 |
| 클라우드 참고 | Compute 인스턴스 SSH·방화벽 개념 | [Google Cloud Compute 문서](https://cloud.google.com/compute/docs) |
| 정보 기준일 | 2026-08-05 | 배포판 메이저 업그레이드 시 옵션 재확인 |

클라우드 VM을 쓰는 경우 OS 방화벽과 **클라우드 방화벽(VPC 규칙)** 이 둘 다 열려야 포트가 통합니다. GCP 쪽은 [Compute Engine 문서](https://cloud.google.com/compute/docs)에서 SSH·방화벽 규칙을 같이 보세요.

## 나에게 해당되는지

### 맞는 사람

- VPS·온프레미스·클라우드에 **리눅스 서버를 직접 올리는** 개발자·인프라 담당
- `tar`/`chmod`/`rsync` 옵션이 헷갈려 **매번 검색**하는 사람
- 초기 셋업 체크리스트를 팀 위키에 붙여 두고 싶은 사람

### 비대상·보류가 나은 경우

- GUI만 쓰고 터미널을 전혀 쓰지 않는 경우
- 관리형 PaaS만 쓰고 OS에 접속하지 않는 경우
- 프로덕션에서 **처음 보는 파괴적 옵션**(`--delete`, `chmod -R 777`)을 당장 실행하려는 경우 → 스테이징 먼저

## 목차 (모음집)

1. 압축/풀기  
2. 권한 (`chmod`/`chown`)  
3. 파일 찾기·디스크 (`find`/`du`/`df`)  
4. 전송·동기화 (`scp`/`rsync`)  
5. SSH  
6. 포트·프로세스  
7. 방화벽 (`ufw`)  
8. systemd + journalctl  
9. cron / timer  
10. Docker 일상  

---

## 1) 압축/풀기

배포 아카이브·백업 묶음을 다룰 때 가장 많이 검색하는 블록입니다.

| 확장자 | 풀기 | 만들기 |
| --- | --- | --- |
| `.tar` | `tar xf archive.tar` | `tar cf archive.tar dir/` |
| `.tar.gz` / `.tgz` | `tar xzf archive.tar.gz` | `tar czf archive.tar.gz dir/` |
| `.tar.bz2` | `tar xjf archive.tar.bz2` | `tar cjf archive.tar.bz2 dir/` |
| `.tar.xz` | `tar xJf archive.tar.xz` | `tar cJf archive.tar.xz dir/` |
| `.zip` | `unzip archive.zip` | `zip -r archive.zip dir/` |
| `.gz` (단일) | `gunzip file.gz` | `gzip file` |

자주 쓰는 옵션: `c` 생성, `x` 추출, `t` 목록, `v` 상세, `f` 파일명, `z` gzip, `J` xz, `-C /path` 풀 위치, `--strip-components=1` 최상위 폴더 제거.

```bash
# 목록만 확인
tar tzf app.tar.gz | head

# /opt에 풀기
tar xzf app.tar.gz -C /opt

# 특정 디렉터리만 묶어 백업
tar czf backup-$(date +%F).tar.gz /etc/nginx /var/www
```

## 2) 권한 (`chmod` / `chown` / `umask`)

웹 루트·배포 스크립트·SSH 키에서 권한이 틀리면 바로 장애가 납니다.

| 숫자 | 의미 | 대표 용도 |
| --- | --- | --- |
| `755` | rwxr-xr-x | 디렉터리, 실행 스크립트 |
| `644` | rw-r--r-- | 일반 설정·소스 파일 |
| `600` | rw------- | 비밀키, `.env` |
| `700` | rwx------ | 개인 홈·전용 디렉터리 |
| `440` | r--r----- | 읽기 전용 공유 설정(그룹) |

```bash
# 소유자 변경
sudo chown -R deploy:deploy /var/www/app

# 디렉터리 755 / 파일 644 패턴
find /var/www/app -type d -exec chmod 755 {} \;
find /var/www/app -type f -exec chmod 644 {} \;

# SSH 키
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub ~/.ssh/authorized_keys
```

`umask 022`면 새 파일은 대체로 `644`, 디렉터리는 `755`에 가깝습니다. **`chmod -R 777`은 임시 디버그용으로만** 쓰고 끝내면 되돌리세요.

## 3) 파일 찾기·디스크 (`find` / `du` / `df`)

로그·오래된 캐시·용량 폭탄을 찾을 때 씁니다.

| 목적 | 명령 |
| --- | --- |
| 디스크 여유 | `df -h` |
| 디렉터리별 용량 | `du -sh /var/* \| sort -h` |
| N일보다 오래된 로그 | `find /var/log -type f -mtime +14` |
| 큰 파일 | `find / -type f -size +500M 2>/dev/null` |
| 이름 검색 | `find /etc -name '*.conf'` |

```bash
# 14일 지난 .log 삭제 전 목록
find /var/log -type f -name '*.log' -mtime +14 -print

# 상위 20개 용량
du -xh /var | sort -h | tail -20
```

삭제 전에 `-print`로 목록을 보고, 필요하면 `-delete` 대신 휴지통 경로로 `mv` 하세요.

## 4) 전송·동기화 (`scp` vs `rsync`)

| 상황 | 추천 | 이유 |
| --- | --- | --- |
| 파일 몇 개 단발 복사 | `scp` | 단순 |
| 디렉터리 반복 동기화·배포 | `rsync` | 증분, exclude, dry-run |
| 미러 후 원본에 없는 것 삭제 | `rsync --delete` | **실수 위험 큼** |

```bash
# scp
scp -P 22 ./app.tar.gz user@host:/opt/

# rsync dry-run 먼저
rsync -avzn --exclude '.git' ./app/ user@host:/var/www/app/

# 실제 동기화 (진행률)
rsync -avz --progress --exclude '.git' ./app/ user@host:/var/www/app/
```

옵션 기억법: `-a` 아카이브(권한·시간 유지), `-v` 상세, `-z` 압축 전송, `-n` dry-run, `--delete` 대상에만 있는 파일 삭제.

## 5) SSH

키 기반 접속과 `~/.ssh/config`만 정리해도 실수가 크게 줄어듭니다.

```bash
# 키 생성
ssh-keygen -t ed25519 -C "deploy@$(hostname)"

# 공개키 등록
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@host

# 접속
ssh -i ~/.ssh/id_ed25519 -p 22 user@host
```

`~/.ssh/config` 예시:

```
Host prod
  HostName 203.0.113.10
  User deploy
  Port 22
  IdentityFile ~/.ssh/id_ed25519
  ForwardAgent no

Host bastion
  HostName bastion.example.com
  User jump

Host internal
  HostName 10.0.0.5
  User deploy
  ProxyJump bastion
```

이후 `ssh prod` / `ssh internal`만으로 접속합니다. 클라우드 VM은 OS SSH와 함께 [Compute Engine SSH 안내](https://cloud.google.com/compute/docs/connect/ssh-in-browser)도 참고하세요.

## 6) 포트·프로세스

| 목적 | 명령 |
| --- | --- |
| 리슨 포트 | `ss -tulpn` |
| 특정 포트 | `ss -tulpn \| grep ':80'` |
| 포트 점유 프로세스 | `sudo lsof -i :8080` |
| 프로세스 검색 | `ps aux \| grep nginx` |
| 정상 종료 | `kill PID` → 안 되면 `kill -15` → 최후 `kill -9` |

```bash
ss -tulpn
sudo lsof -iTCP:443 -sTCP:LISTEN
kill -15 12345
```

`-9`는 정리 훅을 건너뛰므로 DB·쓰기 중 프로세스에는 최후 수단으로만 쓰세요.

## 7) 방화벽 (`ufw` 중심)

Ubuntu/Debian에서는 `ufw`가 단순합니다. RHEL 계열은 `firewalld`(`firewall-cmd`)를 씁니다.

```bash
sudo ufw status verbose
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

**SSH 규칙을 넣 전에 `ufw enable` 하지 마세요.** 클라우드라면 VPC 방화벽에서 22/80/443도 같이 열어야 합니다 ([GCP 방화벽 규칙](https://cloud.google.com/firewall/docs/firewalls)).

## 8) systemd + journalctl

| 목적 | 명령 |
| --- | --- |
| 상태 | `systemctl status nginx` |
| 시작/중지/재시작 | `systemctl start\|stop\|restart nginx` |
| 부팅 시 자동 시작 | `systemctl enable --now nginx` |
| 최근 로그 | `journalctl -u nginx -n 100 --no-pager` |
| 실시간 | `journalctl -u nginx -f` |
| 부팅 이후 | `journalctl -b -u nginx` |

유닛 파일은 보통 `/etc/systemd/system/` 또는 `/lib/systemd/system/`. 수정 후 `sudo systemctl daemon-reload`.

## 9) cron / systemd timer

crontab:

```bash
crontab -e
# 분 시 일 월 요일  명령
0 3 * * * /usr/local/bin/backup.sh >> /var/log/backup.log 2>&1
```

자주 헷갈리는 점:

- cron 환경변수는 로그인 셸과 다름 → 스크립트에 `PATH`를 명시하거나 절대 경로 사용
- 리다이렉션 `>> file 2>&1`을 안 붙이면 실패 원인을 못 봄
- 사용자 cron vs `/etc/cron.d/` 시스템 cron 구분

systemd timer가 필요하면 `*.service` + `*.timer`를 만들고 `systemctl enable --now job.timer`로 등록합니다. 상태 확인: `systemctl list-timers`.

## 10) Docker 일상 명령

| 목적 | 명령 |
| --- | --- |
| 실행 중 컨테이너 | `docker ps` |
| 로그 | `docker logs -f --tail 200 NAME` |
| 접속 | `docker exec -it NAME bash` (없으면 `sh`) |
| compose 기동/종료 | `docker compose up -d` / `docker compose down` |
| 이미지·중지 컨테이너 정리 | `docker system prune` |
| 볼륨까지(주의) | `docker system prune -a --volumes` |

```bash
docker compose -f docker-compose.yml ps
docker compose logs -f api
docker image prune -f
```

`--volumes`는 데이터 삭제입니다. 프로덕션에서는 반드시 볼륨 이름·백업을 확인하세요.

---

## 지금 바로 할 서버 초기 셋업 체크

새 VM을 받았을 때 아래 순서로 확인하면 됩니다.

1. `ssh` 키 접속 확인 → 비밀번호 로그인 정책 점검  
2. `sudo apt update && sudo apt upgrade -y` (또는 `dnf update`)  
3. 시간대: `timedatectl set-timezone Asia/Seoul`  
4. `ufw`에 OpenSSH·필요 포트만 허용 후 enable  
5. 배포 유저 생성 + `chown`/`chmod`로 앱 디렉터리 권한  
6. 앱·리버스 프록시 설치 후 `systemctl enable --now`  
7. `ss -tulpn`으로 리슨 포트 확인  
8. 백업/`rsync` dry-run 한 번 검증  

클라우드를 쓰면 이 단계에서 [Compute Engine 문서](https://cloud.google.com/compute/docs)의 방화벽·SSH 가이드를 OS 설정과 대조하세요.

## 체크리스트 / 피해야 할 실수

- □ SSH 키 권한이 `600`/`700`인가  
- □ `ufw enable` 전에 SSH allow를 넣었는가  
- □ `rsync --delete` 전에 `-n` dry-run을 돌렸는가  
- □ cron 스크립트에 절대 경로·로그 리다이렉션이 있는가  
- □ `chmod 777`·`kill -9`를 습관적으로 쓰지 않는가  
- □ Docker prune에서 볼륨 삭제 여부를 읽었는가  
- 피해야 할 실수: 프로덕션에서 검색한 명령을 **옵션 의미 확인 없이 루트로 바로 실행**하는 것

## FAQ

**Q. `tar`에서 `z`와 `J` 중 뭘 쓰나요?**  
A. `.gz`면 `z`, `.xz`면 `J`입니다. 확장자를 보고 맞추거나, 최근 `tar`는 `tar xf archive.tar.gz`처럼 자동 감지도 됩니다.

**Q. `scp`와 `rsync` 중 기본값은?**  
A. 단발 파일은 `scp`, 배포·백업·반복 동기화는 `rsync`가 안전하고 빠릅니다. 삭제 동기화가 필요하면 반드시 dry-run 먼저.

**Q. `ufw status`는 inactive인데 포트가 막혀 있어요.**  
A. 클라우드 보안 그룹/VPC 방화벽·앞단 로드밸런서 ACL을 같이 보세요. OS `ufw`만의 문제가 아닌 경우가 많습니다.

**Q. cron에선 되는데 수동으론 되는 스크립트가 실패해요.**  
A. `PATH`, 작업 디렉터리, 환경변수 차이입니다. 스크립트 shebang·절대 경로·`printenv` 로그로 비교하세요.

**Q. `kill -9`를 언제 쓰나요?**  
A. `-15`로 종료되지 않고, 좀비/멈춘 프로세스이며, 데이터 손실을 감수할 수 있을 때만 쓰세요.

## 관련 글

- [갤럭시 폴드8·울트라·플립8 뭐 살까? 사전판매·가격 비교 가이드](https://yeondodo.blogspot.com/2026/07/88.html)  
- [2026년 3분기 전기요금 동결일까? 하계 누진·한전ON 고지서 보는 법](https://yeondodo.blogspot.com/2026/07/blog-post_403.html)  
- [욘두두 블로그 소개 — 신청·예약·요금 정보를 쉽게](https://yeondodo.blogspot.com/2026/07/9-728-2.html)

## 한눈에 정리

| 할 일 | 명령 힌트 | 결과 |
| --- | --- | --- |
| 아카이브 배포 | `tar xzf … -C` | 앱 풀기 |
| 권한 고정 | `755`/`644`/`600` | 접속·보안 기본선 |
| 동기화 | `rsync -avzn` → `-avz` | 안전한 배포 |
| 외부 노출 | `ufw allow` + 클라우드 FW | 포트 오픈 |
| 서비스 유지 | `systemctl enable --now` | 재부팅 후 자동 기동 |
| 배치 | `crontab` / timer | 백업·정리 자동화 |

이 글은 서버 운영 참고용입니다. 프로덕션 변경 전에는 스냅샷·백업과 스테이징 검증을 권장합니다.
