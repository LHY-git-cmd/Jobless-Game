/** 照明分步教学：新版目标格与提示来自尝试绑定题目，兼容旧三步草稿。 */
const LEGACY_STEPS=[
  {title:'放下第一盏灯',text:'在任意白格放灯，观察光线沿横竖方向传播。'},
  {title:'练习撤灯',text:'再次点击刚才的灯泡撤灯，放错也可以修改。'},
  {title:'完成这一盘',text:'照亮所有白格、灯泡不互照，并满足每个数字。'},
];

/** 普通关返回空步骤；旧教学仍按原有三步完成，旧尝试不会被套用新目标。 */
export function akariTutorialSteps(puzzle){
  if(!puzzle?.tutorial)return [];
  return Array.isArray(puzzle.tutorial_steps)&&puzzle.tutorial_steps.length?puzzle.tutorial_steps:LEGACY_STEPS;
}
