/** 计时统一显示为分:秒，超过一小时显示时:分:秒。 */
export function formatTime(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(value / 60);
  const tail = String(value % 60).padStart(2, "0");
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${tail}`
    : `${String(minutes).padStart(2, "0")}:${tail}`;
}
