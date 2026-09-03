# -*- coding: utf-8 -*-
"""persona_consumption_90d_v2.csv 생성기.
페르소나: 안정형 소비 습관 + 간헐적 충동 소비를 하는 직장인.
v1 모순(고정지출 변동, 요금 변동, 구독 불일치, 입금 부재, 모임 정산 부재, 지역 단일,
재택/공휴일 통학, 다이소 의류, 분류 소스 혼재, 휴일 자동이체)을 규칙으로 차단한다.
"""
import csv, sys
from datetime import date, timedelta, time
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
rng = np.random.default_rng(20260903)

START, END = date(2026, 6, 6), date(2026, 9, 3)
HOLIDAYS = {date(2026, 6, 6), date(2026, 8, 15), date(2026, 8, 17)}   # 현충일, 광복절, 대체공휴일
LEAVE = {date(2026, 7, 31), date(2026, 8, 14)}                        # 연차
WFH = {date(2026, 6, 17), date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 29),
       date(2026, 8, 12), date(2026, 8, 26)}                          # 재택 (격주 수요일)
PENDING_FROM = date(2026, 8, 30)   # 최근 5일 내 신규 가맹점은 미확정

P = dict(persona_id="P-DEMO-002", persona_name="이서준", age="31",
         occupation="IT 서비스기업 마케팅 사무직", residence="서울 관악구 봉천동",
         workplace="서울 강남구 역삼동", income_band="월 300~350만원", user_id="USR-DEMO-002")
CARD, ACC, SAV = "CARD-DEMO-002", "ACC-DEMO-002", "ACC-DEMO-003"
HOME, WORK, ONLINE = "관악구 봉천동", "강남구 역삼동", "온라인"
KOR = "월화수목금토일"

def is_bizday(d): return d.weekday() < 5 and d not in HOLIDAYS
def next_bizday(d):
    while not is_bizday(d): d += timedelta(days=1)
    return d
def prev_bizday(d):
    while not is_bizday(d): d -= timedelta(days=1)
    return d
