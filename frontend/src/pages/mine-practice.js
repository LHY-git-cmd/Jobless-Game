/** 扫雷练习启动：等待身份确认后载入对应存档，游客也可直接练习。 */
import { initAuth } from '../auth.js';
import { createMinePracticeController } from '../game/mine-practice-controller.js';

const auth=initAuth();
await auth?.ready;
export const app=createMinePracticeController({user:auth?.currentUser??null});
