工作模式基本符合了设想的要求，主agent作为director，并发调用subagents做各种任务，比如记忆召回，比如审查，比如搜索确认事实，然后阻塞等到收集的信息返回

优秀的点：

1. AI修改loop模式的预设为agent预设

2. agent提取预设或提取用户要求为skill，给sub agents挂载，并允许项目(角色卡)级覆写

3. 把agent的所有操作包装成tools（比如写草稿，比如读草稿，比如），而不是用函数去parse返回值

4. 清晰可追踪的运行轨迹，方便查看每一步agent和subagent的思考，工具调用和结果，以方便定位问题

5. 允许用户自己定义agent角色和提示词

问题：

1. 太重了，配置太繁琐，指引过于模糊，东一块西一块
——各agent的协作工作流应该实现类似comfyui的节点、拖拽、连线式交互，从而又简单易用，又高度可自定义。实现允许用户自己定义agent的角色、提示词、工具、skills、模型。最终的工作流应该是一个有向无环图。
——模型配置、连接配置这些应该放在一个地方配置，而不是多级子菜单，且每个agent都要能轻松配置并切换模型，松解耦

2. director agent出现非预期行为：critics工具调用后，直接回到了初始状态开始重复调用scout、brainstorm……，最终因撞到subagents上限，才让主agent发现并调用finalize
——不该让主agent既做director，又做writer，这两个角色应该隔离开。决策者/执行者。
——自审查意义不大，且自审查极易形成环形调用，应该ban

3. token耗费巨大
——上下文污染严重，现在应该相当于是每个subagent都会看到主agent的全部请求历史，导致token爆炸。而且，有些上下文信息，sub agents不应该知道，这些信息也会污染影响sub agent做自己的task。
——**每个agent应且只应看到自己需要知道的信息**，此外工具调用（即主agent，director调起工具）应当有参数能让director给sub agent传递消息。
——逻辑拆解： 第一轮需要看到什么 => 第X轮需要看到什么 => 第X+1轮需要看到什么


## 应该吸收的地方

全局配置与项目覆写

AI解析自动生成skills与合并前端

内置agents

用于创建新agent角色的agent