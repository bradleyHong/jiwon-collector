"""
전국 226개 시군구를 sources.yaml에 일괄 추가.
대구 8개 시·군·구는 이미 있어서 218개만 append.

URL은 표준 영문 도메인 패턴 (www.<roman>.go.kr).
일부는 시 도메인 산하라 안 맞을 수 있음.
다음 수집 후 reports/latest.md의 Source Errors 섹션 보고 수정.
"""

from pathlib import Path
from typing import Iterable

# (id, 영문도메인, 한글이름) 튜플로 관리
REGIONS: dict[str, dict] = {
    "seoul": {
        "name": "서울",
        "districts": [
            ("jongno", "종로구"), ("junggu_seoul", "중구"),
            ("yongsan", "용산구"), ("seongdong", "성동구"),
            ("gwangjin", "광진구"), ("ddm", "동대문구"),
            ("jungnang", "중랑구"), ("seongbuk", "성북구"),
            ("gangbuk", "강북구"), ("dobong", "도봉구"),
            ("nowon", "노원구"), ("ep", "은평구"),
            ("sdm", "서대문구"), ("mapo", "마포구"),
            ("yangcheon", "양천구"), ("gangseo_seoul", "강서구"),
            ("guro", "구로구"), ("geumcheon", "금천구"),
            ("ydp", "영등포구"), ("dongjak", "동작구"),
            ("gwanak", "관악구"), ("seocho", "서초구"),
            ("gangnam", "강남구"), ("songpa", "송파구"),
            ("gangdong", "강동구"),
        ],
    },
    "busan": {
        "name": "부산",
        "districts": [
            ("junggu_busan", "중구"), ("seogu_busan", "서구"),
            ("donggu_busan", "동구"), ("yeongdo", "영도구"),
            ("busanjin", "부산진구"), ("dongnae", "동래구"),
            ("namgu_busan", "남구"), ("bukgu_busan", "북구"),
            ("haeundae", "해운대구"), ("saha", "사하구"),
            ("geumjeong", "금정구"), ("gangseo_busan", "강서구"),
            ("yeonje", "연제구"), ("suyeong", "수영구"),
            ("sasang", "사상구"), ("gijang", "기장군"),
        ],
    },
    # 대구 8개는 이미 있음
    "incheon": {
        "name": "인천",
        "districts": [
            ("junggu_incheon", "중구"), ("donggu_incheon", "동구"),
            ("michuhol", "미추홀구"), ("yeonsu", "연수구"),
            ("namdong", "남동구"), ("bupyeong", "부평구"),
            ("gyeyang", "계양구"), ("seogu_incheon", "서구"),
            ("ganghwa", "강화군"), ("ongjin", "옹진군"),
        ],
    },
    "gwangju": {
        "name": "광주",
        "districts": [
            ("donggu_gwangju", "동구"), ("seogu_gwangju", "서구"),
            ("namgu_gwangju", "남구"), ("bukgu_gwangju", "북구"),
            ("gwangsan", "광산구"),
        ],
    },
    "daejeon": {
        "name": "대전",
        "districts": [
            ("donggu_daejeon", "동구"), ("junggu_daejeon", "중구"),
            ("seogu_daejeon", "서구"), ("yuseong", "유성구"),
            ("daedeok", "대덕구"),
        ],
    },
    "ulsan": {
        "name": "울산",
        "districts": [
            ("junggu_ulsan", "중구"), ("namgu_ulsan", "남구"),
            ("donggu_ulsan", "동구"), ("bukgu_ulsan", "북구"),
            ("uljugun", "울주군"),
        ],
    },
    "gg": {
        "name": "경기",
        "districts": [
            ("suwon", "수원시"), ("seongnam", "성남시"),
            ("uijeongbu", "의정부시"), ("anyang", "안양시"),
            ("bucheon", "부천시"), ("gwangmyeong", "광명시"),
            ("pyeongtaek", "평택시"), ("ddc", "동두천시"),
            ("ansan", "안산시"), ("goyang", "고양시"),
            ("gwacheon", "과천시"), ("guri", "구리시"),
            ("nyj", "남양주시"), ("osan", "오산시"),
            ("siheung", "시흥시"), ("gunpo", "군포시"),
            ("uiwang", "의왕시"), ("hanam", "하남시"),
            ("yongin", "용인시"), ("paju", "파주시"),
            ("icheon", "이천시"), ("anseong", "안성시"),
            ("gimpo", "김포시"), ("hwaseong", "화성시"),
            ("gwangju_gg", "광주시"), ("yangju", "양주시"),
            ("pocheon", "포천시"), ("yeoju", "여주시"),
            ("yeoncheon", "연천군"), ("gapyeong", "가평군"),
            ("yangpyeong", "양평군"),
        ],
    },
    "gw": {
        "name": "강원",
        "districts": [
            ("chuncheon", "춘천시"), ("wonju", "원주시"),
            ("gangneung", "강릉시"), ("donghae", "동해시"),
            ("taebaek", "태백시"), ("sokcho", "속초시"),
            ("samcheok", "삼척시"), ("hongcheon", "홍천군"),
            ("hoengseong", "횡성군"), ("yeongwol", "영월군"),
            ("pyeongchang", "평창군"), ("jeongseon", "정선군"),
            ("cheorwon", "철원군"), ("hwacheon", "화천군"),
            ("yanggu", "양구군"), ("inje", "인제군"),
            ("goseong_gw", "고성군"), ("yangyang", "양양군"),
        ],
    },
    "cb": {
        "name": "충북",
        "districts": [
            ("cheongju", "청주시"), ("chungju", "충주시"),
            ("jecheon", "제천시"), ("boeun", "보은군"),
            ("okcheon", "옥천군"), ("yeongdong", "영동군"),
            ("jeungpyeong", "증평군"), ("jincheon", "진천군"),
            ("goesan", "괴산군"), ("eumseong", "음성군"),
            ("danyang", "단양군"),
        ],
    },
    "cn": {
        "name": "충남",
        "districts": [
            ("cheonan", "천안시"), ("gongju", "공주시"),
            ("boryeong", "보령시"), ("asan", "아산시"),
            ("seosan", "서산시"), ("nonsan", "논산시"),
            ("gyeryong", "계룡시"), ("dangjin", "당진시"),
            ("geumsan", "금산군"), ("buyeo", "부여군"),
            ("seocheon", "서천군"), ("cheongyang", "청양군"),
            ("hongseong", "홍성군"), ("yesan", "예산군"),
            ("taean", "태안군"),
        ],
    },
    "jb": {
        "name": "전북",
        "districts": [
            ("jeonju", "전주시"), ("gunsan", "군산시"),
            ("iksan", "익산시"), ("jeongeup", "정읍시"),
            ("namwon", "남원시"), ("gimje", "김제시"),
            ("wanju", "완주군"), ("jinan", "진안군"),
            ("muju", "무주군"), ("jangsu", "장수군"),
            ("imsil", "임실군"), ("sunchang", "순창군"),
            ("gochang", "고창군"), ("buan", "부안군"),
        ],
    },
    "jn": {
        "name": "전남",
        "districts": [
            ("mokpo", "목포시"), ("yeosu", "여수시"),
            ("suncheon", "순천시"), ("naju", "나주시"),
            ("gwangyang", "광양시"), ("damyang", "담양군"),
            ("gokseong", "곡성군"), ("gurye", "구례군"),
            ("goheung", "고흥군"), ("boseong", "보성군"),
            ("hwasun", "화순군"), ("jangheung", "장흥군"),
            ("gangjin", "강진군"), ("haenam", "해남군"),
            ("yeongam", "영암군"), ("muan", "무안군"),
            ("hampyeong", "함평군"), ("yeonggwang", "영광군"),
            ("jangseong", "장성군"), ("wando", "완도군"),
            ("jindo", "진도군"), ("sinan", "신안군"),
        ],
    },
    "gb": {
        "name": "경북",
        "districts": [
            ("pohang", "포항시"), ("gyeongju", "경주시"),
            ("gimcheon", "김천시"), ("andong", "안동시"),
            ("gumi", "구미시"), ("yeongju", "영주시"),
            ("yeongcheon", "영천시"), ("sangju", "상주시"),
            ("mungyeong", "문경시"), ("gyeongsan", "경산시"),
            ("gunwi", "군위군"), ("uiseong", "의성군"),
            ("cheongsong", "청송군"), ("yeongyang", "영양군"),
            ("yeongdeok", "영덕군"), ("cheongdo", "청도군"),
            ("goryeong", "고령군"), ("seongju", "성주군"),
            ("chilgok", "칠곡군"), ("yecheon", "예천군"),
            ("bonghwa", "봉화군"), ("uljin", "울진군"),
            ("ulleung", "울릉군"),
        ],
    },
    "gn": {
        "name": "경남",
        "districts": [
            ("changwon", "창원시"), ("jinju", "진주시"),
            ("tongyeong", "통영시"), ("sacheon", "사천시"),
            ("gimhae", "김해시"), ("miryang", "밀양시"),
            ("geoje", "거제시"), ("yangsan", "양산시"),
            ("uiryeong", "의령군"), ("haman", "함안군"),
            ("changnyeong", "창녕군"), ("goseong_gn", "고성군"),
            ("namhae", "남해군"), ("hadong", "하동군"),
            ("sancheong", "산청군"), ("hamyang", "함양군"),
            ("geochang", "거창군"), ("hapcheon", "합천군"),
        ],
    },
    "jj": {
        "name": "제주",
        "districts": [
            ("jejusi", "제주시"), ("seogwipo", "서귀포시"),
        ],
    },
}

