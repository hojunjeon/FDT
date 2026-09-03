"""KeyFin 분류 체계.

- 7대 예산 봉투(Envelope)와 KeyFin 세분류(Subcategory)
- 가맹점명 -> 세분류 매핑 테이블 (FR-TXN-02, FR-TXN-10)
- 금융망 카테고리 ID (SSAFY 금융망 가맹점 카테고리)

봉투는 '소비'만 담는다. 급여·월세·통신·구독·보험·대출이자·카드대금 출금은
봉투가 아닌 별도 흐름(Flow)으로 분류한다 (FDT.md '약정 지출 큐').
"""
from __future__ import annotations

from enum import StrEnum


class Envelope(StrEnum):
    DINING = "외식"
    TRANSPORT = "교통비"
    HEALTH = "의료·건강"
    LEISURE = "취미·여가"
    SHOPPING = "쇼핑"
    GROCERY = "편의점·마트·잡화"
    ETC = "기타"


ENVELOPES: tuple[Envelope, ...] = tuple(Envelope)

# 재배분 시 손대지 않는 필수 봉투 (FDT-ANL-02)
ESSENTIAL_ENVELOPES: frozenset[Envelope] = frozenset({Envelope.TRANSPORT, Envelope.HEALTH, Envelope.GROCERY})
FLEXIBLE_ENVELOPES: tuple[Envelope, ...] = (Envelope.LEISURE, Envelope.SHOPPING, Envelope.DINING, Envelope.ETC)


class Flow(StrEnum):
    """봉투 밖 거래 종류."""

    INCOME = "수입"
    FIXED = "고정비"           # 월세, 통신, 보험, 구독, 대출이자
    CARD_BILL = "카드대금"      # 카드 청구서 출금 (봉투 이중 차감 방지)
    TRANSFER_INTERNAL = "내계좌이체"
    REFUND = "환불·취소"
    SPEND = "소비"             # 봉투 차감 대상


# 세분류 -> 봉투
SUBCATEGORY_TO_ENVELOPE: dict[str, Envelope] = {
    "음식점": Envelope.DINING,
    "카페": Envelope.DINING,
    "배달": Envelope.DINING,
    "주점": Envelope.DINING,
    "대중교통": Envelope.TRANSPORT,
    "택시": Envelope.TRANSPORT,
    "주유": Envelope.TRANSPORT,
    "병원·약국": Envelope.HEALTH,
    "운동·헬스": Envelope.HEALTH,
    "영화·공연·전시": Envelope.LEISURE,
    "스포츠 관람": Envelope.LEISURE,
    "게임·콘텐츠": Envelope.LEISURE,
    "여행·숙박": Envelope.LEISURE,
    "패션·잡화": Envelope.SHOPPING,
    "뷰티": Envelope.SHOPPING,
    "온라인 쇼핑": Envelope.SHOPPING,
    "편의점": Envelope.GROCERY,
    "마트": Envelope.GROCERY,
    "생활용품": Envelope.GROCERY,
    "교육": Envelope.ETC,
    "해외 결제": Envelope.ETC,
    "경조사·기타": Envelope.ETC,
}

# 금융망 카테고리 (요구사항명세 'SSAFY 금융망 가맹점 카테고리')
FIN_CATEGORY: dict[str, tuple[str, str]] = {
    "주유": ("CG-3fa85f6425e811e", "주유"),
    "대형마트": ("CG-4fa85f6425ad1d3", "대형마트"),
    "교통": ("CG-4fa85f6455cad4a", "교통"),
    "교육/육아": ("CG-6dd85f6425ez11o", "교육/육아"),
    "통신": ("CG-7fa85f6425bc311", "통신"),
    "해외": ("CG-8fa85f6425e1123", "해외"),
    "생활": ("CG-9ca85f66311a23d", "생활"),
}

# 세분류 -> 금융망 등록 업종 (형식상)
SUBCATEGORY_TO_FIN: dict[str, str] = {
    "대중교통": "교통", "택시": "교통", "주유": "주유",
    "마트": "대형마트", "교육": "교육/육아", "해외 결제": "해외",
}

