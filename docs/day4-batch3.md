# 第四天 · 第三批：游戏状态与失败画面

本批在 feat/day4-animation 分支继续开发，完成显式的游戏状态和失败结果显示。
重新开始按钮与恢复数据属于下一批。本批失败后可以关闭窗口，再运行程序试玩。

## 1. 这次改变了什么

之前已经能扣失误机会、显示失败文字，并通过次数是否耗尽来限制点击。
本批将游戏阶段明确记录为 game_state，让输入、更新和绘图依据同一个状态工作。

- 游戏中：顶部显示游戏名称和规则，允许点击箭头。
- 失败：顶部显示红色“本关失败”，说明棋盘操作已停止，保留失败时的棋盘。
- 失败后仍继续绘图、处理关闭事件，最后一次碰撞的变红计时也能结束。

## 2. 两个状态就是两个有含义的值

```python
PLAYING = "playing"
FAILED = "failed"
game_state = PLAYING
```

PLAYING 和 FAILED 是用大写名称表达的常量约定；其值仍是普通字符串。
game_state 保存当前阶段，初始为 PLAYING。
使用这些名称便于阅读，并减少在各处手写字符串导致的拼写错误。

这一批的状态转换：

```text
启动 → PLAYING
PLAYING --第三次有效失误，机会变为 0--> FAILED
```

前两次失误以及成功消除不会进入 FAILED。下一批再增加重开时返回 PLAYING 的流程。

## 3. 在事件发生时切换状态

受阻点击处：

```python
mistakes_remaining -= 1
if mistakes_remaining == 0:
    game_state = FAILED
    status_text = "失误次数已耗尽，本关失败"
```

mistakes_remaining 是剩余次数这个数据；次数归零则触发一次状态转换。
这里没有重建棋盘，也没有关闭窗口，所以已经消除的箭头不会自动回来。

状态立即在点击处理中更新。如果同一帧还有排队的鼠标点击，
处理后续点击时就能看到 FAILED，并阻止继续消除或把次数扣成负数。

## 4. 由状态控制输入与更新

鼠标左键处理的入口：

```python
if not running or game_state != PLAYING or flying_arrow is not None:
    continue
```

任一条件成立，就跳过这次棋盘点击。
continue 作用于当前的事件 for 循环，不会退出整个游戏主循环。

飞出位置更新也要求 game_state == PLAYING。
碰撞计时是短暂视觉反馈，继续在主循环中更新，不受失败状态影响。
因此失败后箭头颜色可以恢复，但游戏仍保持 FAILED。

## 5. 由状态决定画面

```python
if game_state == FAILED:
    screen.blit(failed_title_surface, failed_title_rect)
    screen.blit(failed_hint_surface, failed_hint_rect)
else:
    screen.blit(title_surface, title_rect)
    screen.blit(hint_surface, hint_rect)
```

失败标题和说明在主循环前渲染一次，循环里根据状态选择绘制哪一组。
棋盘、剩余数量和失误次数仍然显示，便于看清失败时的局面。
底部提示的颜色也根据 game_state 选择。

## 6. game_state 与 running 的区别

| 变量 | 回答的问题 | 失败后、关闭前 |
| --- | --- | --- |
| running | 程序主循环是否继续运行？ | True |
| game_state | 当前游戏处于什么阶段？ | FAILED |

如果失败时把 running 设为 False，主循环就会结束，随后 pygame.quit() 关闭窗口，
玩家便无法继续查看失败结果。
因此当前实现只在收到 QUIT 事件时把 running 设为 False。

## 7. 实际试玩与自检

```powershell
.\.venv\Scripts\python.exe main.py
```

1. 先点击第 1 行第 1 列的向上箭头，等它飞出，数量变为 12。
2. 点击第 1 行第 3 列的受阻箭头两次，确认仍显示普通游戏标题，机会剩 1。
3. 第三次点击同一箭头，顶部应立即切换为“本关失败”。
4. 再点击第 4 行第 4 列的安全箭头，应没有变化，数量保持 12。
5. 等待红色碰撞反馈恢复，确认失败标题仍存在。
6. 点击窗口关闭按钮，程序应正常退出。

尝试解释：为何不在失败时关闭窗口？状态在哪一行改变？
为何碰撞颜色恢复不代表游戏重新开始？同一帧的后续点击为何也能被阻止？

## 8. 验证记录

本批于 2026-09-16 至 2026-09-17 开发、检查并整理说明。
运行 test_logic.py 与 test_interaction.py，原有路径、数量、点击、飞出和碰撞检查全部通过。

新增 4 组检查通过：

1. 初始、成功消除和前两次失误都保持 PLAYING。
2. 第三次失误进入 FAILED，同帧及后续点击均被限制。
3. 消除部分箭头后再失败，保留已有进度，不自动重开。
4. 检查真实画布的标题像素：第三次失误后出现红色结果标题，随后二十个空帧仍继续绘制，
   碰撞颜色正常恢复，最后关闭事件正常处理。

另外查看了失败刚发生及碰撞颜色恢复后的离屏截图，文字与棋盘显示清晰。
以上是自动化模拟和离屏画面检查；本人试玩、学习耗时及人工修改需本人如实记录。
