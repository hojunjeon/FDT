"""더미 데이터 생성기.

프로필 YAML(선언) + 시드 -> 금융망 API 응답 형식(FinSnapshot) + 정답(ground truth).

설계 원칙
- 엔진이 추정하는 것(요일 밀도, 금액 분포, 탄력도)과 별개로, 엔진이 모르는 요소를 섞는다:
  급여 후 소비 증가, 급여 전 절약, 돌발 대형 지출, 결제 취소, 더치페이 입금, 잔액 부족 시 결제 거절.
  그래야 시뮬레이션 검증이 순환 논증이 되지 않는다.
- 카드 청구는 금융망 실제 규칙을 따른다: 월~일 사용분을 차주 월요일 07:30 청구,
  카드별 출금 요일 16:00 에 출금 계좌에서 자동 출금. 잔액 부족이면 미결제로 남고 다음 날 재시도한다
  (금융망 실제 동작은 미확인. 가정으로 기록).
- 계좌 거래는 transactionSummary 문자열에만 가맹점 정보가 남는다 (금융망 스키마 제약).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from fdt.schemas.finapi import (
    AccountTransaction,
    AccountTransactionHistory,
    BillingMonth,
    BillingStatement,
    CardBillingStatements,
    CardTransaction,
    CardTransactionHistory,
    CreditCard,
    DemandDepositAccount,
    FinSnapshot,
    LoanAccount,
    Subscription,
)
from fdt.taxonomy.categories import (
    ENVELOPES,
    FIXED_MERCHANTS,
    MERCHANT_TO_SUBCATEGORY,
    SUBCATEGORY_TO_ENVELOPE,
    Envelope,
    fin_category_of_merchant,
)

PROFILE_DIR = Path(__file__).parent / "profiles"

# 봉투별 가맹점 풀 (가중치). 매핑 테이블에 전부 등록된 가맹점만 사용.
_ENVELOPE_MERCHANTS: dict[Envelope, list[tuple[str, float]]] = {
    Envelope.DINING: [("김밥천국", 3), ("백반집", 3), ("국밥집", 2), ("맘스터치", 2), ("버거킹", 1.5), ("서브웨이", 1.5),
                      ("한솥도시락", 2), ("본죽", 1), ("스타벅스", 3), ("메가커피", 4), ("컴포즈커피", 3), ("이디야커피", 1.5),
                      ("투썸플레이스", 1), ("배달의민족", 3), ("요기요", 1), ("쿠팡이츠", 1.5), ("호프집", 1.2), ("포차", 0.8),
                      ("이자카야", 0.6)],
    Envelope.TRANSPORT: [("지하철", 5), ("시내버스", 4), ("티머니", 2), ("카카오T", 1.2), ("우티", 0.4),
                         ("SK에너지", 0.5), ("GS칼텍스", 0.4), ("현대오일뱅크", 0.2)],
    Envelope.HEALTH: [("온누리약국", 3), ("내과의원", 2), ("치과의원", 0.5), ("피부과", 0.5), ("헬스장", 1), ("필라테스", 0.6), ("요가원", 0.3)],
    Envelope.LEISURE: [("CGV", 2), ("메가박스", 1), ("인터파크티켓", 0.6), ("야구장", 0.5), ("축구장", 0.2), ("PC방", 1.5),
                       ("스팀", 1), ("닌텐도샵", 0.4), ("야놀자", 0.5), ("여기어때", 0.3), ("에어비앤비", 0.2), ("KTX", 0.6)],
    Envelope.SHOPPING: [("쿠팡", 4), ("네이버쇼핑", 3), ("11번가", 1), ("G마켓", 1), ("무신사", 1.5), ("유니클로", 1), ("자라", 0.6),
                        ("ABC마트", 0.6), ("올리브영", 2.5), ("미용실", 1), ("네일샵", 0.4)],
    Envelope.GROCERY: [("GS25", 4), ("CU", 4), ("세븐일레븐", 2), ("이마트24", 1.5), ("이마트", 1.2), ("홈플러스", 0.8),
                       ("롯데마트", 0.6), ("코스트코", 0.3), ("다이소", 1.5), ("아트박스", 0.3)],
    Envelope.ETC: [("교보문고", 1.5), ("YES24", 1), ("인프런", 0.6), ("패스트캠퍼스", 0.3), ("알리익스프레스", 1), ("아마존", 0.4),
                   ("축의금", 0.5), ("조의금", 0.2)],
}

# 돌발 지출 가맹점 (봉투 상관없이 큰 금액)
_SHOCK_MERCHANTS: list[tuple[str, float]] = [("내과의원", 2), ("치과의원", 1.5), ("축의금", 2), ("조의금", 0.7), ("KTX", 1.5),
                                             ("야놀자", 1), ("에어비앤비", 0.8), ("쿠팡", 1.5), ("무신사", 1), ("자라", 0.6)]

# 봉투별 결제 시각 분포 (시 단위 가중치, 0~23)
_HOUR_WEIGHTS: dict[Envelope, list[float]] = {
    Envelope.DINING: [0.2, 0.1, 0, 0, 0, 0, 0.3, 1, 2, 1.5, 1, 4, 5, 2, 1.2, 1.5, 1.2, 2, 4.5, 4, 2.5, 2, 1.2, 0.6],
    Envelope.TRANSPORT: [0.2, 0.1, 0, 0, 0, 0.3, 1.5, 4, 5, 2, 1, 1, 1, 1, 1, 1, 1.2, 2, 4.5, 3.5, 2, 1.5, 1.2, 0.6],
    Envelope.HEALTH: [0, 0, 0, 0, 0, 0, 0, 0, 0.5, 2, 3, 2.5, 1, 1.5, 2.5, 2.5, 2, 1.5, 1, 0.5, 0.2, 0, 0, 0],
    Envelope.LEISURE: [0.5, 0.3, 0, 0, 0, 0, 0, 0, 0.2, 0.5, 1, 1.5, 2, 2.5, 3, 3, 3, 3, 3.5, 4, 3.5, 3, 2, 1],
    Envelope.SHOPPING: [0.5, 0.3, 0, 0, 0, 0, 0, 0.2, 0.5, 1, 1.5, 2, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5, 3, 3.5, 4, 3.5, 1.5],
    Envelope.GROCERY: [0.5, 0.2, 0, 0, 0, 0, 0.2, 1, 1.5, 1, 1, 1.5, 2, 1.5, 1.2, 1.2, 1.5, 2, 3, 3.5, 3.5, 3, 2.5, 1.2],
    Envelope.ETC: [0.2, 0, 0, 0, 0, 0, 0, 0.3, 0.8, 1.5, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1.5, 1, 0.5, 0.2],
}


def _wchoice(rng: np.random.Generator, items: list[tuple[str, float]]) -> str:
    w = np.array([x[1] for x in items], dtype=float)
    return items[int(rng.choice(len(items), p=w / w.sum()))][0]


def _lognormal(rng: np.random.Generator, median: float, sigma: float, lo: int = 500) -> int:
    v = float(rng.lognormal(mean=math.log(median), sigma=sigma))
    return max(lo, int(round(v / 100.0)) * 100)


def _hour(rng: np.random.Generator, env: Envelope) -> time:
    w = np.array(_HOUR_WEIGHTS[env], dtype=float)
    h = int(rng.choice(24, p=w / w.sum()))
    return time(h, int(rng.integers(0, 60)), int(rng.integers(0, 60)))


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _hms(t: time) -> str:
    return t.strftime("%H%M%S")


def _digits(seed: str, n: int) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return "".join(str(int(c, 16) % 10) for c in h)[:n]


def _day_of_month_or_last(d: date, day: int) -> bool:
    """해당 월에 day 가 없으면(2월 30일 등) 말일로 대체."""
    last = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return d.day == min(day, last.day)


@dataclass
class _Account:
    role: str
    rec: DemandDepositAccount
    balance: int
    txs: list[AccountTransaction] = field(default_factory=list)
    seq: int = 0

    def post(self, day: date, t: time, amount: int, kind: str, summary: str, counterpart: str = "") -> AccountTransaction | None:
        """amount 양수 입금, 음수 출금. 출금은 잔액 부족 시 None (거절)."""
        if amount < 0 and self.balance + amount < 0:
            return None
        self.balance += amount
        self.seq += 1
        deposit = amount > 0
        tx = AccountTransaction(
            transactionUniqueNo=str(self.seq),
            transactionDate=_ymd(day),
            transactionTime=_hms(t),
            transactionType="1" if deposit else "2",
            transactionTypeName=kind,
            transactionAccountNo=counterpart,
            transactionBalance=str(abs(amount)),
            transactionAfterBalance=str(self.balance),
            transactionSummary=summary,
        )
        self.txs.append(tx)
        return tx


@dataclass
class _Statement:
    week_start: date
    issued: date
    total: int
    paid_on: datetime | None = None


@dataclass
class _Card:
    rec: CreditCard
    withdrawal_weekday: int
    txs: list[CardTransaction] = field(default_factory=list)
    seq: int = 0
    statements: list[_Statement] = field(default_factory=list)

    def charge(self, day: date, t: time, merchant: str, amount: int) -> CardTransaction:
        self.seq += 1
        cid, cname = fin_category_of_merchant(merchant)
        tx = CardTransaction(
            transactionUniqueNo=str(self.seq),
            categoryId=cid,
            categoryName=cname,
            merchantId=str(int(_digits(f"m-{merchant}", 3)) + 100),
            merchantName=merchant,
            transactionDate=_ymd(day),
            transactionTime=_hms(t),
            transactionBalance=str(amount),
        )
        self.txs.append(tx)
        return tx

    def approvals_between(self, start: date, end: date) -> int:
        s, e = _ymd(start), _ymd(end)
        return sum(int(x.transactionBalance) for x in self.txs if s <= x.transactionDate <= e and x.cardStatus == "승인")

    def mark_billed(self, start: date, end: date, paid: bool) -> None:
        s, e = _ymd(start), _ymd(end)
        for x in self.txs:
            if s <= x.transactionDate <= e:
                x.billStatementsYn = "Y"
                x.billStatementsStatus = "결제완료" if paid else "미결제"


class Generator:
    def __init__(self, profile: dict[str, Any], seed: int | None = None):
        self.p = profile
        self.rng = np.random.default_rng(profile["seed"] if seed is None else seed)
        self.start: date = profile["period"]["start"]
        self.end: date = profile["period"]["end"]
        self.user_key = _digits(f"user-{profile['id']}", 32)
        self.accounts: list[_Account] = []
        self.cards: list[_Card] = []
        self.loan: LoanAccount | None = None
        self.subs: list[Subscription] = []
        self.truth: dict[str, Any] = {
            "profile_id": profile["id"], "hidden_params": profile["spending"], "income": profile["income"],
            "daily_balance": {}, "card_shortfalls": [], "declined_debits": [], "shocks": [], "cancels": [], "dutch_pays": [],
            "envelope_true_spend": {}, "income_events": [],
        }
        self._month_spent: dict[Envelope, int] = {e: 0 for e in ENVELOPES}
        self._month_budget: dict[Envelope, int] = {}
        self._last_income: date | None = None
        self._irregular_plan: dict[date, int] = {}
        self._setup()

    # ------------------------------------------------------------------ setup
    def _setup(self) -> None:
        p = self.p
        opened = self.start - timedelta(days=int(self.rng.integers(400, 1500)))
        for i, a in enumerate(p["accounts"]):
            acc_no = a["bankCode"] + _digits(f"acc-{p['id']}-{i}", 13)
            rec = DemandDepositAccount(
                bankCode=a["bankCode"], bankName=a["bankName"], userName=p["name"], accountNo=acc_no,
                accountName=a["accountName"], accountCreatedDate=_ymd(opened), accountExpiryDate=_ymd(opened.replace(year=opened.year + 5)),
                accountBalance=str(a["opening_balance"]),
            )
            self.accounts.append(_Account(role=a["role"], rec=rec, balance=a["opening_balance"]))
        primary = self.primary.rec.accountNo
        for i, c in enumerate(p["cards"]):
            card_no = c["issuerCode"] + _digits(f"card-{p['id']}-{i}", 12)
            rec = CreditCard(
                cardNo=card_no, cvc=_digits(f"cvc-{p['id']}-{i}", 3), cardUniqueNo=f"{c['issuerCode']}-{_digits(f'cu-{p['id']}-{i}', 15)}",
                cardIssuerCode=c["issuerCode"], cardIssuerName=c["issuerName"], cardName=c["cardName"],
                cardDescription=c.get("description", ""), cardExpiryDate=_ymd(opened.replace(year=opened.year + 5)),
                withdrawalAccountNo=primary, withdrawalDate=str(c["withdrawal_weekday"] + 1),
            )
            self.cards.append(_Card(rec=rec, withdrawal_weekday=c["withdrawal_weekday"]))
        if p.get("loan"):
            l = p["loan"]
            ld = self.start - timedelta(days=int(self.rng.integers(200, 700)))
            self.loan = LoanAccount(
                accountNo=l["bankCode"] + _digits(f"loan-{p['id']}", 13), accountName=l["accountName"], status="상환중",
                accountTypeUniqueNo=_digits(f"loanprod-{p['id']}", 20), loanPeriod=36, loanDate=_ymd(ld),
                maturityDate=_ymd(ld.replace(year=ld.year + 3)), loanBalance=str(l["balance"]), interestRate=float(l["rate"]),
                withdrawalAccountNo=primary,
            )
        # 구독(정기결제) 목록: 고정비 중 kind=구독, via=card
        for i, f in enumerate(f for f in p["fixed"] if f["kind"] == "구독"):
            nxt = self._next_due(self.end + timedelta(days=1), f["day"])
            self.subs.append(Subscription(
                subscriptionId=f"SUB{_ymd(self.start)}{_digits(f'sub-{p['id']}-{i}', 9)}", subscriptionName=f["merchant"],
                paymentAmount=str(f["amount"]), billingCycle="MONTHLY", nextPaymentDate=_ymd(nxt), status="ACTIVE",
                cardNo=self.cards[i % len(self.cards)].rec.cardNo, paymentDay=str(f["day"]),
            ))
        # 봉투별 "월 예산"(생성기 내부용, 잔여율 계산에만 사용): 기대 지출 × 1.05
        for env, cfg in self._env_cfgs().items():
            mean_amt = math.exp(math.log(cfg["amount_median"]) + cfg["sigma"] ** 2 / 2)
            self._month_budget[env] = int(cfg["daily_rate"] * 30 * mean_amt * 1.05)
        if p["income"]["type"] == "irregular":
            self._plan_irregular_income()

    def _env_cfgs(self) -> dict[Envelope, dict[str, Any]]:
        return {Envelope(k): v for k, v in self.p["spending"]["envelopes"].items()}

    @property
    def primary(self) -> _Account:
        return next(a for a in self.accounts if a.role == "primary")

    @property
    def emergency(self) -> _Account | None:
        return next((a for a in self.accounts if a.role == "emergency"), None)

    @staticmethod
    def _next_due(from_day: date, dom: int) -> date:
        d = from_day
        for _ in range(62):
            if _day_of_month_or_last(d, dom):
                return d
            d += timedelta(days=1)
        return d

    def _plan_irregular_income(self) -> None:
        inc = self.p["income"]
        lo, hi = inc["payments_per_month"]
        m = self.start.replace(day=1)
        while m <= self.end:
            nxt = (m + timedelta(days=32)).replace(day=1)
            n = int(self.rng.integers(lo, hi + 1))
            days = sorted(self.rng.choice(range(1, 29), size=n, replace=False))
            raw = self.rng.lognormal(mean=0, sigma=inc["amount_sigma"], size=n)
            raw = raw / raw.sum() * inc["monthly_mean"] * float(self.rng.uniform(0.7, 1.3))
            for d, a in zip(days, raw):
                self._irregular_plan[m.replace(day=int(d))] = int(round(a / 10000) * 10000)
            m = nxt

    # ------------------------------------------------------------------ run
    def run(self) -> tuple[FinSnapshot, dict[str, Any]]:
        d = self.start
        while d <= self.end:
            if d.day == 1:
                for e in ENVELOPES:
                    self._month_spent[e] = 0
            self._income(d)
            self._fixed(d)
            self._card_billing(d)
            self._spending(d)
            self._shock(d)
            self._cancels_and_dutch(d)
            self.truth["daily_balance"][_ymd(d)] = {a.rec.accountNo: a.balance for a in self.accounts}
            d += timedelta(days=1)
        return self._snapshot(), self.truth

    def _income(self, d: date) -> None:
        inc = self.p["income"]
        amt = 0
        if inc["type"] == "salary":
            if _day_of_month_or_last(d, inc["payday"]):
                amt = int(inc["amount"])
        else:
            amt = self._irregular_plan.get(d, 0)
        if amt <= 0:
            return
        self.primary.post(d, time(9, 12, 0) if inc["type"] == "salary" else time(int(self.rng.integers(10, 18)), 30, 0),
                          amt, "입금(이체)", inc["summary"])
        self.truth["income_events"].append({"date": _ymd(d), "amount": amt})
        self._last_income = d
        et = int(inc.get("emergency_transfer", 0) or 0)
        if et > 0 and self.emergency is not None:
            if self.primary.post(d, time(9, 30, 0), -et, "출금(이체)", "비상금이체 세이프박스", self.emergency.rec.accountNo):
                self.emergency.post(d, time(9, 30, 0), et, "입금(이체)", "비상금이체", self.primary.rec.accountNo)

    def _fixed(self, d: date) -> None:
        for f in self.p["fixed"]:
            if not _day_of_month_or_last(d, f["day"]):
                continue
            if f["via"] == "account":
                self.primary.post(d, time(8, 5, 0), -int(f["amount"]), "출금(이체)", f["summary"])
            else:
                card = self.cards[int(_digits(f"fx-{f['merchant']}", 2)) % len(self.cards)]
                card.charge(d, time(4, 10, 0), f["merchant"], int(f["amount"]))
        if self.loan is not None and _day_of_month_or_last(d, self.p["loan"]["interest_day"]):
            interest = int(round(int(self.loan.loanBalance) * float(self.loan.interestRate) / 100 / 12 / 10) * 10)
            self.primary.post(d, time(10, 0, 0), -interest, "출금(이체)", self.p["loan"]["summary"])

    def _card_billing(self, d: date) -> None:
        # 월요일 07:30 청구서 발행 (직전 월~일)
        if d.weekday() == 0 and d > self.start:
            ws, we = d - timedelta(days=7), d - timedelta(days=1)
            for c in self.cards:
                total = c.approvals_between(ws, we)
                if total > 0:
                    c.statements.append(_Statement(week_start=ws, issued=d, total=total))
        # 출금 요일 16:00 (미결제 청구서는 매일 재시도 - 가정)
        for c in self.cards:
            for st in c.statements:
                if st.paid_on is not None or d < st.issued:
                    continue
                due_today = d.weekday() == c.withdrawal_weekday and d >= st.issued
                overdue = d > st.issued and (d - st.issued).days >= 7  # 첫 출금일을 넘긴 미결제
                if not (due_today or overdue):
                    continue
                tx = self.primary.post(d, time(16, 0, 0), -st.total, "출금(이체)", f"카드대금 {c.rec.cardIssuerName}")
                if tx is None:
                    self.truth["card_shortfalls"].append({"date": _ymd(d), "card": c.rec.cardNo, "amount": st.total,
                                                          "statement_issued": _ymd(st.issued), "balance": self.primary.balance})
                else:
                    st.paid_on = datetime.combine(d, time(16, 0, 0))
                    c.mark_billed(st.week_start, st.week_start + timedelta(days=6), paid=True)

    def _budget_pressure(self, env: Envelope) -> float:
        remaining_ratio = 1 - self._month_spent[env] / max(1, self._month_budget[env])
        return float(self.p["spending"]["elasticity"]) if remaining_ratio < 0.2 else 1.0

    def _cycle_mult(self, d: date) -> float:
        sp = self.p["spending"]
        m = 1.0
        if self._last_income is not None and 0 <= (d - self._last_income).days < 7:
            m *= float(sp["payday_boost"])
        inc = self.p["income"]
        if inc["type"] == "salary":
            nxt = self._next_due(d, inc["payday"])
            if 0 < (nxt - d).days <= 5:
                m *= float(sp["pre_payday_damp"])
        return m

    def _spend_one(self, d: date, env: Envelope, merchant: str, amount: int, t: time) -> None:
        via_card = self.cards and self.rng.random() < float(self.p["spending"]["card_share"])
        if via_card:
            card = self.cards[int(self.rng.integers(0, len(self.cards)))]
            card.charge(d, t, merchant, amount)
        else:
            tx = self.primary.post(d, t, -amount, "출금", f"{merchant} 체크카드")
            if tx is None:
                self.truth["declined_debits"].append({"date": _ymd(d), "merchant": merchant, "amount": amount})
                return
        self._month_spent[env] += amount
        self.truth["envelope_true_spend"].setdefault(_ymd(d)[:6], {}).setdefault(str(env), 0)
        self.truth["envelope_true_spend"][_ymd(d)[:6]][str(env)] += amount

    def _spending(self, d: date) -> None:
        cm = self._cycle_mult(d)
        for env, cfg in self._env_cfgs().items():
            rate = cfg["daily_rate"] * cfg["weekday"][d.weekday()] * cm * self._budget_pressure(env)
            n = int(self.rng.poisson(rate))
            for _ in range(n):
                merchant = _wchoice(self.rng, _ENVELOPE_MERCHANTS[env])
                amount = _lognormal(self.rng, cfg["amount_median"], cfg["sigma"])
                self._spend_one(d, env, merchant, amount, _hour(self.rng, env))

    def _shock(self, d: date) -> None:
        sh = self.p["spending"]["shocks"]
        if self.rng.random() >= float(sh["daily_prob"]):
            return
        merchant = _wchoice(self.rng, _SHOCK_MERCHANTS)
        env = SUBCATEGORY_TO_ENVELOPE[MERCHANT_TO_SUBCATEGORY[merchant]]
        amount = _lognormal(self.rng, sh["amount_median"], sh["sigma"], lo=30000)
        self._spend_one(d, env, merchant, amount, _hour(self.rng, env))
        self.truth["shocks"].append({"date": _ymd(d), "merchant": merchant, "amount": amount})

    def _cancels_and_dutch(self, d: date) -> None:
        sp = self.p["spending"]
        today = _ymd(d)
        # 카드 결제 취소: 당일 승인 건 중 일부
        for c in self.cards:
            for tx in [x for x in c.txs if x.transactionDate == today and x.cardStatus == "승인"]:
                if tx.merchantName in FIXED_MERCHANTS:
                    continue
                if self.rng.random() < float(sp["cancel_prob"]):
                    tx.cardStatus = "취소"
                    env = SUBCATEGORY_TO_ENVELOPE[MERCHANT_TO_SUBCATEGORY[tx.merchantName]]
                    self._month_spent[env] -= int(tx.transactionBalance)
                    self.truth["envelope_true_spend"][today[:6]][str(env)] -= int(tx.transactionBalance)
                    self.truth["cancels"].append({"date": today, "merchant": tx.merchantName, "amount": int(tx.transactionBalance)})
        # 더치페이: 당일 외식 3만원 이상 결제 뒤 친구 입금
        dining = [x for c in self.cards for x in c.txs if x.transactionDate == today and x.cardStatus == "승인"
                  and MERCHANT_TO_SUBCATEGORY.get(x.merchantName) in ("음식점", "주점") and int(x.transactionBalance) >= 30000]
        dining += [x for x in self.primary.txs if x.transactionDate == today and x.transactionType == "2"
                   and x.transactionSummary.split(" ")[0] in MERCHANT_TO_SUBCATEGORY
                   and MERCHANT_TO_SUBCATEGORY[x.transactionSummary.split(" ")[0]] in ("음식점", "주점") and int(x.transactionBalance) >= 30000]
        for x in dining:
            if self.rng.random() < float(sp["dutch_pay_prob"]):
                n = int(self.rng.integers(2, 5))
                share = int(round(int(x.transactionBalance) * (n - 1) / n / 100) * 100)
                self.primary.post(d, time(int(self.rng.integers(19, 24)), 0, 0), share, "입금(이체)", "더치페이 친구")
                self.truth["dutch_pays"].append({"date": today, "amount": share})

    # ------------------------------------------------------------------ output
    def _snapshot(self) -> FinSnapshot:
        for a in self.accounts:
            a.rec.accountBalance = str(a.balance)
            a.rec.lastTransactionDate = a.txs[-1].transactionDate if a.txs else ""
        card_hist, billing = [], []
        for c in self.cards:
            unpaid = sum(s.total for s in c.statements if s.paid_on is None)
            last_issue = max((s.issued for s in c.statements), default=self.start)
            unbilled = c.approvals_between(last_issue, self.end) if c.statements else c.approvals_between(self.start, self.end)
            card_hist.append(CardTransactionHistory(
                cardIssuerCode=c.rec.cardIssuerCode, cardIssuerName=c.rec.cardIssuerName, cardName=c.rec.cardName,
                cardNo=c.rec.cardNo, estimatedBalance=str(unpaid + unbilled), transactionList=c.txs,
            ))
            months: dict[str, list[BillingStatement]] = {}
            for s in c.statements:
                months.setdefault(_ymd(s.issued)[:6], []).append(BillingStatement(
                    billingWeek=str((s.issued.day - 1) // 7 + 1), billingDate=_ymd(s.issued), totalBalance=str(s.total),
                    status="결제완료" if s.paid_on else "미결제",
                    paymentDate=_ymd(s.paid_on.date()) if s.paid_on else "", paymentTime=_hms(s.paid_on.time()) if s.paid_on else "",
                ))
            billing.append(CardBillingStatements(cardNo=c.rec.cardNo, months=[BillingMonth(billingMonth=m, billingList=l) for m, l in sorted(months.items())]))
        return FinSnapshot(
            userKey=self.user_key, userName=self.p["name"], generatedAt=datetime.now().isoformat(timespec="seconds"),
            accounts=[a.rec for a in self.accounts],
            accountTransactions=[AccountTransactionHistory(accountNo=a.rec.accountNo, totalCount=str(len(a.txs)), list=a.txs) for a in self.accounts],
            cards=[c.rec for c in self.cards], cardTransactions=card_hist, billingStatements=billing,
            subscriptions=self.subs, loans=[self.loan] if self.loan else [],
        )


def load_profile(name_or_path: str) -> dict[str, Any]:
    p = Path(name_or_path)
    if not p.exists():
        p = PROFILE_DIR / f"{name_or_path}.yaml"
    with open(p, encoding="utf-8") as f:
        prof = yaml.safe_load(f)
    for k in ("start", "end"):
        v = prof["period"][k]
        prof["period"][k] = v if isinstance(v, date) else date.fromisoformat(str(v))
    return prof


def list_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))


def generate(profile: str, out_dir: Path, seed: int | None = None, end: date | None = None) -> tuple[Path, dict[str, Any]]:
    prof = load_profile(profile)
    if end is not None:
        prof["period"]["end"] = end
    snap, truth = Generator(prof, seed=seed).run()
    d = out_dir / prof["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "snapshot.json").write_text(snap.model_dump_json(indent=1), encoding="utf-8")
    (d / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (d / "profile.yaml").write_text(yaml.safe_dump(prof, allow_unicode=True, sort_keys=False, default_flow_style=None), encoding="utf-8")
    return d, {
        "profile": prof["id"], "days": (prof["period"]["end"] - prof["period"]["start"]).days + 1,
        "account_tx": sum(len(h.list) for h in snap.accountTransactions),
        "card_tx": sum(len(h.transactionList) for h in snap.cardTransactions),
        "statements": sum(len(m.billingList) for b in snap.billingStatements for m in b.months),
        "card_shortfall_days": len(truth["card_shortfalls"]),
        "card_shortfall_statements": len({(x["card"], x["statement_issued"]) for x in truth["card_shortfalls"]}), "declined_debits": len(truth["declined_debits"]),
        "final_balances": {a.accountName: int(a.accountBalance) for a in snap.accounts},
    }