YAML_TEMPLATE = """  - id: {sid}
    name: {region_name} {district_name}
    org: {region_name} {district_name}청
    adapter: html_list
    url: "https://www.{domain}.go.kr/"
    search_url: "https://www.{domain}.go.kr/"
    rss_or_api: none_found
    notes: "{region_name} {district_name} 고시공고. URL 확인 필요."
"""


def main(out_path: str) -> int:
    lines: list[str] = []
    lines.append("\n  # ============================================================\n")
    lines.append("  # 218개 전국 시군구 (대구 8개 제외, 2026-06-04 추가)\n")
    lines.append("  # URL은 표준 영문 도메인 패턴. 실패 사이트는 reports 확인 후 수정.\n")
    lines.append("  # ============================================================\n")
    count = 0
    for region_id, info in REGIONS.items():
        lines.append(f"\n  # ── {info['name']} ({len(info['districts'])}개) ──\n")
        for domain, district_name in info["districts"]:
            sid = f"{region_id}_{domain}"
            lines.append(
                YAML_TEMPLATE.format(
                    sid=sid,
                    region_name=info["name"],
                    district_name=district_name,
                    domain=domain,
                )
            )
            count += 1
    Path(out_path).open("a", encoding="utf-8").write("".join(lines))
    print(f"appended {count} districts")
    return count


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "sources.yaml"
    main(target)
