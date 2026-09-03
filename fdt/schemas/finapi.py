"""SSAFY 금융망 API 응답 REC 스키마 (필드명 원본 그대로).

더미 데이터는 이 형식으로 생성되고, 원장 인입(ingest)은 이 형식만 읽는다.
나중에 LIVE 금융망 응답을 그대로 흘려 넣어도 동작해야 한다.

금융망은 숫자(Long)를 문자열로 내려주므로 str 로 받고 인입 단계에서 int 변환한다.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Rec(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class DemandDepositAccount(_Rec):
    """계좌 목록 조회 REC[]"""

    bankCode: str
    bankName: str
    userName: str
    accountNo: str
    accountName: str
    accountTypeCode: str = "1"
    accountTypeName: str = "수시입출금"
    accountCreatedDate: str
    accountExpiryDate: str
    dailyTransferLimit: str = "500000000"
    oneTimeTransferLimit: str = "100000000"
    accountBalance: str
    lastTransactionDate: str = ""
    currency: str = "KRW"


class AccountTransaction(_Rec):
    """계좌 거래 내역 조회 REC.list[]"""

    transactionUniqueNo: str
    transactionDate: str        # YYYYMMDD
    transactionTime: str        # HHMMSS
    transactionType: str        # 1: 입금, 2: 출금
    transactionTypeName: str    # 입금, 출금, 입금(이체), 출금(이체)
    transactionAccountNo: str = ""
    transactionBalance: str
    transactionAfterBalance: str
    transactionSummary: str = ""
    transactionMemo: str = ""


class AccountTransactionHistory(_Rec):
    """계좌 거래 내역 조회 REC (계좌번호는 요청에만 있어 accountNo 를 덧붙여 저장)"""

    accountNo: str
    totalCount: str
    list: list[AccountTransaction]


class CreditCard(_Rec):
    """내 카드 목록 조회 REC[]"""

    cardNo: str
    cvc: str
    cardUniqueNo: str
    cardIssuerCode: str
    cardIssuerName: str
    cardName: str
    baselinePerformance: str = "0"
    maxBenefitLimit: str = "0"
    cardDescription: str = ""
    cardExpiryDate: str
    withdrawalAccountNo: str
    withdrawalDate: str  # 요일: 월1 화2 수3 목4 금5 토6 일7


class CardTransaction(_Rec):
    """카드 결제 내역 조회 REC.transactionList[]"""

    transactionUniqueNo: str
    categoryId: str
    categoryName: str
    merchantId: str
    merchantName: str
    transactionDate: str
    transactionTime: str
    transactionBalance: str
    cardStatus: str = "승인"            # 승인, 취소
    billStatementsYn: str = "N"
    billStatementsStatus: str = "미결제"  # 미결제, 결제완료


class CardTransactionHistory(_Rec):
    """카드 결제 내역 조회 REC"""

    cardIssuerCode: str
    cardIssuerName: str
    cardName: str
    cardNo: str
    estimatedBalance: str
    transactionList: list[CardTransaction]


class BillingStatement(_Rec):
    """청구서 조회 REC.billingList[]  (주 단위: 월~일 사용분, 차주 월 07:30 발행)"""

    billingWeek: str
    billingDate: str
    totalBalance: str
    status: str  # 결제완료, 미결제
    paymentDate: str = ""
    paymentTime: str = ""


class BillingMonth(_Rec):
    billingMonth: str
    billingList: list[BillingStatement]


class CardBillingStatements(_Rec):
    cardNo: str
    months: list[BillingMonth]


class Subscription(_Rec):
    """정기결제 목록 조회 REC.subscriptions[]"""

    subscriptionId: str
    subscriptionName: str
    paymentAmount: str
    billingCycle: str = "MONTHLY"
    dailyAmount: str | None = None
    nextPaymentDate: str
    status: str = "ACTIVE"
    cardNo: str = ""
    paymentDay: str = ""


class LoanAccount(_Rec):
    """대출 상품 가입 목록 조회 REC[]"""

    accountNo: str
    accountName: str
    status: str = "상환중"
    accountTypeUniqueNo: str = ""
    loanPeriod: int
    loanDate: str
    maturityDate: str
    loanBalance: str
    interestRate: float
    withdrawalAccountNo: str


class FinSnapshot(BaseModel):
    """한 사용자의 금융망 조회 결과 묶음 (시딩 파일 1세트)."""

    model_config = ConfigDict(extra="allow")

    userKey: str
    userName: str
    generatedAt: str
    accounts: list[DemandDepositAccount]
    accountTransactions: list[AccountTransactionHistory]
    cards: list[CreditCard]
    cardTransactions: list[CardTransactionHistory]
    billingStatements: list[CardBillingStatements]
    subscriptions: list[Subscription]
    loans: list[LoanAccount]
