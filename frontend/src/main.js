/** 游戏页面启动入口：业务状态由各控制器实例管理。 */
import { createGameController } from './game/game-controller.js';

export const app = createGameController();