# 가맹점명 -> 세분류. 시딩 가맹점 전부 등록 (매핑 우선 조회, FDT-INP-01)
MERCHANT_TO_SUBCATEGORY: dict[str, str] = {
    # 외식
    "백반집": "음식점", "김밥천국": "음식점", "버거킹": "음식점", "맘스터치": "음식점",
    "한솥도시락": "음식점", "본죽": "음식점", "서브웨이": "음식점", "국밥집": "음식점",
    "스타벅스": "카페", "메가커피": "카페", "투썸플레이스": "카페", "이디야커피": "카페", "컴포즈커피": "카페",
    "배달의민족": "배달", "요기요": "배달", "쿠팡이츠": "배달",
    "호프집": "주점", "포차": "주점", "이자카야": "주점",
    # 교통비
    "지하철": "대중교통", "시내버스": "대중교통", "티머니": "대중교통",
    "카카오T": "택시", "우티": "택시",
    "SK에너지": "주유", "GS칼텍스": "주유", "현대오일뱅크": "주유",
    # 의료·건강
    "내과의원": "병원·약국", "온누리약국": "병원·약국", "치과의원": "병원·약국", "피부과": "병원·약국",
    "헬스장": "운동·헬스", "필라테스": "운동·헬스", "요가원": "운동·헬스",
    # 취미·여가
    "CGV": "영화·공연·전시", "메가박스": "영화·공연·전시", "인터파크티켓": "영화·공연·전시",
    "야구장": "스포츠 관람", "축구장": "스포츠 관람",
    "PC방": "게임·콘텐츠", "스팀": "게임·콘텐츠", "닌텐도샵": "게임·콘텐츠",
    "야놀자": "여행·숙박", "여기어때": "여행·숙박", "에어비앤비": "여행·숙박", "KTX": "여행·숙박",
    # 쇼핑
    "무신사": "패션·잡화", "ABC마트": "패션·잡화", "유니클로": "패션·잡화", "자라": "패션·잡화",
    "올리브영": "뷰티", "미용실": "뷰티", "네일샵": "뷰티",
    "쿠팡": "온라인 쇼핑", "네이버쇼핑": "온라인 쇼핑", "11번가": "온라인 쇼핑", "G마켓": "온라인 쇼핑",
    # 편의점·마트·잡화
    "GS25": "편의점", "CU": "편의점", "세븐일레븐": "편의점", "이마트24": "편의점",
    "이마트": "마트", "홈플러스": "마트", "코스트코": "마트", "롯데마트": "마트",
    "다이소": "생활용품", "아트박스": "생활용품",
    # 기타
    "인프런": "교육", "교보문고": "교육", "YES24": "교육", "패스트캠퍼스": "교육",
    "알리익스프레스": "해외 결제", "아마존": "해외 결제",
    "축의금": "경조사·기타", "조의금": "경조사·기타",
}

# 고정비 가맹점/요약 키워드 (봉투 아님)
FIXED_MERCHANTS: dict[str, str] = {
    "SKT": "통신", "KT": "통신", "LG유플러스": "통신",
    "넷플릭스": "구독", "유튜브프리미엄": "구독", "스포티파이": "구독", "쿠팡와우": "구독",
    "왓챠": "구독", "ChatGPT Plus": "구독", "멜론": "구독", "디즈니플러스": "구독",
    "삼성화재": "보험", "현대해상": "보험", "메리츠화재": "보험",
}

# 계좌 거래 요약(transactionSummary)에서 흐름을 판별하는 키워드
SUMMARY_KEYWORDS: dict[str, Flow] = {
    "급여": Flow.INCOME, "월급": Flow.INCOME, "정산금": Flow.INCOME, "용역대금": Flow.INCOME,
    "프리랜서": Flow.INCOME, "외주": Flow.INCOME, "이자입금": Flow.INCOME,
    "카드대금": Flow.CARD_BILL, "카드청구": Flow.CARD_BILL,
    "월세": Flow.FIXED, "관리비": Flow.FIXED, "대출이자": Flow.FIXED, "대출원리금": Flow.FIXED,
    "비상금이체": Flow.TRANSFER_INTERNAL, "내계좌": Flow.TRANSFER_INTERNAL,
    "취소": Flow.REFUND, "환불": Flow.REFUND, "더치페이": Flow.REFUND,
}


def envelope_of(subcategory: str) -> Envelope | None:
    return SUBCATEGORY_TO_ENVELOPE.get(subcategory)


def fin_category_of_merchant(merchant: str) -> tuple[str, str]:
    """가맹점을 금융망 카테고리(ID, 명)로. 미등록/기타는 '생활'."""
    if FIXED_MERCHANTS.get(merchant) == "통신":
        return FIN_CATEGORY["통신"]
    sub = MERCHANT_TO_SUBCATEGORY.get(merchant)
    key = SUBCATEGORY_TO_FIN.get(sub or "", "생활")
    return FIN_CATEGORY[key]
