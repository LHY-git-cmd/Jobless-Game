/** 扫雷练习启动：等待身份确认后载入对应存档，游客也可直接练习。 */
import { initAuth } from '../../features/account/auth.js';
import { createMinePracticeController } from './practice-controller.js';

const auth=initAuth();
await auth?.ready;
export const app=createMinePracticeController({user:auth?.currentUser??null});
