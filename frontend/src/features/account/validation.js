/** 登录输入规则：前后端按 Unicode 字符计数，汉字 3 单位、ASCII 字母数字 2 单位，上限 24。 */
// 固定 Unicode 15.1 已分配汉字范围，与 Python 一致；不接受块内未分配码位。
const hanRanges = "\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufa6d\\ufa70-\\ufad9"
  + "\\u{20000}-\\u{2a6df}\\u{2a700}-\\u{2b739}\\u{2b740}-\\u{2b81d}"
  + "\\u{2b820}-\\u{2cea1}\\u{2ceb0}-\\u{2ebe0}\\u{2ebf0}-\\u{2ee5d}"
  + "\\u{2f800}-\\u{2fa1d}\\u{30000}-\\u{3134a}\\u{31350}-\\u{323af}";
const han = new RegExp(`^[${hanRanges}]$`, "u");
const allowed = new RegExp(`^[A-Za-z0-9${hanRanges}]+$`, "u");

/** 逐 Unicode 字符计算权重，补充平面汉字不按 UTF-16 两个单元重复计数。 */
export function usernameUnits(value) {
  return [...value].reduce((units, char) => units + (han.test(char) ? 3 : 2), 0);
}

/** 用户名不做 trim；空白、标点和表情均提示用户修改。 */
export function validateUsername(value) {
  if (!value || !allowed.test(value) || value.endsWith("\n")) return "用户名只能包含汉字、英文字母和数字。";
  return usernameUnits(value) > 24 ? "用户名长度不能超过 12（汉字计 1.5）。" : "";
}

/** 密码保留原始内容，允许空格、粘贴与密码管理器填充。 */
export function validatePassword(value) {
  return [...value].length < 6 ? "密码至少需要 6 个字符。" : "";
}

