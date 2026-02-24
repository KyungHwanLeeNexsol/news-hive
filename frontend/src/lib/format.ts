/**
 * Add spaces around Korean conjunctions/particles in sector names
 * for better readability.
 *
 * "반도체와반도체장비" → "반도체와 반도체장비"
 * "건강관리장비와용품" → "건강관리장비와 용품"
 * "에너지장비및서비스" → "에너지장비 및 서비스"
 * "섬유,의류,신발,호화품" → "섬유, 의류, 신발, 호화품"
 */
export function formatSectorName(name: string): string {
  return name
    // "와 " / "과 " — already spaced? skip. Otherwise add space after
    .replace(/(?<=.)([와과])(?=[가-힣])/g, "$1 ")
    // "및" — space before and after
    .replace(/(?<=[가-힣])및(?=[가-힣])/g, " 및 ")
    // "된" followed by text — "다각화된통신서비스" → "다각화된 통신서비스"
    .replace(/된(?=[가-힣])/g, "된 ")
    // comma without space — "섬유,의류" → "섬유, 의류"
    .replace(/,(?=\S)/g, ", ");
}