def is_workday(d): return is_bizday(d) and d not in LEAVE and d not in WFH
def t(h, m): return f"{h:02d}:{m:02d}"
def jit(h, m, spread=25):
    mm = h * 60 + m + int(rng.integers(-spread, spread + 1))
    return t(mm // 60, mm % 60)

# 가맹점 마스터: name -> (category, subcategory, area, classify_mode)
#   MAP  : 가맹점 맵에 등록 -> 항상 MERCHANT_MAP/AUTO
#   RULE : 사용자가 지정한 고정 규칙(월세·적금·급여·공과금) -> RULE/AUTO
#   LOCAL: 미등록 소상공인 -> 첫 결제 MODEL, 이후 학습돼 MERCHANT_MAP
#   PERSON: 개인 송금 -> USER/CONFIRMED
M = {}
def reg(name, cat, sub, area, mode="LOCAL"):
    M[name] = dict(cat=cat, sub=sub, area=area, mode=mode, id=f"M-{len(M)+1:02d}")

reg("서울교통공사", "교통", "대중교통", HOME, "MAP")
reg("카카오T", "교통", "택시", WORK, "MAP")
reg("회사 구내식당", "식비", "점심", WORK, "LOCAL")
reg("김밥천국 역삼점", "식비", "점심", WORK, "MAP")
reg("샐러디 역삼점", "식비", "점심", WORK, "MAP")
reg("역삼 순대국집", "식비", "점심", WORK, "LOCAL")
reg("역삼 한식뷔페", "식비", "점심", WORK, "LOCAL")
reg("메가커피 역삼점", "식비", "카페", WORK, "MAP")
reg("스타벅스 역삼점", "식비", "카페", WORK, "MAP")
reg("봉천 로스터리", "식비", "카페", HOME, "LOCAL")
reg("GS25 봉천점", "식비", "편의점", HOME, "MAP")
reg("CU 역삼점", "식비", "편의점", WORK, "MAP")
reg("이마트 신림점", "식비", "장보기", "관악구 신림동", "MAP")
reg("쿠팡 로켓프레시", "식비", "장보기", ONLINE, "MAP")
reg("배달의민족", "식비", "배달", HOME, "MAP")
reg("봉천 칼국수", "식비", "저녁/외식", HOME, "LOCAL")
reg("역삼 돈까스집", "식비", "저녁/외식", WORK, "LOCAL")
reg("봉천 쌀국수", "식비", "저녁/외식", HOME, "LOCAL")
reg("샤로수길 파스타", "식비", "저녁/외식", "관악구 봉천동(샤로수길)", "LOCAL")
reg("역삼 이자카야", "사회·경조", "모임", WORK, "LOCAL")
reg("홍대 양꼬치", "사회·경조", "모임", "마포구 서교동", "LOCAL")
reg("성수 브루어리", "사회·경조", "모임", "성동구 성수동", "LOCAL")
reg("CGV 신림", "여가·문화", "영화/공연", "관악구 신림동", "MAP")
reg("국립현대미술관 서울", "여가·문화", "전시", "종로구 소격동", "LOCAL")
reg("잠실 야구장 매표", "여가·문화", "스포츠 관람", "송파구 잠실동", "LOCAL")
reg("봉천 피트니스", "여가·문화", "헬스장", HOME, "LOCAL")
reg("넷플릭스", "주거·통신", "구독", ONLINE, "MAP")
reg("멜론", "주거·통신", "구독", ONLINE, "MAP")
reg("SKT", "주거·통신", "통신", ONLINE, "MAP")
reg("KT 인터넷", "주거·통신", "인터넷", ONLINE, "MAP")
reg("한국전력", "주거·통신", "전기요금", ONLINE, "RULE")
reg("서울도시가스", "주거·통신", "가스요금", ONLINE, "RULE")
reg("집주인 김OO (월세)", "주거·통신", "월세", HOME, "RULE")
reg("○○은행 정기적금", "저축·투자", "적금", ONLINE, "RULE")
reg("(주)케이마케팅 급여", "수입", "급여", ONLINE, "RULE")
reg("다이소 봉천점", "쇼핑", "생활용품", HOME, "MAP")
reg("올리브영 강남점", "쇼핑", "뷰티·건강", "강남구 역삼동", "MAP")
reg("무신사", "쇼핑", "의류", ONLINE, "MAP")
reg("쿠팡", "쇼핑", "생활용품", ONLINE, "MAP")
reg("신세계백화점 강남점", "쇼핑", "의류", "서초구 반포동", "MAP")
reg("스팀", "여가·문화", "게임", ONLINE, "MAP")
reg("봉천 헤어살롱", "생활서비스", "미용", HOME, "LOCAL")
reg("봉천 온누리약국", "건강", "약국", HOME, "LOCAL")
reg("역삼 연세내과", "건강", "병원", WORK, "LOCAL")
reg("교보문고 강남점", "교육", "도서", "서초구 서초동", "MAP")
reg("인프런", "교육", "온라인 강의", ONLINE, "MAP")
for p in ["김민수", "박지훈", "이하은", "최윤서"]:
    reg(p, "사회·경조", "모임 정산", ONLINE, "PERSON")
reg("정우진 (결혼식 축의금)", "사회·경조", "경조사", ONLINE, "PERSON")

seen = set()
rows = []
def add(d, tm, merchant, amount, *, direction="EXPENSE", ttype="CARD", memo="",
        pattern="ROUTINE", fixed=False, recurring=False, exclude="NONE", cat=None, sub=None):
    m = M[merchant]
    src, st = "", ""   # 정렬 후 시간순으로 확정
    acct = ttype != "CARD"
    rows.append(dict(
        **{k: v for k, v in P.items()},
        transaction_id="", source="SEED", direction=direction, transaction_type=ttype,
        payment_method="ACCOUNT" if acct else "CARD",
        transaction_date=d.isoformat(), day_of_week=KOR[d.weekday()], transaction_time=tm,
        category=cat or m["cat"], subcategory=sub or m["sub"], merchant=merchant, merchant_id=m["id"],
        merchant_area=m["area"], amount_krw=int(amount),
        account_id=ACC if acct else "", card_id="" if acct else CARD,
        is_fixed=str(fixed).lower(), is_recurring=str(recurring).lower(),
        spend_pattern=pattern, classify_source=src, confirm_status=st,
        exclude_tag=exclude, status="NORMAL", memo=memo))

def r100(x): return int(round(x / 100.0)) * 100

# ---------- 1. 고정·정기 (금액 불변, 휴일은 다음 영업일) ----------
for mth in (6, 7, 8):
    d = date(2026, mth, 25)
    pay = prev_bizday(d) if d >= START else None      # 급여: 휴일이면 앞당겨 지급
    if pay and pay >= START:
        add(pay, t(9, 0), "(주)케이마케팅 급여", 3_120_000, direction="INCOME", ttype="DEPOSIT",
            memo="월 급여(세후)", pattern="FIXED", recurring=True)
    d = date(2026, mth, 10)
    if d >= START:
        add(next_bizday(d), t(8, 0), "집주인 김OO (월세)", 700_000, ttype="WITHDRAW",
            memo="월세 자동이체", pattern="FIXED", fixed=True, recurring=True)
    d = date(2026, mth, 26)
    if d >= START:
        add(next_bizday(d), t(8, 0), "○○은행 정기적금", 500_000, direction="TRANSFER", ttype="TRANSFER_OUT",
            memo=f"정기적금 자동이체 → {SAV}", pattern="FIXED", fixed=True, recurring=True, exclude="INTERNAL_TRANSFER")
    d = date(2026, mth, 15)
    if d >= START:
        add(next_bizday(d), t(9, 30), "SKT", 55_000, ttype="WITHDRAW", memo="휴대폰 요금 자동이체",
            pattern="FIXED", fixed=True, recurring=True)
    d = date(2026, mth, 20)
    if d >= START:
        add(next_bizday(d), t(9, 30), "KT 인터넷", 33_000, ttype="WITHDRAW", memo="인터넷 요금 자동이체",
            pattern="FIXED", fixed=True, recurring=True)
    d = date(2026, mth, 12)
    if d >= START:
        add(d, t(3, 10), "넷플릭스", 13_500, memo="구독 자동결제", pattern="FIXED", fixed=True, recurring=True)
    d = date(2026, mth, 8)
    if d >= START:
        add(d, t(3, 10), "멜론", 10_900, memo="구독 자동결제", pattern="FIXED", fixed=True, recurring=True)
# 전기·가스: 청구 주체 분리, 사용량 변동(여름 전기↑ 가스↓)
for mth, elec in ((6, 38_400), (7, 47_900), (8, 81_300)):
    add(next_bizday(date(2026, mth, 22)), t(9, 30), "한국전력", elec, ttype="WITHDRAW",
        memo="전기요금(전월 사용분, 변동)", pattern="FIXED", recurring=True)
for mth, gas in ((6, 16_200), (7, 11_800), (8, 10_900)):
    add(next_bizday(date(2026, mth, 27)), t(9, 30), "서울도시가스", gas, ttype="WITHDRAW",
        memo="도시가스 요금(변동)", pattern="FIXED", recurring=True)
# 헬스장: 집 근처, 매월 6일 정액, 현장 카드 결제라 시각은 다름
for mth in (6, 7, 8):
    add(date(2026, mth, 6), jit(20, 10) if mth != 6 else jit(10, 30), "봉천 피트니스", 60_000,
        memo="월 회원권", pattern="FIXED", fixed=True, recurring=True)

# ---------- 2. 평일 루틴 (통학 요금 고정 1,550 왕복 2건, 점심, 커피) ----------
LUNCH = [("회사 구내식당", 7_000, 0.55), ("김밥천국 역삼점", 6_500, 0.12), ("샐러디 역삼점", 9_800, 0.12),
         ("역삼 순대국집", 10_000, 0.11), ("역삼 한식뷔페", 9_000, 0.10)]
late_taxi_days = {date(2026, 6, 18), date(2026, 7, 9), date(2026, 7, 23), date(2026, 8, 20)}   # 야근 귀가
d = START
while d <= END:
    if is_workday(d):
        add(d, jit(8, 5, 12), "서울교통공사", 1_550, memo="출근 (봉천역→역삼역)")
        names, amts, ws = zip(*LUNCH)
        i = rng.choice(len(names), p=np.array(ws) / sum(ws))
        add(d, jit(12, 20, 20), names[i], amts[i], memo="평일 점심")
        u = rng.random()
        if u < 0.55:   add(d, jit(13, 10, 10), "메가커피 역삼점", 2_000, memo="식후 커피")
        elif u < 0.75: add(d, jit(13, 10, 10), "스타벅스 역삼점", 4_500, memo="식후 커피")
        if d in late_taxi_days:
            add(d, jit(22, 40, 20), "카카오T", r100(16_000 + rng.integers(0, 2_500)),
                memo="야근 후 택시 귀가 (역삼→봉천)")
        else:
            add(d, jit(19, 0, 30), "서울교통공사", 1_550, memo="퇴근 (역삼역→봉천역)")
        if rng.random() < 0.18:
            add(d, jit(17, 30, 40), "CU 역삼점", r100(rng.integers(1_800, 5_200)), memo="간식")
    elif d in WFH:
        add(d, jit(12, 30, 15), "배달의민족", r100(rng.integers(12_000, 16_500)), memo="재택 점심 배달")
        add(d, jit(15, 30, 30), "봉천 로스터리", 4_800, memo="재택 오후 커피")
    d += timedelta(days=1)

# ---------- 3. 주말·저녁 루틴 ----------
d = START
while d <= END:
    if d.weekday() == 5 and d not in (date(2026, 8, 22), date(2026, 8, 29)):
        add(d, jit(11, 0, 40), "이마트 신림점", r100(rng.integers(48_000, 72_000)), memo="주간 장보기", pattern="PLANNED")
    if d.weekday() == 6 and rng.random() < 0.6:
        add(d, jit(14, 0, 60), "봉천 로스터리", 4_800, memo="주말 카페")
    if d.weekday() in (1, 3) and rng.random() < 0.25 and d not in LEAVE and d not in HOLIDAYS:
        add(d, jit(20, 0, 25), "봉천 칼국수", 9_000, memo="퇴근 후 저녁")
    d += timedelta(days=1)
for dd in (date(2026, 6, 16), date(2026, 7, 7), date(2026, 8, 4), date(2026, 8, 25)):
    add(dd, jit(21, 0, 15), "쿠팡 로켓프레시", r100(rng.integers(28_000, 36_000)), memo="생필품·식재료 온라인", pattern="PLANNED")
for dd in (date(2026, 6, 13), date(2026, 7, 11), date(2026, 8, 8)):
    add(dd, jit(15, 0, 30), "봉천 헤어살롱", 15_000, memo="월 1회 커트")
add(date(2026, 6, 21), t(14, 20), "CGV 신림", 15_000, memo="주말 영화", pattern="PLANNED")
add(date(2026, 7, 5), t(11, 40), "국립현대미술관 서울", 4_000, memo="전시 관람", pattern="PLANNED")
add(date(2026, 7, 5), t(10, 55), "서울교통공사", 1_550, memo="전시 이동 (봉천→안국)")
add(date(2026, 7, 5), t(16, 30), "서울교통공사", 1_550, memo="귀가 (안국→봉천)")
add(date(2026, 8, 9), t(17, 10), "잠실 야구장 매표", 18_000, memo="야구 관람", pattern="PLANNED")
add(date(2026, 8, 9), t(15, 50), "서울교통공사", 1_550, memo="야구장 이동 (봉천→종합운동장)")
add(date(2026, 8, 9), t(22, 35), "카카오T", 21_400, memo="경기 후 택시 귀가 (잠실→봉천)")
add(date(2026, 8, 15), t(12, 40), "샤로수길 파스타", 17_500, memo="광복절 점심 외식")
add(date(2026, 7, 31), t(13, 10), "샤로수길 파스타", 16_000, memo="연차 점심")
add(date(2026, 8, 14), t(12, 30), "봉천 칼국수", 9_000, memo="연차 점심")
add(date(2026, 6, 30), t(21, 15), "인프런", 44_000, memo="직무 강의 결제", pattern="PLANNED")
add(date(2026, 8, 16), t(15, 40), "교보문고 강남점", 18_500, memo="도서 구매", pattern="PLANNED")
add(date(2026, 8, 16), t(14, 55), "서울교통공사", 1_550, memo="이동 (봉천→강남)")
add(date(2026, 8, 16), t(17, 20), "서울교통공사", 1_550, memo="귀가 (강남→봉천)")
add(date(2026, 7, 21), t(18, 50), "역삼 연세내과", 6_500, memo="감기 진료")
add(date(2026, 7, 21), t(19, 5), "봉천 온누리약국", 8_900, memo="처방약")
add(date(2026, 8, 27), t(19, 10), "봉천 온누리약국", 8_900, memo="상비약")
add(date(2026, 7, 18), t(16, 20), "다이소 봉천점", 12_500, memo="생활용품", pattern="PLANNED")
add(date(2026, 8, 22), t(13, 0), "정우진 (결혼식 축의금)", 100_000, ttype="TRANSFER_OUT",
    memo="대학 동기 결혼식 축의금", pattern="PLANNED")
add(date(2026, 8, 22), t(11, 30), "서울교통공사", 1_550, memo="결혼식 이동 (봉천→선릉)")
add(date(2026, 8, 22), t(15, 40), "서울교통공사", 1_550, memo="귀가 (선릉→봉천)")

add(date(2026, 9, 1), t(19, 45), "봉천 쌀국수", 10_500, memo="퇴근 후 저녁 (신규 가맹점)")
add(date(2026, 7, 14), t(19, 30), "역삼 돈까스집", 11_000, memo="야근 전 저녁")

# ---------- 4. 모임: 내가 결제 → N빵 입금 / 남이 결제 → 내가 송금 ----------
def group_paid_by_me(d, tm, merchant, total, payers):
    add(d, tm, merchant, total, memo=f"모임 {len(payers)+1}인, 내가 대표 결제 (N빵 정산 예정)", pattern="PLANNED")
    share = r100(total / (len(payers) + 1))
    for k, p in enumerate(payers):
        dd = d + timedelta(days=1 if k < 2 else 2)
        add(dd, jit(10 + 3 * k, 20, 40), p, share, direction="INCOME", ttype="TRANSFER_IN",
            memo=f"{d.month}/{d.day} 모임 N빵 입금", pattern="PLANNED")
def group_paid_by_other(d, tm, merchant_area_note, payee, share):
    add(d, tm, payee, share, ttype="TRANSFER_OUT", memo=f"모임 N빵 송금 ({merchant_area_note})", pattern="PLANNED")

group_paid_by_me(date(2026, 6, 12), t(20, 45), "역삼 이자카야", 148_000, ["김민수", "박지훈", "이하은"])
add(date(2026, 6, 12), t(23, 20), "카카오T", 17_800, memo="모임 후 택시 귀가 (역삼→봉천)")
group_paid_by_other(date(2026, 6, 27), t(22, 10), "홍대 양꼬치, 박지훈 결제", "박지훈", 42_000)
add(date(2026, 6, 27), t(18, 40), "서울교통공사", 1_550, memo="모임 이동 (봉천→홍대입구)")
add(date(2026, 6, 27), t(23, 5), "카카오T", 19_600, memo="모임 후 택시 귀가 (홍대→봉천)")
group_paid_by_me(date(2026, 7, 17), t(20, 30), "성수 브루어리", 176_000, ["김민수", "최윤서", "이하은"])
add(date(2026, 7, 17), t(23, 40), "카카오T", 23_900, memo="모임 후 택시 귀가 (성수→봉천)")
group_paid_by_other(date(2026, 7, 25), t(21, 50), "역삼 이자카야, 김민수 결제", "김민수", 38_000)
add(date(2026, 7, 25), t(18, 30), "서울교통공사", 1_550, memo="모임 이동 (봉천→역삼)")
add(date(2026, 7, 25), t(22, 30), "서울교통공사", 1_550, memo="귀가 (역삼→봉천)")
group_paid_by_me(date(2026, 8, 7), t(20, 40), "홍대 양꼬치", 132_000, ["박지훈", "최윤서", "이하은"])
add(date(2026, 8, 7), t(19, 30), "서울교통공사", 1_550, memo="모임 이동 (역삼→홍대입구)")
add(date(2026, 8, 7), t(23, 30), "카카오T", 19_200, memo="모임 후 택시 귀가 (홍대→봉천)")
group_paid_by_other(date(2026, 8, 28), t(22, 0), "성수 브루어리, 최윤서 결제", "최윤서", 44_000)
add(date(2026, 8, 28), t(23, 25), "카카오T", 23_100, memo="모임 후 택시 귀가 (성수→봉천)")

# ---------- 5. 충동 소비 (급여 직후·심야·스트레스) ----------
IMP = "IMPULSE"
add(date(2026, 6, 26), t(23, 40), "무신사", 168_000, memo="충동 구매: 급여 다음날 심야 의류 주문", pattern=IMP)
add(date(2026, 7, 8), t(22, 15), "배달의민족", 24_000, memo="충동 구매: 야식 치킨", pattern=IMP)
add(date(2026, 7, 24), t(21, 30), "쿠팡", 219_000, memo="충동 구매: 급여일 무선 이어폰", pattern=IMP)
add(date(2026, 8, 2), t(1, 10), "스팀", 65_000, memo="충동 구매: 심야 게임 세일", pattern=IMP)
add(date(2026, 8, 25), t(20, 40), "올리브영 강남점", 87_000, memo="충동 구매: 급여일 퇴근길", pattern=IMP)
add(date(2026, 8, 29), t(15, 20), "신세계백화점 강남점", 139_000, memo="충동 구매: 세일 운동화", pattern=IMP)
add(date(2026, 8, 29), t(14, 30), "서울교통공사", 1_550, memo="이동 (봉천→신논현)")
add(date(2026, 8, 29), t(17, 10), "서울교통공사", 1_550, memo="귀가 (신논현→봉천)")

# ---------- 정렬·ID·저장 ----------
rows.sort(key=lambda r: (r["transaction_date"], r["transaction_time"]))
for i, r in enumerate(rows, 1):
    r["transaction_id"] = f"TX-DEMO2-{i:04d}"
    mode = M[r["merchant"]]["mode"]; d = date.fromisoformat(r["transaction_date"])
    first = r["merchant"] not in seen; seen.add(r["merchant"])
    if mode == "MAP":      src, st = "MERCHANT_MAP", "AUTO"
    elif mode == "RULE":   src, st = "RULE", "AUTO"
    elif mode == "PERSON": src, st = ("MODEL", "PENDING") if d >= PENDING_FROM else ("USER", "CONFIRMED")
    elif first:            src, st = "MODEL", ("PENDING" if d >= PENDING_FROM else "CONFIRMED")
    else:                  src, st = "MERCHANT_MAP", "AUTO"
    r["classify_source"], r["confirm_status"] = src, st
cols = list(rows[0].keys())
out = "docs/persona_consumption_90d_v2.csv"
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print("rows", len(rows), "->", out)
