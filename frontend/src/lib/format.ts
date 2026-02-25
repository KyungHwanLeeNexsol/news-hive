/**
 * Add spaces around Korean conjunctions/particles in sector names
 * for better readability.
 *
 * "에너지장비및서비스" → "에너지장비 및 서비스"
 * "섬유,의류,신발,호화품" → "섬유, 의류, 신발, 호화품"
 * "다각화된통신서비스" → "다각화된 통신서비스"
 *
 * Note: "와"/"과" rules removed — they falsely split words like
 * "생명과학" → "생명과 학". These sector names are kept as-is.
 */
export function formatSectorName(name: string): string {
  return name
    // "및" — space before and after
    .replace(/(?<=[가-힣])및(?=[가-힣])/g, " 및 ")
    // "된" followed by text — "다각화된통신서비스" → "다각화된 통신서비스"
    .replace(/된(?=[가-힣])/g, "된 ")
    // comma without space — "섬유,의류" → "섬유, 의류"
    .replace(/,(?=\S)/g, ", ");
}
