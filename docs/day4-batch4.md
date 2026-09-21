# 第四天 · 第四批：重新开始与完整重置

本批继续在 feat/day4-animation 上完成重新开始按钮。
第四天的飞出、碰撞、失败与重开功能至此均已实现；开始界面、三关和通关切换仍属于第五天。

## 1. 运行观察

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe main.py
```

右侧“重新开始”按钮在游戏中、失败后和飞出期间均可使用。
点击后恢复 13 个箭头、3 次失误机会、普通游戏标题，并清除选中框和动画。

## 2. 初始布局与当前棋盘分开

原棋盘列表现在命名为 INITIAL_BOARD，作为恢复用的初始布局。
实际游玩使用 board；消除只修改 board。

```python
board = [row[:] for row in INITIAL_BOARD]
```

这是列表推导式，等价于下面的写法：

```python
board = []
for row in INITIAL_BOARD:
    board.append(row[:])
```

row[:] 为当前行创建一个新的列表。外层列表与内部每一行都独立，
所以执行 board[0][0] = None 不会改掉 INITIAL_BOARD[0][0]。

两种容易出错的写法：

- board = INITIAL_BOARD：两个名字指向同一个棋盘。
- board = INITIAL_BOARD.copy()：只复制外层，各行仍然共享。

当前格子只包含字符串和 None，这样逐行复制就足够。
如果以后格子改为可变的字典或列表，需要重新考虑更深层的复制。
大写命名是一种约定，并不会让 Python 自动禁止修改 INITIAL_BOARD。

## 3. 统一的 reset_game 函数

程序启动和点击重开都调用 reset_game()，避免两套初始化代码不一致。
函数集中恢复：

| 数据 | 恢复值 | 原因 |
| --- | --- | --- |
| board | 初始布局的逐行副本 | 已消除的箭头重新出现 |
| game_state | PLAYING | 失败后重新允许操作 |
| mistakes_remaining | MAX_MISTAKES | 恢复失误机会 |
| selected_cell | None | 清除旧黄色框 |
| flying_arrow | None | 防止旧动画继续删除新棋盘中的箭头 |
| collision_cell | None | 清除旧红色标记 |
| collision_remaining | 0.0 | 清除旧碰撞倒计时 |
| status_text | 初始操作提示 | 不再显示旧的失败或碰撞说明 |

remaining_arrows 每帧从棋盘重新统计，所以无需单独重置；字体、窗口和时钟可以继续使用。
重开不会创建另一个窗口，也不会递归调用主程序或启动第二个主循环。

## 4. 为什么函数里出现 global

```python
global board, game_state, selected_cell, mistakes_remaining, status_text
global flying_arrow, collision_cell, collision_remaining
```

主循环使用的是模块中的这些变量，而 reset_game 在函数内为它们重新赋值。
global 声明告诉 Python：这里要重新赋值的是模块里的名字。
如果没有声明，例如函数内的 game_state = PLAYING 只会创建局部变量，
函数结束后主循环中的失败状态仍然没有改变。

本批沿用现有的模块级变量结构，将这种集中修改收在一个函数内。
global 并不是所有函数都需要的；未来学习类或状态字典时也可以用其他结构组织状态。

## 5. 为什么先处理重开按钮

```python
if not running:
    continue

if restart_rect.collidepoint(event.pos):
    reset_game()
    restarted_this_frame = True
    continue

if restarted_this_frame or game_state != PLAYING or flying_arrow is not None:
    continue
```

顺序非常重要：先确认窗口没有关闭，再检查按钮，最后应用棋盘的限制。
如果先判断失败或飞出状态并 continue，按钮点击也会被跳过，就无法失败后重试或动画中重开。

按钮只响应左键按下。处理完后 continue，避免同一个按钮点击又走到“棋盘外点击”的逻辑，
把刚恢复的初始提示覆盖掉。

## 6. 重开这一帧的后续点击

每帧开始设置 restarted_this_frame = False；收到重开点击后改为 True。
这一帧余下的棋盘点击被忽略，避免已经排队的旧点击立刻影响新棋盘。
下一帧自动恢复接收棋盘点击。重复点击重开仍然可以执行，关闭窗口事件也照常处理。

## 7. 本人试玩顺序

1. 消除一个箭头，再点击一次受阻箭头，重开后应恢复 13 个箭头和 3 次机会。
2. 故意失误三次，出现失败后点击重开，再消除一个安全箭头，验证能够继续玩。
3. 点击第 4 行第 4 列的向右箭头，在它飞出期间重开；等待一秒，确认箭头没有被旧动画删除。
4. 点击第 1 行第 3 列的受阻箭头，变红期间重开，确认红色和黄色框立即消失。
5. 连续完成三轮“游玩 → 重开”，确认初始布局一直一致。

试着解释：为什么仅复制外层不够？为什么除了棋盘还要清空 flying_arrow？
为什么按钮判断必须在状态限制前面？global 改变的是哪一层的变量？

## 8. 本批验证

以下为 2026-09-17 的历史验证记录，当时的规则与交互检查全部通过；相关测试脚本现已移除。
新增 7 组重开检查通过：

1. 消除并失误后恢复，同时验证初始布局未被修改、内部行列表没有共享。
2. 失败后重开，随后能正常消除。
3. 飞出中，以及飞出与碰撞反馈并存时重开；等待后没有旧动画误删。
4. 碰撞变红期间重开，直接检查像素颜色恢复及所有反馈变量清空。
5. 连续三轮游玩重开，以及同一帧连点重开。
6. 右键、按钮右边界和下边界外点击不触发重开。
7. 重开当帧排队的后续棋盘点击不会改变新局，关闭事件仍可处理。

另查看失败与紧接着重开的离屏截图，按钮文字、布局和状态显示正常。
这些是自动化模拟与离屏画面检查，不代替本人实际试玩；本人耗时和修改需如实记录。
